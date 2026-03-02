# Architecture Reference

## Services List

1. **Simulated Context Emitter (`emitter`)**
   - Dockerized Python producer that publishes scan jobs to RabbitMQ.
   - Payload includes immutable image digest + runtime context flags.
2. **Message Broker (RabbitMQ on host OS)**
   - Durable `scan_jobs` queue for async scan triggers.
   - Alternative Docker path is available via `docker-compose.rabbitmq.yml`.
3. **Scan Worker (`worker`)**
   - Dockerized Python consumer that processes scan jobs.
   - Implemented as clear flat modules in `worker/` (`orchestrator.py`, `infra.py`, `syft_logic.py`, `grype_logic.py`, `vex_logic.py`, `db.py`).
   - SBOM cache lookup/generation via Syft.
   - Vulnerability analysis via Grype.
   - Context-aware VEX adjustment before persistence.
4. **Storage Layer**
   - RustFS in Docker for SBOM/report blobs.
   - PostgreSQL on host OS for queryable metadata and findings.
   - Alternative Docker path for PostgreSQL is available via `docker-compose.postgres.yml`.
5. **Visualization Layer (Grafana in Docker)**
   - Provisioned PostgreSQL datasource and starter dashboard JSON.
6. **Vulnerability Feed**
   - Vunnel local sync strategy (external to worker runtime).
7. **Autoscaler (Optional K8s Profile)**
   - KEDA ScaledObject can autoscale worker pods based on RabbitMQ `scan_jobs` queue depth.

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
   - Persistence operations use SQLAlchemy 2.0; schema evolution is managed by Alembic migrations.
6. **Visualization**
   - Grafana queries PostgreSQL for risk funnel, status breakdown, actionable findings, and VEX audit views.

## Deployment Model (Current MVP)

- **Baseline Orchestration:** Plain Docker containers.
- **Autoscaling Demo Profile:** `kind` cluster + KEDA for worker pod autoscaling.
- **Networking:** Dockerized apps connect to host services via `host.docker.internal`.
- **Infra Startup Options:** RabbitMQ/PostgreSQL can be started natively or via standalone Docker Compose files.
- **Worker Concurrency:** RabbitMQ prefetch controls parallelism per consumer.
- **K8s Scope:** Static single-replica infra services with autoscaled worker deployment for local proof-of-scale.
- **K8s Scope:** Static single-replica infra services (RabbitMQ/Postgres/RustFS/Grafana) with autoscaled worker deployment for local proof-of-scale.
- **Deduplication:** PostgreSQL uniqueness constraints in `scan_results` for per-scan finding identity.
- **Schema Management:** Alembic migrations under `worker/alembic` (with `init.sql` retained as bootstrap fallback).
- **Alembic File Guide:** `docs/alembic.md` explains what each Alembic file does.
- **Runtime Data Policy:** `volumes/` contains local runtime state for Grafana and RustFS and is excluded from Git; only source configs and dashboard definitions are version-controlled.
- **Autoscaling Guide:** `docs/autoscaling-kind.md` provides full setup, KEDA config, and burst test flow.

## Deferred Hardening (Implemented)

End-of-project hardening tracked in `docs/deferred-hardening.md` is now implemented:

- Worker ACK/NACK safety with reconnect loop on broker disconnect.
- Artifact integrity check/repair pass between Postgres object keys and RustFS objects.
- Strict emitter digest behavior (explicit digest or Docker-resolved digest only).

