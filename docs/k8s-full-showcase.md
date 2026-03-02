# Kubernetes Full Showcase (50 Images + Autoscaling + Grafana + Postgres + pgAdmin)

Use this when you want a clean, repeatable demo from zero state.

## 1. Prerequisites

- Docker Desktop running
- `kubectl`, `kind`, `helm` installed
- PowerShell opened in repo root:
  `Set the location where the project is currently located`

## 2. Clean Reset

```powershell
kind delete cluster --name vulnsentinel 2>$null
if (Test-Path .\volumes) { Get-ChildItem .\volumes -Force | Remove-Item -Recurse -Force }
docker rm -f pgadmin 2>$null
```

## 3. Create kind Cluster

```powershell
kind create cluster --name vulnsentinel --config .\k8s\kind-cluster.yaml
kubectl config use-context kind-vulnsentinel
kubectl get nodes
```

Expected: `1` control-plane + `2` workers in `Ready` state.

## 4. Install KEDA

```powershell
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm upgrade --install keda kedacore/keda --namespace keda --create-namespace
kubectl -n keda rollout status deploy/keda-operator
```

## 5. Build and Load App Images

```powershell
docker build -t vuln-worker:local .\worker
docker build -t vuln-emitter:local .\emitter
kind load docker-image vuln-worker:local vuln-emitter:local --name vulnsentinel
```

## 6. Deploy Infra (RabbitMQ, Postgres, RustFS, Grafana)

```powershell
kubectl apply -f .\k8s\namespace.yaml
kubectl apply -f .\k8s\infra.yaml
kubectl -n vulnsentinel rollout status deploy/rabbitmq
kubectl -n vulnsentinel rollout status deploy/postgres
kubectl -n vulnsentinel rollout status deploy/rustfs
kubectl -n vulnsentinel rollout status deploy/grafana
kubectl -n vulnsentinel get pods
```

## 7. Run DB Migration Job

```powershell
kubectl delete job db-migrate -n vulnsentinel --ignore-not-found
kubectl apply -f .\k8s\worker-migrate-job.yaml
kubectl -n vulnsentinel wait --for=condition=complete job/db-migrate --timeout=180s
kubectl -n vulnsentinel logs job/db-migrate --tail=120
```

Expected: Alembic migration completes without errors.

## 8. Deploy Worker + Autoscaler

```powershell
kubectl apply -f .\k8s\worker.yaml
kubectl apply -f .\k8s\worker-autoscale.yaml
kubectl -n vulnsentinel rollout status deploy/worker
kubectl -n vulnsentinel get scaledobject worker-rabbitmq-scaler
```

## 9. Start Localhost Access (Separate Terminals)

Run each in its own PowerShell window:

```powershell
kubectl -n vulnsentinel port-forward svc/rabbitmq 5672:5672 15672:15672
```

```powershell
kubectl -n vulnsentinel port-forward svc/rustfs 9000:9000 9001:9001
```

```powershell
kubectl -n vulnsentinel port-forward svc/grafana 3000:3000
```

```powershell
kubectl -n vulnsentinel port-forward svc/postgres 5433:5432
```

Now these are available on localhost:

- RabbitMQ AMQP: `localhost:5672`
- RabbitMQ UI: `http://localhost:15672` (`guest` / `guest`)
- RustFS API: `http://localhost:9000`
- RustFS Console: `http://localhost:9001` (`rustfsadmin` / `rustfsadmin`)
- Grafana: `http://localhost:3000` (`admin` / `admin`)
- Postgres: `localhost:5433` (`postgres` / `postgres`, DB: `vulnsentinel`)

## 10. Start pgAdmin Locally

```powershell
docker compose -f .\docker-compose.pgadmin.yml up -d
docker ps --filter "name=pgadmin"
```

Open `http://localhost:5050`.

pgAdmin login:

- Email: `admin@vulnsentinel.com`
- Password: `admin`

Create server in pgAdmin:

- Name: `vulnsentinel-k8s`
- Host: `host.docker.internal`
- Port: `5433`
- Maintenance DB: `vulnsentinel`
- Username: `postgres`
- Password: `postgres`

## 11. Run 50-Image Burst Test

Terminal A (watch pods scale):

```powershell
kubectl -n vulnsentinel get pods -w
```

Terminal B (emit 50 messages):

```powershell
.\scripts\test_scale.ps1 -Count 50
```

Expected:

- Worker starts at 1 pod
- Scales up while queue depth grows
- Scales back down after queue drains

## 12. Verify Data in Postgres

Option A: pgAdmin query tool:

```sql
select count(*) as scans_total from scans;
select count(*) as findings_total from scan_results;
select status, count(*) from scans group by status order by status;
```

Option B: direct from kubectl:

```powershell
kubectl -n vulnsentinel exec deploy/postgres -- psql -U postgres -d vulnsentinel -c "select count(*) as scans_total from scans;"
kubectl -n vulnsentinel exec deploy/postgres -- psql -U postgres -d vulnsentinel -c "select count(*) as findings_total from scan_results;"
kubectl -n vulnsentinel exec deploy/postgres -- psql -U postgres -d vulnsentinel -c "select status, count(*) from scans group by status order by status;"
```

## 13. Verify Grafana Dashboard

- Open `http://localhost:3000`
- Login with `admin` / `admin`
- Open VulnSentinel dashboard
- Show panel changes as scans/finding counts update after burst

If you do not see any dashboard (empty Dashboards page), import it manually:

1. Add PostgreSQL datasource in Grafana:
   - `Connections` -> `Data sources` -> `Add data source` -> `PostgreSQL`
   - Host: `postgres:5432`
   - Database: `vulnsentinel`
   - User: `postgres`
   - Password: `postgres`
   - SSL mode: `disable`
   - Some Grafana versions expose a datasource UID field; if shown, set it to `vulnsentinel-postgres`.
   - If UID field is not shown, run this once from PowerShell to create a datasource with the expected UID:

```powershell
$pair='admin:admin'
$encoded=[Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers=@{Authorization="Basic $encoded"; 'Content-Type'='application/json'}
$body=@{
  name='VulnSentinel Postgres'
  uid='vulnsentinel-postgres'
  type='grafana-postgresql-datasource'
  access='proxy'
  url='postgres:5432'
  user='postgres'
  database='vulnsentinel'
  isDefault=$true
  jsonData=@{
    database='vulnsentinel'
    sslmode='disable'
    postgresVersion=1500
  }
  secureJsonData=@{password='postgres'}
} | ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri 'http://localhost:3000/api/datasources' -Headers $headers -Method Post -Body $body
```

- Click `Save & test`

2. Import dashboard JSON:
   - `Dashboards` -> `New` -> `Import`
   - Upload `grafana/dashboards/vulnsentinel-overview.json`
   - Choose the PostgreSQL datasource you just created
   - Click `Import`

After import, open the `VulnSentinel` folder and load `VulnSentinel Risk Overview`.

## 14. One-Command Validation (Optional)

Terminal A (watch autoscaling live):

```powershell
kubectl -n vulnsentinel get pods -w
```

Terminal B (run full validation):

```powershell
.\scripts\validate_autoscaling.ps1 -BurstCount 50
```

Expected final output: `Autoscaling validation PASSED.`

## 15. Demo Cleanup

```powershell
docker rm -f pgadmin 2>$null
kind delete cluster --name vulnsentinel
```
