# Message Schemas

## RabbitMQ: `scan_jobs`

**Routing Key:** `scan.trigger`

```json
{
  "job_id": "uuid-v4",
  "timestamp": "ISO-8601",
  "image_ref": "docker.io/library/nginx@sha256:12345...",
  "image_digest": "sha256:12345...",
  "context": {
    "environment": "local-docker-test",
    "is_exposed_public": true,
    "is_privileged": false
  }
}
```

## Database Schema (PostgreSQL)

### Table: `assets`

- `id` (PK)
- `image_digest` (Unique, SHA256 digest format validated)
- `image_name`
- `created_at` (default `now()`)
- `last_scanned_at` (default `now()`, updated when scan finishes)

### Table: `scans`

- `id` (PK)
- `asset_id` (FK -> `assets.id`)
- `job_id` (UUID, unique when present)
- `status` (`queued | running | completed | failed | cancelled | repair_required`)
- `started_at`, `finished_at`, `created_at`
- `error`
- `context` (JSONB runtime snapshot from queue payload)
- `tool_versions` (JSONB for syft/grype/vunnel versions)
- `sbom_object_key`, `sbom_sha256`, `sbom_bytes` (RustFS object pointer + metadata)
- `report_object_key`, `report_sha256`, `report_bytes` (RustFS object pointer + metadata)

### Table: `scan_results`

- `id` (PK)
- `scan_id` (FK -> `scans.id`)
- `vuln_id` (CVE, GHSA, distro advisory ID, etc.)
- `package_name`, `package_version`, `package_type`, `package_path`
- `raw_severity`, `effective_severity`
  - Allowed: `Unknown | Negligible | Low | Medium | High | Critical`
- `status`
  - Allowed (OpenVEX): `not_affected | affected | fixed | under_investigation`
  - Dashboard alias (optional): `affected -> open`, `not_affected -> suppressed`
- `vex_justification` (OpenVEX, required when `status=not_affected`)
  - Allowed:
    - `component_not_present`
    - `vulnerable_code_not_present`
    - `vulnerable_code_not_in_execute_path`
    - `vulnerable_code_cannot_be_controlled_by_adversary`
    - `inline_mitigations_already_exist`
- `fix_version`
- `cvss_score`
- `raw_finding` (JSONB: compact, queryable finding metadata only)
- `scanned_at`, `created_at`

### Deduplication Rule

One finding per package+vulnerability identity within a scan:

- Unique index on:
  - `scan_id`
  - `vuln_id`
  - `package_name`
  - `coalesce(package_version, '')`
  - `coalesce(package_type, '')`
  - `coalesce(package_path, '')`

## Storage Policy

- Store full SBOM and full scanner reports in RustFS blobs.
- Store only object keys + checksums + sizes in Postgres.
- Use JSONB in Postgres only for small/queryable metadata, not large raw reports.
