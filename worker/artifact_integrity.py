"""Artifact integrity checks and repair routines."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from db import Database
from grype_logic import report_key_for_scan, run_grype_report, write_sbom_temp_file
from infra import Postgres, RustFS
from syft_logic import run_syft_sbom, sbom_key_for_digest
from worker_helpers import image_ref_from_asset


# Rebuild and repersist missing scan artifacts for a single scan row.
def repair_scan_artifacts(
    scan: dict[str, Any],
    postgres: Postgres,
    rustfs: RustFS,
    tool_versions: dict[str, str],
) -> bool:
    scan_id = int(scan["scan_id"])
    image_name = str(scan["image_name"])
    image_digest = str(scan["image_digest"])
    current_sbom_key = scan.get("sbom_object_key")
    current_report_key = scan.get("report_object_key")

    sbom_key = str(current_sbom_key) if current_sbom_key else sbom_key_for_digest(image_digest)
    report_key = str(current_report_key) if current_report_key else report_key_for_scan(scan_id, image_digest)

    sbom_exists = bool(current_sbom_key) and rustfs.exists(sbom_key)
    report_exists = bool(current_report_key) and rustfs.exists(report_key)

    db = Database(postgres)
    sbom_file: Path | None = None
    try:
        sbom_data: bytes | None = None
        report_data: bytes | None = None

        if not sbom_exists:
            image_ref = image_ref_from_asset(image_name, image_digest)
            logging.info("Rebuilding SBOM for scan_id=%s image_ref=%s", scan_id, image_ref)
            sbom_data = run_syft_sbom(image_ref)
            rustfs.put_bytes(sbom_key, sbom_data, "application/json")

        if not report_exists:
            if sbom_data is None:
                sbom_data = rustfs.get_bytes(sbom_key)
            sbom_file = write_sbom_temp_file(sbom_data)
            report_data = run_grype_report(sbom_file)
            rustfs.put_bytes(report_key, report_data, "application/json")

        db.complete_scan_repair(
            scan_id=scan_id,
            tool_versions=tool_versions,
            sbom_key=sbom_key,
            sbom_data=sbom_data,
            report_key=report_key,
            report_data=report_data,
        )
        db.commit()
        logging.info("Artifact repair succeeded scan_id=%s", scan_id)
        return True
    except Exception as exc:
        db.rollback()
        try:
            db.mark_scan_repair_required(scan_id, f"artifact_integrity_repair_failed: {exc}")
            db.commit()
        except Exception:
            db.rollback()
            logging.exception("Failed to mark scan repair_required scan_id=%s", scan_id)
        logging.exception("Artifact repair failed scan_id=%s", scan_id)
        return False
    finally:
        if sbom_file is not None:
            try:
                sbom_file.unlink(missing_ok=True)
            except Exception:
                logging.warning("Failed to delete temp SBOM file: %s", sbom_file)
        db.close()


# Validate artifact keys for recent scans and repair missing objects.
def run_artifact_integrity_pass(
    postgres: Postgres,
    rustfs: RustFS,
    tool_versions: dict[str, str],
    limit: int,
) -> dict[str, int]:
    db = Database(postgres)
    try:
        candidates = db.fetch_integrity_candidates(limit=limit)
    finally:
        db.close()

    summary = {
        "checked": 0,
        "healthy": 0,
        "repaired": 0,
        "repair_required": 0,
    }

    for scan in candidates:
        summary["checked"] += 1
        scan_id = int(scan["scan_id"])

        sbom_key = scan.get("sbom_object_key")
        report_key = scan.get("report_object_key")
        sbom_exists = bool(sbom_key) and rustfs.exists(str(sbom_key))
        report_exists = bool(report_key) and rustfs.exists(str(report_key))

        if sbom_exists and report_exists:
            summary["healthy"] += 1
            continue

        missing: list[str] = []
        if not sbom_exists:
            missing.append("sbom")
        if not report_exists:
            missing.append("report")

        logging.warning(
            "Artifact integrity mismatch scan_id=%s missing=%s",
            scan_id,
            ",".join(missing),
        )

        if repair_scan_artifacts(scan=scan, postgres=postgres, rustfs=rustfs, tool_versions=tool_versions):
            summary["repaired"] += 1
        else:
            summary["repair_required"] += 1

    logging.info(
        "Artifact integrity pass complete checked=%s healthy=%s repaired=%s repair_required=%s",
        summary["checked"],
        summary["healthy"],
        summary["repaired"],
        summary["repair_required"],
    )
    return summary
