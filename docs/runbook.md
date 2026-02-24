# Runbook

## Prerequisites

- Native PostgreSQL 15+
- Native RabbitMQ (Erlang required)
- RustFS Docker container
- Docker installed

## 1. Start Infrastructure

1. Start local PostgreSQL on `5432`.
2. Start local RabbitMQ on `5672` and management UI on `15672`.
3. Start RustFS in Docker on `9000` (API) and `9001` (console).

## 2. Apply Database Schema

Use the database name you actually created (for example `vulnsentinel` or `vulnsentinal`).

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
  -e POSTGRES_PASSWORD=<POSTGRES_PASSWORD> `
  -e POSTGRES_DB=<DB_NAME> `
  -e RABBITMQ_REQUEUE_ON_ERROR=true `
  vuln-worker
```

## 5. Emit a Test Job

```powershell
docker pull nginx:latest
$imgRef = docker image inspect nginx:latest --format '{{index .RepoDigests 0}}'
docker run --rm --add-host host.docker.internal:host-gateway vuln-emitter --image-ref $imgRef --is-exposed-public true
```

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

## 7. Grafana

Use `docs/grafana-blueprint.md` for panel layout and query templates aligned with OpenVEX statuses.

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
