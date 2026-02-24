# Architecture Reference

## Services List

1. **Simulated Context Emitter (`emitter`)**
   - Dockerized Python producer that publishes scan jobs to RabbitMQ.
   - Payload includes immutable image digest + runtime context flags.
2. **Message Broker (RabbitMQ on host OS)**
   - Durable `scan_jobs` queue for async scan triggers.
3. **Scan Worker (`worker`)**
   - Dockerized Python consumer that processes scan jobs.
   - SBOM cache lookup/generation via Syft.
   - Vulnerability analysis via Grype.
   - Context-aware VEX adjustment before persistence.
4. **Storage Layer**
   - RustFS in Docker for SBOM/report blobs.
   - PostgreSQL on host OS for queryable metadata and findings.
5. **Visualization Layer (Grafana in Docker)**
   - Provisioned PostgreSQL datasource and starter dashboard JSON.
6. **Vulnerability Feed**
   - Vunnel local sync strategy (external to worker runtime).

## Data Flow (The Happy Path)

1. **Trigger**
   - `emitter` publishes a job with `job_id`, `image_ref`, `image_digest`, and `context`.
2. **Inventory Check / SBOM Cache**
   - Worker checks RustFS for `sboms/<digest>.syft.json`.
   - Cache miss: run Syft and upload SBOM blob.
   - Cache hit: reuse existing SBOM blob.
3. **Analysis**
   - Worker runs Grype against the SBOM and parses JSON findings.
4. **Prioritization (VEX Rule in MVP)**
   - If raw severity is `Critical` and `is_exposed_public=false`, effective severity is downgraded and status is suppressed (`not_affected`) with justification.
5. **Persistence**
   - Worker stores scan metadata in `scans`, findings in `scan_results`, and report blob in RustFS.
6. **Visualization**
   - Grafana queries PostgreSQL for risk funnel, status breakdown, actionable findings, and VEX audit views.

## Deployment Model (Current MVP)

- **Orchestration:** Plain Docker containers, no Kubernetes in MVP.
- **Networking:** Dockerized apps connect to host services via `host.docker.internal`.
- **Worker Concurrency:** RabbitMQ prefetch controls parallelism per consumer.
- **Deduplication:** PostgreSQL uniqueness constraints in `scan_results` for per-scan finding identity.

## Deferred Hardening (End Of Project)

The following are intentionally deferred and tracked in `docs/deferred-hardening.md`:

- Worker ACK/NACK safety with reconnect loop on broker disconnect.
- Artifact integrity checker between Postgres object keys and RustFS objects, plus repair policy.
- Strict emitter digest behavior (explicit digest or Docker-resolved digest only).
