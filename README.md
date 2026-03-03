# VulnSentinel AI

VulnSentinel AI is a local-first vulnerability scanning pipeline for container images. It separates SBOM inventory from vulnerability analysis, then applies runtime context and VEX-style logic to prioritize actionable risk.

## What It Does

- Publishes scan jobs to RabbitMQ from a lightweight emitter.
- Consumes jobs in a worker that:
  - resolves or reuses SBOMs (Syft),
  - scans for vulnerabilities (Grype),
  - applies context-aware VEX logic,
  - stores metadata/findings in PostgreSQL,
  - stores large artifacts (SBOM/report JSON) in RustFS.
- Exposes operational and risk views through Grafana.
- Supports optional local Kubernetes autoscaling (kind + KEDA).

## Architecture (MVP)

1. `emitter` publishes a `scan_jobs` message.
2. `worker` consumes the message and checks SBOM cache.
3. Worker runs Syft + Grype and applies VEX adjustment rules.
4. Worker writes:
   - relational/queryable data -> PostgreSQL
   - SBOM and scanner report blobs -> RustFS
5. Grafana queries PostgreSQL for dashboards.

For full architecture details, see [docs/architecture.md](docs/architecture.md).

## Repository Layout

```text
emitter/   # RabbitMQ producer for scan jobs
worker/    # Scan orchestrator + DB/storage integration + Alembic
docs/      # Architecture, runbook, schemas, decisions, ops guides
k8s/       # Optional kind + KEDA manifests for autoscaling demo
grafana/   # Provisioning + dashboard JSON
scripts/   # Local validation/load test scripts
```

## Prerequisites

- Docker Desktop (or Docker Engine with Compose plugin)
- Python 3.11+ (for local Alembic commands)
- PostgreSQL 15+ and RabbitMQ
  - run natively, or
  - use provided compose files:
    - `docker-compose.postgres.yml`
    - `docker-compose.rabbitmq.yml`
- RustFS (compose file: `docker-compose.rustfs.yml`)
- Optional: Grafana (`docker-compose.grafana.yml`)

## Quick Start (Local Docker Flow)

1. Start infrastructure:

```powershell
docker compose -f .\docker-compose.postgres.yml up -d
docker compose -f .\docker-compose.rabbitmq.yml up -d
docker compose -f .\docker-compose.rustfs.yml up -d
```

2. Apply DB schema (optional if worker runs migrations on startup):

```powershell
cd .\worker
python -m pip install -r .\requirements.txt
alembic upgrade head
cd ..
```

3. Build images:

```powershell
docker build -t vuln-worker .\worker
docker build -t vuln-emitter .\emitter
```

4. Start worker:

```powershell
docker rm -f worker-1 2>$null
docker run -d --name worker-1 --add-host host.docker.internal:host-gateway `
  -e POSTGRES_HOST=host.docker.internal `
  -e POSTGRES_PORT=5432 `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=vulnsentinel `
  -e RABBITMQ_HOST=host.docker.internal `
  -e RABBITMQ_PORT=5672 `
  -e RABBITMQ_USER=guest `
  -e RABBITMQ_PASSWORD=guest `
  -e RABBITMQ_VHOST=/ `
  -e RABBITMQ_QUEUE=scan_jobs `
  vuln-worker
```

5. Emit a scan job:

```powershell
docker pull nginx:latest
$imgRef = docker image inspect nginx:latest --format '{{index .RepoDigests 0}}'
docker run --rm --add-host host.docker.internal:host-gateway vuln-emitter --image-ref $imgRef --is-exposed-public true
```

6. Validate:

```powershell
docker logs --tail 200 worker-1
```

Expected behavior:
- first run: SBOM cache miss
- repeat run (same digest): SBOM cache hit
- completion log with scan id and findings count

## Optional Components

- Grafana UI: `docker compose -f .\docker-compose.grafana.yml up -d`
- Kubernetes autoscaling profile: see [docs/autoscaling-kind.md](docs/autoscaling-kind.md)

## Key Documentation

- Runbook: [docs/runbook.md](docs/runbook.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- Message + DB schema: [docs/message-schemas.md](docs/message-schemas.md)
- Design decisions (ADR): [docs/decisions.md](docs/decisions.md)
- Alembic guide: [docs/alembic.md](docs/alembic.md)
- Grafana guides:
  - [docs/grafana-blueprint.md](docs/grafana-blueprint.md)
  - [docs/grafana-ui-change-guide.md](docs/grafana-ui-change-guide.md)

## Project Status

- Backend MVP flow: implemented
- Deferred hardening: implemented
- kind + KEDA autoscaling demo: implemented
- Frontend risk UI: pending

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
