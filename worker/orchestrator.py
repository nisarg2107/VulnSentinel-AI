"""Worker orchestration across RabbitMQ, Postgres, RustFS, Syft, Grype, and VEX."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import pika

from db import Database
from grype_logic import detect_grype_version, report_key_for_scan, run_grype_report, write_sbom_temp_file
from infra import Postgres, RabbitMQ, RustFS
from syft_logic import detect_syft_version, run_syft_sbom, sbom_key_for_digest
from vex_logic import extract_findings


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def image_name_from_ref(image_ref: str) -> str:
    if "@sha256:" in image_ref:
        return image_ref.split("@", 1)[0]
    return image_ref


def detect_tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    try:
        versions["syft"] = detect_syft_version()
    except Exception as exc:  # pragma: no cover
        versions["syft"] = f"error: {exc}"

    try:
        versions["grype"] = detect_grype_version()
    except Exception as exc:  # pragma: no cover
        versions["grype"] = f"error: {exc}"

    return versions


def process_message(body: bytes, postgres: Postgres, rustfs: RustFS, tool_versions: dict[str, str]) -> None:
    payload = json.loads(body.decode("utf-8"))
    image_ref = str(payload["image_ref"])
    image_digest = str(payload["image_digest"])
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}

    job_id: str | None = None
    raw_job_id = payload.get("job_id")
    if raw_job_id:
        try:
            job_id = str(uuid.UUID(str(raw_job_id)))
        except ValueError:
            logging.warning("Invalid job_id=%s, storing NULL", raw_job_id)

    db = Database(postgres)
    scan_id: int | None = None
    sbom_file: Path | None = None
    try:
        asset_id = db.upsert_asset(
            image_digest=image_digest,
            image_name=image_name_from_ref(image_ref),
        )
        scan_id = db.insert_scan(
            asset_id=asset_id,
            job_id=job_id,
            context=context,
            tool_versions=tool_versions,
        )
        db.commit()

        sbom_key = sbom_key_for_digest(image_digest)
        if rustfs.exists(sbom_key):
            logging.info("SBOM cache hit for %s", image_digest)
            sbom_data = rustfs.get_bytes(sbom_key)
        else:
            logging.info("SBOM cache miss for %s; running syft", image_digest)
            sbom_data = run_syft_sbom(image_ref)
            rustfs.put_bytes(sbom_key, sbom_data, "application/json")

        sbom_file = write_sbom_temp_file(sbom_data)
        report_data = run_grype_report(sbom_file)
        report = json.loads(report_data.decode("utf-8"))
        findings = extract_findings(report, context)

        db.insert_findings(scan_id, findings)
        report_key = report_key_for_scan(scan_id, image_digest)
        rustfs.put_bytes(report_key, report_data, "application/json")
        db.complete_scan(
            scan_id=scan_id,
            tool_versions=tool_versions,
            sbom_key=sbom_key,
            sbom_data=sbom_data,
            report_key=report_key,
            report_data=report_data,
        )
        db.commit()

        logging.info(
            "Completed scan scan_id=%s image_digest=%s findings=%s",
            scan_id,
            image_digest,
            len(findings),
        )
    except Exception as exc:
        db.rollback()
        if scan_id is not None:
            try:
                db.fail_scan(scan_id, str(exc))
                db.commit()
            except Exception:
                db.rollback()
                logging.exception("Failed to mark scan failed scan_id=%s", scan_id)
        raise
    finally:
        if sbom_file is not None:
            try:
                sbom_file.unlink(missing_ok=True)
            except Exception:
                logging.warning("Failed to delete temp SBOM file: %s", sbom_file)
        db.close()


def run_worker(rabbitmq: RabbitMQ, postgres: Postgres, rustfs: RustFS) -> None:
    tool_versions = detect_tool_versions()
    connection = rabbitmq.connect()
    channel = connection.channel()
    channel.queue_declare(queue=rabbitmq.queue, durable=True)
    channel.basic_qos(prefetch_count=rabbitmq.prefetch)

    def callback(
        ch: pika.adapters.blocking_connection.BlockingChannel,
        method: Any,
        _properties: Any,
        body: bytes,
    ) -> None:
        delivery_tag = method.delivery_tag
        try:
            process_message(body=body, postgres=postgres, rustfs=rustfs, tool_versions=tool_versions)
            ch.basic_ack(delivery_tag=delivery_tag)
        except Exception:
            logging.exception("Message processing failed")
            ch.basic_nack(delivery_tag=delivery_tag, requeue=rabbitmq.requeue_on_error)

    logging.info("Worker started. queue=%s", rabbitmq.queue)
    channel.basic_consume(queue=rabbitmq.queue, on_message_callback=callback)
    channel.start_consuming()



def run() -> int:
    configure_logging()
    run_worker(
        rabbitmq=RabbitMQ.from_env(),
        postgres=Postgres.from_env(),
        rustfs=RustFS.from_env(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

