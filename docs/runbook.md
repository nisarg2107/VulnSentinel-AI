# Runbook

## Prerequisites

- Native PostgreSQL 15+ (optional if using Docker Compose)
- Native RabbitMQ (Erlang required, optional if using Docker Compose)
- RustFS Docker container
- Docker Desktop (or Docker Engine + Compose plugin)
- Python 3.11+ (for Alembic migration commands)

You can run PostgreSQL and RabbitMQ either natively on your machine or with the Docker Compose files in this repo.

## 0. Git Hygiene (Runtime Volumes)

Runtime bind-mount data under `volumes/` is intentionally ignored by Git (`.gitignore`) because it contains ephemeral container state (`.db`, `.json`, `.js`, `.map`, logs, and object-store metadata).
Detailed policy and examples: `docs/git-hygiene.md`.

If your clone already tracked these files from older commits, run this once:

```powershell
git rm -r --cached volumes
git add .gitignore
git commit -m "chore: ignore runtime volumes and untrack generated artifacts"
```

Notes:

- This removes files from Git tracking only.
- Local runtime data remains on disk under `volumes/`.

## 1. Start Infrastructure

Option A (native services):

1. Start local PostgreSQL on `5432`.
2. Start local RabbitMQ on `5672` and management UI on `15672`.
3. Start RustFS in Docker on `9000` (API) and `9001` (console).

Option B (Docker Compose):

```powershell
docker compose -f .\docker-compose.postgres.yml up -d
docker compose -f .\docker-compose.rabbitmq.yml up -d
docker compose -f .\docker-compose.rustfs.yml up -d
```

Optional (Grafana):

```powershell
docker compose -f .\docker-compose.grafana.yml up -d
```

Default endpoints:

- PostgreSQL: `localhost:5432`
- RabbitMQ AMQP: `localhost:5672`
- RabbitMQ UI: `http://localhost:15672`
- RustFS API: `http://localhost:9000`
- RustFS console: `http://localhost:9001`

## 2. Apply Database Schema

If you use Docker Compose for Postgres, defaults are:

- database: `vulnsentinel`
- user: `postgres`
- password: `postgres`

If you use native Postgres, use your own database name and credentials in the commands below.

Simple Alembic file explanations are documented in `docs/alembic.md`.

Note: the worker container now runs `alembic upgrade head` on startup, so manual migration is optional when running via Docker worker.

Preferred (Alembic):

```powershell
cd .\worker
python -m pip install -r .\requirements.txt
alembic upgrade head
cd ..
```

Fallback (raw SQL):

```powershell
psql -h localhost -p 5432 -U postgres -d <DB_NAME> -f .\init.sql
```

## 3. Build Docker Images

```powershell
docker build -t vuln-worker .\worker
docker build -t vuln-emitter .\emitter
```

## 4. Start Worker

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
  -e RABBITMQ_REQUEUE_ON_ERROR=false `
  -e RABBITMQ_RECONNECT_INITIAL_DELAY_SECONDS=2 `
  -e RABBITMQ_RECONNECT_MAX_DELAY_SECONDS=30 `
  -e ARTIFACT_INTEGRITY_CHECK_ON_START=false `
  vuln-worker
```

## 5. Emit a Test Job

```powershell
docker pull nginx:latest
$imgRef = docker image inspect nginx:latest --format '{{index .RepoDigests 0}}'
docker run --rm --add-host host.docker.internal:host-gateway vuln-emitter --image-ref $imgRef --is-exposed-public true
```

Digest behavior:

- Emitter now requires immutable digest identity.
- If `--image-ref` has no digest and `--image-digest` is not passed, emitter tries `docker image inspect` to resolve one.
- If digest cannot be resolved, the emit command fails.

## 6. Validate Happy Flow

1. Worker logs:

```powershell
docker logs --tail 200 worker-1
```

Expected:

- first run: `SBOM cache miss ...`
- later runs (same digest): `SBOM cache hit ...`
- completion: `Completed scan scan_id=... findings=...`

2. RabbitMQ UI: `http://localhost:15672`

3. RustFS console: `http://localhost:9001`
   - bucket `sboms` should contain `sboms/...syft.json` and `reports/...grype.json`

4. Postgres checks:

```sql
SELECT id, status, sbom_object_key, report_object_key, error, created_at
FROM scans
ORDER BY id DESC
LIMIT 5;

SELECT scan_id, COUNT(*) AS findings
FROM scan_results
GROUP BY scan_id
ORDER BY scan_id DESC
LIMIT 5;
```

Optional artifact integrity pass (on-demand):

```powershell
cd .\worker
python .\orchestrator.py --artifact-integrity-check-only --artifact-integrity-limit 500
cd ..
```

Exit code:

- `0`: all checked scans were healthy or repaired.
- `1`: one or more scans remain `repair_required`.

## 7. Grafana

Use `docs/grafana-blueprint.md` for panel layout and query templates aligned with OpenVEX statuses.
Use `docs/grafana-ui-change-guide.md` for dashboard UI-only customization (copying dashboards, severity color mapping, and rollback).

### Theme Modes (Light / Dark / System)

Grafana now supports all three UI theme modes in this project:

- `system` (default)
- `light`
- `dark`

Compose config:

- `GF_USERS_DEFAULT_THEME=${GRAFANA_DEFAULT_THEME:-system}`

To change default theme before startup:

```powershell
$env:GRAFANA_DEFAULT_THEME = "light"   # or "dark" or "system"
docker compose -f .\docker-compose.grafana.yml up -d
```

To switch theme per user in UI:

1. Login to Grafana.
2. Open your user profile/preferences.
3. Set Theme to `Light`, `Dark`, or `System`.
