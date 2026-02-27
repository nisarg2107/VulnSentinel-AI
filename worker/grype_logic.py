"""Grype report generation helpers."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def detect_grype_version() -> str:
    result = subprocess.run(["grype", "version"], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def report_key_for_scan(scan_id: int, image_digest: str) -> str:
    safe = image_digest.replace(":", "_")
    return f"reports/{safe}.scan-{scan_id}.grype.json"


def write_sbom_temp_file(sbom_data: bytes) -> Path:
    tmp = tempfile.NamedTemporaryFile(prefix="sbom-", suffix=".json", delete=False)
    try:
        tmp.write(sbom_data)
        tmp.flush()
        return Path(tmp.name)
    finally:
        tmp.close()


def run_grype_report(sbom_path: Path) -> bytes:
    result = subprocess.run(
        ["grype", f"sbom:{sbom_path}", "-o", "json"],
        check=True,
        capture_output=True,
        text=False,
    )
    return result.stdout
