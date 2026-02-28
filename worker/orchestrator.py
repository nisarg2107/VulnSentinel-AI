"""Worker orchestration across RabbitMQ, Postgres, RustFS, Syft, Grype, and VEX."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pika

from artifact_integrity import run_artifact_integrity_pass
from db import Database
from grype_logic import report_key_for_scan, run_grype_report, write_sbom_temp_file
from infra import Postgres, RabbitMQ, RustFS, parse_bool_env, parse_int_env
from syft_logic import run_syft_sbom, sbom_key_for_digest
from vex_logic import extract_findings
from worker_helpers import detect_tool_versions, image_name_from_ref, safe_ack, safe_nack


# Configure root logging using LOG_LEVEL.
def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )


# Process one queue message end-to-end and persist scan results.
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


# Consume queue messages forever with reconnect/backoff behavior.
def run_worker(rabbitmq: RabbitMQ, postgres: Postgres, rustfs: RustFS, tool_versions: dict[str, str]) -> None:
    reconnect_delay = rabbitmq.reconnect_initial_delay_seconds

    # Handle and ACK/NACK one delivery.
    def callback(
        ch: pika.adapters.blocking_connection.BlockingChannel,
        method: Any,
        _properties: Any,
        body: bytes,
    ) -> None:
        delivery_tag = method.delivery_tag
        try:
            process_message(body=body, postgres=postgres, rustfs=rustfs, tool_versions=tool_versions)
            safe_ack(ch, delivery_tag=delivery_tag)
        except Exception:
            logging.exception("Message processing failed")
            safe_nack(ch, delivery_tag=delivery_tag, requeue=rabbitmq.requeue_on_error)

    while True:
        connection: pika.BlockingConnection | None = None
        channel: pika.adapters.blocking_connection.BlockingChannel | None = None
        try:
            connection = rabbitmq.connect()
            channel = connection.channel()
            channel.queue_declare(queue=rabbitmq.queue, durable=True)
            channel.basic_qos(prefetch_count=rabbitmq.prefetch)
            channel.basic_consume(queue=rabbitmq.queue, on_message_callback=callback)

            reconnect_delay = rabbitmq.reconnect_initial_delay_seconds
            logging.info(
                "Worker started. queue=%s prefetch=%s",
                rabbitmq.queue,
                rabbitmq.prefetch,
            )
            channel.start_consuming()
            logging.warning("RabbitMQ consuming stopped, reconnecting")
        except KeyboardInterrupt:
            logging.info("Worker interrupted; shutting down")
            return
        except pika.exceptions.AMQPError:
            logging.exception("RabbitMQ error; reconnecting in %ss", reconnect_delay)
        except Exception:
            logging.exception("Unexpected worker loop error; reconnecting in %ss", reconnect_delay)
        finally:
            if channel is not None and channel.is_open:
                try:
                    channel.close()
                except Exception:
                    logging.debug("Failed to close channel cleanly", exc_info=True)
            if connection is not None and connection.is_open:
                try:
                    connection.close()
                except Exception:
                    logging.debug("Failed to close connection cleanly", exc_info=True)

        time.sleep(reconnect_delay)
        reconnect_delay = min(
            reconnect_delay * 2,
            rabbitmq.reconnect_max_delay_seconds,
        )


# Build CLI flags for integrity-check modes.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VulnSentinel worker")
    parser.add_argument(
        "--artifact-integrity-check",
        action="store_true",
        help="Run one artifact integrity validation/repair pass before consuming.",
    )
    parser.add_argument(
        "--artifact-integrity-check-only",
        action="store_true",
        help="Run one artifact integrity validation/repair pass and exit.",
    )
    parser.add_argument(
        "--artifact-integrity-limit",
        type=int,
        default=parse_int_env("ARTIFACT_INTEGRITY_LIMIT", 200, minimum=1),
        help="Maximum number of scans checked per integrity pass.",
    )
    return parser


# Entry point that optionally runs integrity checks before consuming.
def run(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)

    rabbitmq = RabbitMQ.from_env()
    postgres = Postgres.from_env()
    rustfs = RustFS.from_env()
    tool_versions = detect_tool_versions()

    run_integrity_check = (
        args.artifact_integrity_check
        or args.artifact_integrity_check_only
        or parse_bool_env("ARTIFACT_INTEGRITY_CHECK_ON_START", False)
    )

    integrity_summary: dict[str, int] | None = None
    if run_integrity_check:
        try:
            integrity_summary = run_artifact_integrity_pass(
                postgres=postgres,
                rustfs=rustfs,
                tool_versions=tool_versions,
                limit=max(1, args.artifact_integrity_limit),
            )
        except Exception:
            logging.exception("Artifact integrity pass failed")
            if args.artifact_integrity_check_only:
                return 1

    if args.artifact_integrity_check_only:
        unresolved = 0 if integrity_summary is None else integrity_summary["repair_required"]
        return 1 if unresolved > 0 else 0

    run_worker(
        rabbitmq=rabbitmq,
        postgres=postgres,
        rustfs=rustfs,
        tool_versions=tool_versions,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
