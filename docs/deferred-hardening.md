# Deferred Hardening Backlog (Implement At End Of Project)

This file stores reliability and correctness findings that are intentionally deferred until the final project phase.

## 1. Worker ACK/NACK Safety + Reconnect Loop

- **What to implement later**
  - Guard ACK/NACK calls so channel/connection shutdown does not crash the worker process.
  - Add broker reconnect loop for transient RabbitMQ disconnects.
- **Why it matters**
  - Prevents worker crashes during temporary network or broker interruptions.
  - Avoids manual restarts for non-functional transient failures.

## 2. Artifact Integrity Check (Postgres Keys vs RustFS Objects)

- **What to implement later**
  - Periodic or on-demand validation that `scans.sbom_object_key` and `scans.report_object_key` exist in RustFS.
  - Define repair policy:
    - Rebuild missing SBOM/report where possible.
    - Or mark scan as invalid/repair-required with clear status.
- **Why it matters**
  - Prevents silent drift between DB metadata and blob storage.
  - Keeps audit/history queries trustworthy.

## 3. Emitter Digest Strictness

- **What to implement later**
  - Require explicit immutable digest in emitted jobs, or resolve real digest through Docker inspect before publish.
  - Disallow synthetic digest fallback derived from image-ref string hashing.
- **Why it matters**
  - Preserves immutable scan identity and reproducible cache keys.
  - Prevents scan/caching drift from non-real digest values.

## Implementation Timing

- **Do not implement now.**
- Implement these items only in the final hardening phase, after feature completion.
