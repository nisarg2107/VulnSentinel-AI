# Deferred Hardening Backlog

## 1. Worker ACK/NACK Safety + Reconnect Loop

- **Status:** Implemented (February 28, 2026)
- **Implemented behavior**
  - ACK/NACK calls are guarded so channel/connection shutdown does not crash the worker process.
  - Worker now runs in a reconnect loop with backoff for transient RabbitMQ disconnects.

## 2. Artifact Integrity Check (Postgres Keys vs RustFS Objects)

- **Status:** Implemented (February 28, 2026)
- **Implemented behavior**
  - On-demand integrity pass validates that `scans.sbom_object_key` and `scans.report_object_key` exist in RustFS.
  - Repair policy:
    - Rebuild missing SBOM/report where possible.
    - Mark scan `repair_required` with explicit error when repair fails.

## 3. Emitter Digest Strictness

- **Status:** Implemented (February 28, 2026)
- **Implemented behavior**
  - Emitter requires explicit immutable digest or resolves digest via `docker image inspect`.
  - Synthetic digest fallback derived from image-ref hashing is removed.
