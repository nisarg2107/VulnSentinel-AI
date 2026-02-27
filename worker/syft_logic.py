"""Syft SBOM generation helpers."""

from __future__ import annotations

import subprocess


def detect_syft_version() -> str:
    result = subprocess.run(["syft", "version"], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def sbom_key_for_digest(image_digest: str) -> str:
    safe = image_digest.replace(":", "_")
    return f"sboms/{safe}.syft.json"


def run_syft_sbom(image_ref: str) -> bytes:
    result = subprocess.run(
        ["syft", image_ref, "-o", "json"],
        check=True,
        capture_output=True,
        text=False,
    )
    return result.stdout
