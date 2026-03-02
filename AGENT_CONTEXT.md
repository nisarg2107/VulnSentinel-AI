## Project Summary

VulnSentinel AI is a local-only, enterprise-grade vulnerability management pipeline designed to handle high-throughput container image scanning. It decouples **Inventory (SBOM)** from **Analysis (Scanning)** and filters results through a **Runtime Context Engine**. It prioritizes risks by evaluating runtime context (e.g., internet exposure) and applying VEX logic to suppress false positives.

## Current Status

- **Phase:** MVP Core + Deferred Hardening Complete + kind/KEDA Autoscaling Demo Added / Frontend Pending
- **Infrastructure:** Native Host OS Installations (PostgreSQL, RabbitMQ) + RustFS in Docker
- **Alternative Infra Path:** Standalone Docker Compose files for PostgreSQL and RabbitMQ are available in repo root.
- **Compute (Baseline):** Plain Docker containers
- **Compute (Autoscaling Demo):** kind Kubernetes + KEDA worker autoscaling
- **Backend:** Worker + emitter implemented and verified in happy flow
- **Worker Codebase:** Flat, readable layout in `worker/` with `orchestrator.py` as the startup entrypoint and split infra/syft/grype/vex/db modules.
- **Data Model:** `assets`, `scans`, and `scan_results` in Postgres with OpenVEX-aligned statuses
- **Observability:** Grafana provisioning and baseline dashboard JSON committed

## Tech Stack

- **Compute Orchestration:** Plain Docker (1-2 Dockerfiles for testing the flow)
- **Queue:** RabbitMQ (Running natively on Host OS)
- **Queue (Alternative):** RabbitMQ via `docker-compose.rabbitmq.yml`
- **Storage:** RustFS for SBOM JSONs + PostgreSQL 15 for Risk Relationships
- **Storage (Alternative):** PostgreSQL via `docker-compose.postgres.yml`
- **Scanning:** Syft (Generate SBOM) + Grype (Scan SBOM) + Vunnel (DB Sync)
- **Backend:** Python (modular worker) + SQLAlchemy 2.0 + Alembic
- **Frontend:** Next.js 14 (Pending)

## Key Decisions

- **Dropped Kubernetes for MVP:** To validate the "happy flow" quickly, we are using simple Docker containers instead of a full Kubernetes cluster.
- **Simulated Context:** Since we are not running Kubernetes, the "Context Collector" is now a Python script that injects mock infrastructure data (e.g., `exposed: true`) into RabbitMQ to test the VEX decision engine.
- **Local-Only Infrastructure:** PostgreSQL and RabbitMQ run on host OS, while RustFS runs in Docker.
- **Local-Only Infrastructure (Alternative):** PostgreSQL and RabbitMQ can also run in Docker via standalone compose files.
- **Networking Rule:** Dockerized workers must connect to native services using the host machine's IP (e.g., `host.docker.internal`).
- **Deferred Hardening:** End-of-project hardening backlog is implemented and tracked in `docs/deferred-hardening.md`.

## Next Tasks

1. Validate kind/KEDA autoscaling flow repeatedly with varying burst sizes and queue thresholds.
2. Build the frontend (Next.js + shadcn) for actionable risk views.
3. Continue hardening validation runs (disconnect/reconnect, artifact repair, strict digest emit).

