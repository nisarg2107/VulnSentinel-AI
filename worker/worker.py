#!/usr/bin/env python3
"""Consume scan jobs, run Syft/Grype, store blobs in RustFS, persist findings in Postgres."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import pika
import psycopg2
from botocore.config import Config
from botocore.exceptions import ClientError
from psycopg2.extras import Json


SEVERITY_ALLOWED = {"Unknown", "Negligible", "Low", "Medium", "High", "Critical"}


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def canonical_severity(value: str | None) -> str:
    if not value:
        return "Unknown"
    normalized = value.strip().lower()
    mapping = {
        "unknown": "Unknown",
        "negligible": "Negligible",
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "critical": "Critical",
    }
    return mapping.get(normalized, "Unknown")


def parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def default_local_service_host() -> str:
    configured = os.getenv("LOCAL_SERVICES_HOST")
    if configured:
        return configured
    if os.path.exists("/.dockerenv"):
        return "host.docker.internal"
    return "localhost"


def default_rustfs_endpoint() -> str:
    return f"http://{default_local_service_host()}:9000"


def run_json_command(cmd: list[str]) -> dict[str, Any]:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def run_text_command(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def image_name_from_ref(image_ref: str) -> str:
    if "@sha256:" in image_ref:
        return image_ref.split("@", 1)[0]
    return image_ref


def first_fix_version(vulnerability: dict[str, Any]) -> str | None:
    fix = vulnerability.get("fix") or {}
    versions = fix.get("versions") or []
    if isinstance(versions, list) and versions:
        return str(versions[0])
    return None


def max_cvss_score(vulnerability: dict[str, Any]) -> float | None:
    cvss_items = vulnerability.get("cvss") or []
    best: float | None = None
    for item in cvss_items:
        if not isinstance(item, dict):
            continue
        score = item.get("baseScore")
        if score is None:
            score = item.get("score")
        if isinstance(score, (int, float)):
            if best is None or float(score) > best:
                best = float(score)
    return best


@dataclass
class Settings:
    rabbitmq_host: str = os.getenv("RABBITMQ_HOST", default_local_service_host())
    rabbitmq_port: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    rabbitmq_user: str = os.getenv("RABBITMQ_USER", "guest")
    rabbitmq_password: str = os.getenv("RABBITMQ_PASSWORD", "guest")
    rabbitmq_vhost: str = os.getenv("RABBITMQ_VHOST", "/")
    rabbitmq_queue: str = os.getenv("RABBITMQ_QUEUE", "scan_jobs")
    rabbitmq_prefetch: int = int(os.getenv("RABBITMQ_PREFETCH", "1"))
    requeue_on_error: bool = parse_bool_env("RABBITMQ_REQUEUE_ON_ERROR", False)

    postgres_host: str = os.getenv("POSTGRES_HOST", default_local_service_host())
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_user: str = os.getenv("POSTGRES_USER", "postgres")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    postgres_db: str = os.getenv("POSTGRES_DB", "vulnsentinel")

    rustfs_endpoint: str = os.getenv("RUSTFS_ENDPOINT", default_rustfs_endpoint())
    rustfs_access_key: str = os.getenv("RUSTFS_ACCESS_KEY", "rustfsadmin")
    rustfs_secret_key: str = os.getenv("RUSTFS_SECRET_KEY", "rustfsadmin")
    rustfs_region: str = os.getenv("RUSTFS_REGION", "us-east-1")
    rustfs_bucket: str = os.getenv("RUSTFS_BUCKET", "sboms")
    rustfs_auto_create_bucket: bool = parse_bool_env("RUSTFS_AUTO_CREATE_BUCKET", True)


class RustFsStore:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.rustfs_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.rustfs_endpoint,
            aws_access_key_id=settings.rustfs_access_key,
            aws_secret_access_key=settings.rustfs_secret_key,
            region_name=settings.rustfs_region,
            config=Config(s3={"addressing_style": "path"}),
        )

        if settings.rustfs_auto_create_bucket:
            self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code")
            if code in {"404", "NoSuchBucket", "NotFound"}:
                self.client.create_bucket(Bucket=self.bucket)
                logging.info("Created RustFS bucket: %s", self.bucket)
            else:
                raise

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )


class Database:
    def __init__(self, settings: Settings) -> None:
        self.conn = psycopg2.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            dbname=settings.postgres_db,
        )
        self.conn.autocommit = False

    def close(self) -> None:
        self.conn.close()

    def upsert_asset(self, image_digest: str, image_name: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO assets (image_digest, image_name)
                VALUES (%s, %s)
                ON CONFLICT (image_digest)
                DO UPDATE SET image_name = EXCLUDED.image_name
                RETURNING id
                """,
                (image_digest, image_name),
            )
            row = cur.fetchone()
            assert row is not None
            return int(row[0])

    def insert_scan(
        self,
        asset_id: int,
        job_id: str | None,
        context: dict[str, Any],
        tool_versions: dict[str, Any],
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scans (asset_id, job_id, status, context, tool_versions)
                VALUES (%s, %s, 'running', %s, %s)
                RETURNING id
                """,
                (asset_id, job_id, Json(context), Json(tool_versions)),
            )
            row = cur.fetchone()
            assert row is not None
            return int(row[0])

    def complete_scan(
        self,
        scan_id: int,
        tool_versions: dict[str, Any],
        sbom_key: str,
        sbom_data: bytes,
        report_key: str,
        report_data: bytes,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE scans
                SET status = 'completed',
                    finished_at = now(),
                    tool_versions = %s,
                    sbom_object_key = %s,
                    sbom_sha256 = %s,
                    sbom_bytes = %s,
                    report_object_key = %s,
                    report_sha256 = %s,
                    report_bytes = %s,
                    error = NULL
                WHERE id = %s
                """,
                (
                    Json(tool_versions),
                    sbom_key,
                    sha256_hex(sbom_data),
                    len(sbom_data),
                    report_key,
                    sha256_hex(report_data),
                    len(report_data),
                    scan_id,
                ),
            )

    def fail_scan(self, scan_id: int, error: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE scans
                SET status = 'failed',
                    finished_at = now(),
                    error = %s
                WHERE id = %s
                """,
                (error[:4000], scan_id),
            )

    def insert_findings(self, scan_id: int, findings: list[dict[str, Any]]) -> None:
        if not findings:
            return

        with self.conn.cursor() as cur:
            for finding in findings:
                cur.execute(
                    """
                    INSERT INTO scan_results (
                        scan_id,
                        vuln_id,
                        package_name,
                        package_version,
                        package_type,
                        package_path,
                        raw_severity,
                        effective_severity,
                        status,
                        vex_justification,
                        fix_version,
                        cvss_score,
                        raw_finding
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        scan_id,
                        finding["vuln_id"],
                        finding["package_name"],
                        finding["package_version"],
                        finding["package_type"],
                        finding["package_path"],
                        finding["raw_severity"],
                        finding["effective_severity"],
                        finding["status"],
                        finding["vex_justification"],
                        finding["fix_version"],
                        finding["cvss_score"],
                        Json(finding["raw_finding"]),
                    ),
                )


def detect_tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    try:
        versions["syft"] = run_text_command(["syft", "version"])
    except Exception as exc:  # pragma: no cover
        versions["syft"] = f"error: {exc}"

    try:
        versions["grype"] = run_text_command(["grype", "version"])
    except Exception as exc:  # pragma: no cover
        versions["grype"] = f"error: {exc}"

    return versions


def sbom_key_for_digest(image_digest: str) -> str:
    safe = image_digest.replace(":", "_")
    return f"sboms/{safe}.syft.json"


def report_key_for_scan(scan_id: int, image_digest: str) -> str:
    safe = image_digest.replace(":", "_")
    return f"reports/{safe}.scan-{scan_id}.grype.json"


def write_temp_file(prefix: str, suffix: str, data: bytes) -> Path:
    tmp = tempfile.NamedTemporaryFile(prefix=prefix, suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.flush()
        return Path(tmp.name)
    finally:
        tmp.close()


def run_syft_sbom(image_ref: str) -> bytes:
    result = subprocess.run(
        ["syft", image_ref, "-o", "json"],
        check=True,
        capture_output=True,
        text=False,
    )
    return result.stdout


def run_grype_report(sbom_path: Path) -> bytes:
    result = subprocess.run(
        ["grype", f"sbom:{sbom_path}", "-o", "json"],
        check=True,
        capture_output=True,
        text=False,
    )
    return result.stdout


def extract_package_path(match: dict[str, Any]) -> str | None:
    artifact = match.get("artifact") or {}
    locations = artifact.get("locations") or []
    if isinstance(locations, list) and locations:
        first = locations[0]
        if isinstance(first, dict):
            path = first.get("path")
            if path:
                return str(path)
    return None


def apply_vex(raw_severity: str, context: dict[str, Any]) -> tuple[str, str, str | None]:
    exposed_raw = context.get("is_exposed_public")
    exposed = exposed_raw if isinstance(exposed_raw, bool) else None

    if raw_severity == "Critical" and exposed is False:
        return (
            "High",
            "not_affected",
            "vulnerable_code_not_in_execute_path",
        )

    return raw_severity, "affected", None


def extract_findings(report: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    matches = report.get("matches") or []
    findings: list[dict[str, Any]] = []

    for match in matches:
        if not isinstance(match, dict):
            continue

        vulnerability = match.get("vulnerability") or {}
        artifact = match.get("artifact") or {}

        vuln_id = str(vulnerability.get("id") or "UNKNOWN")
        raw_severity = canonical_severity(vulnerability.get("severity"))
        effective_severity, status, vex_justification = apply_vex(raw_severity, context)
        if effective_severity not in SEVERITY_ALLOWED:
            effective_severity = "Unknown"

        package_name = str(artifact.get("name") or "unknown")
        package_version = artifact.get("version")
        package_type = artifact.get("type")
        package_path = extract_package_path(match)

        raw_finding = {
            "vulnerability": {
                "id": vulnerability.get("id"),
                "severity": vulnerability.get("severity"),
                "namespace": vulnerability.get("namespace"),
                "dataSource": vulnerability.get("dataSource"),
            },
            "artifact": {
                "name": artifact.get("name"),
                "version": artifact.get("version"),
                "type": artifact.get("type"),
                "locations": artifact.get("locations"),
            },
            "matchDetails": match.get("matchDetails"),
        }

        findings.append(
            {
                "vuln_id": vuln_id,
                "package_name": package_name,
                "package_version": str(package_version) if package_version else None,
                "package_type": str(package_type) if package_type else None,
                "package_path": str(package_path) if package_path else None,
                "raw_severity": raw_severity,
                "effective_severity": effective_severity,
                "status": status,
                "vex_justification": vex_justification,
                "fix_version": first_fix_version(vulnerability),
                "cvss_score": max_cvss_score(vulnerability),
                "raw_finding": raw_finding,
            }
        )

    return findings


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = RustFsStore(settings)
        self.tool_versions = detect_tool_versions()

    def run(self) -> None:
        credentials = pika.PlainCredentials(
            self.settings.rabbitmq_user,
            self.settings.rabbitmq_password,
        )
        params = pika.ConnectionParameters(
            host=self.settings.rabbitmq_host,
            port=self.settings.rabbitmq_port,
            virtual_host=self.settings.rabbitmq_vhost,
            credentials=credentials,
        )

        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.queue_declare(queue=self.settings.rabbitmq_queue, durable=True)
        channel.basic_qos(prefetch_count=self.settings.rabbitmq_prefetch)

        def callback(ch: pika.adapters.blocking_connection.BlockingChannel, method, _properties, body: bytes) -> None:
            delivery_tag = method.delivery_tag
            try:
                self.process_message(body)
                ch.basic_ack(delivery_tag=delivery_tag)
            except Exception:
                logging.exception("Message processing failed")
                ch.basic_nack(delivery_tag=delivery_tag, requeue=self.settings.requeue_on_error)

        logging.info("Worker started. queue=%s", self.settings.rabbitmq_queue)
        channel.basic_consume(queue=self.settings.rabbitmq_queue, on_message_callback=callback)
        channel.start_consuming()

    def process_message(self, body: bytes) -> None:
        payload = json.loads(body.decode("utf-8"))
        image_ref = str(payload["image_ref"])
        image_digest = str(payload["image_digest"])
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}

        job_id = None
        raw_job_id = payload.get("job_id")
        if raw_job_id:
            try:
                job_id = str(uuid.UUID(str(raw_job_id)))
            except ValueError:
                logging.warning("Invalid job_id=%s, storing NULL", raw_job_id)

        db = Database(self.settings)
        scan_id: int | None = None
        sbom_file: Path | None = None
        try:
            image_name = image_name_from_ref(image_ref)
            asset_id = db.upsert_asset(image_digest=image_digest, image_name=image_name)
            scan_id = db.insert_scan(
                asset_id=asset_id,
                job_id=job_id,
                context=context,
                tool_versions=self.tool_versions,
            )
            db.conn.commit()

            sbom_key = sbom_key_for_digest(image_digest)
            if self.store.exists(sbom_key):
                logging.info("SBOM cache hit for %s", image_digest)
                sbom_data = self.store.get_bytes(sbom_key)
            else:
                logging.info("SBOM cache miss for %s; running syft", image_digest)
                sbom_data = run_syft_sbom(image_ref)
                self.store.put_bytes(sbom_key, sbom_data, "application/json")

            sbom_file = write_temp_file(prefix="sbom-", suffix=".json", data=sbom_data)
            report_data = run_grype_report(sbom_file)
            report = json.loads(report_data.decode("utf-8"))
            findings = extract_findings(report, context)

            db.insert_findings(scan_id, findings)
            report_key = report_key_for_scan(scan_id, image_digest)
            self.store.put_bytes(report_key, report_data, "application/json")
            db.complete_scan(
                scan_id=scan_id,
                tool_versions=self.tool_versions,
                sbom_key=sbom_key,
                sbom_data=sbom_data,
                report_key=report_key,
                report_data=report_data,
            )
            db.conn.commit()

            logging.info(
                "Completed scan scan_id=%s image_digest=%s findings=%s",
                scan_id,
                image_digest,
                len(findings),
            )
        except Exception as exc:
            db.conn.rollback()
            if scan_id is not None:
                try:
                    db.fail_scan(scan_id, str(exc))
                    db.conn.commit()
                except Exception:
                    db.conn.rollback()
                    logging.exception("Failed to mark scan failed scan_id=%s", scan_id)
            raise
        finally:
            if sbom_file is not None:
                try:
                    sbom_file.unlink(missing_ok=True)
                except Exception:
                    logging.warning("Failed to delete temp SBOM file: %s", sbom_file)
            db.close()


def main() -> int:
    configure_logging()
    settings = Settings()
    worker = Worker(settings)
    worker.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
