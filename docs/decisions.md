### 4. `docs/decisions.md`

```markdown
# Architectural Decision Record (ADR)

- **Why drop Kubernetes for MVP?** Setting up K8s RBAC, CronJobs, and Pods adds unnecessary friction for validating the core logic. Using 1-2 standard Dockerfiles allows us to rapidly test the "happy flow" (Queue -> SBOM -> Scan -> DB) while keeping the same enterprise architecture patterns.
- **Why mixed local services?** PostgreSQL and RabbitMQ run natively on the laptop, and RustFS runs in Docker for artifact storage. Docker containers communicate with host services via `host.docker.internal`.
- **Why add standalone Docker Compose files for RabbitMQ/PostgreSQL?** So contributors can start infra quickly without installing those services directly on their OS.
- **Why Syft + Grype?** Decoupling SBOM generation from scanning is required to handle high-throughput enterprise loads (1M+ images).
- **Why Image Digest?** Tags are mutable. `v1.0` changes. Digests are immutable. Security must pin to digests.
- **Why add a `scans` table?** One scan run needs one durable record so we can keep history and query latest-vs-previous scans cleanly.
- **Why keep only compact JSONB in Postgres?** Full SBOM/scan outputs are blobs better stored in RustFS; Postgres stores queryable metadata and blob pointers.
- **Why SQLAlchemy + Alembic?** SQLAlchemy 2.0 provides a cleaner modular persistence layer, and Alembic provides repeatable schema versioning while remaining Postgres-first.
```
