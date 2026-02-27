"""VEX mapping and finding extraction."""

from __future__ import annotations

from typing import Any

SEVERITY_ALLOWED = {"Unknown", "Negligible", "Low", "Medium", "High", "Critical"}


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
