# Autoscaling on kind (MVP Demo)

This document describes the local autoscaling profile for VulnSentinel:

- Fixed `kind` cluster size (`1` control-plane + `2` worker nodes)
- Static infra pods (RabbitMQ, Postgres, RustFS, Grafana)
- KEDA autoscaling for worker pods based on RabbitMQ `scan_jobs` queue length

This is a local proof-of-scale flow, not a production HA blueprint.

For a clean-reset demo script that includes localhost port-forwards, pgAdmin, Grafana, and Postgres verification, use `docs/k8s-full-showcase.md`.

## 1. Prerequisites

- Docker Desktop (or Docker Engine)
- `kubectl`
- `kind`
- `helm`

## 2. Create the kind cluster

```powershell
kind create cluster --name vulnsentinel --config .\k8s\kind-cluster.yaml
kubectl cluster-info --context kind-vulnsentinel
```

Notes:

- `kind` does not provide cloud-style node autoscaling by default. Node count is fixed unless you recreate the cluster.
- `k8s/kind-cluster.yaml` is set to a known-good node image tag (`kindest/node:v1.33.1`) for this project.
- `k8s/kind-cluster.yaml` mounts the project `volumes/` folder into kind nodes so Kubernetes infra reuses the same local storage used by Docker Compose.
- If you move the repo to a different path, update `hostPath` in `k8s/kind-cluster.yaml` before creating the cluster.

## 3. Install KEDA

```powershell
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm upgrade --install keda kedacore/keda --namespace keda --create-namespace
kubectl -n keda rollout status deploy/keda-operator
```

## 4. Build and load images into kind

```powershell
docker build -t vuln-worker:local .\worker
docker build -t vuln-emitter:local .\emitter
kind load docker-image vuln-worker:local vuln-emitter:local --name vulnsentinel
```

## 5. Deploy VulnSentinel services

```powershell
kubectl apply -f .\k8s\namespace.yaml
kubectl apply -f .\k8s\infra.yaml
kubectl -n vulnsentinel rollout status deploy/rabbitmq
kubectl -n vulnsentinel rollout status deploy/postgres
kubectl -n vulnsentinel rollout status deploy/rustfs
kubectl -n vulnsentinel rollout status deploy/grafana
```

Storage note:

- Kubernetes `infra.yaml` uses `hostPath` under `/vulnsentinel-volumes/...`, which maps to your local `./volumes/...` from Docker Compose.
- RustFS logs are shared at `./volumes/rustfs/logs` for both Kubernetes and Docker Compose.
- Grafana data is shared at `./volumes/grafana/data` for both Kubernetes and Docker Compose.

Run DB migrations once:

```powershell
kubectl apply -f .\k8s\worker-migrate-job.yaml
kubectl -n vulnsentinel wait --for=condition=complete job/db-migrate --timeout=180s
```

Deploy worker and autoscaler:

```powershell
kubectl apply -f .\k8s\worker.yaml
kubectl apply -f .\k8s\worker-autoscale.yaml
kubectl -n vulnsentinel rollout status deploy/worker
```

Deploy the CronJob template (suspended by default):

```powershell
kubectl apply -f .\k8s\emitter-cronjob.yaml
```

## 6. Run the 50-message burst autoscaling test

Terminal A (watch scaling live):

```powershell
kubectl -n vulnsentinel get pods -w
```

Terminal B (emit burst):

```powershell
.\scripts\test_scale.ps1 -Count 50
```

Expected behavior:

- Worker starts at `1` pod.
- KEDA scales worker pods up (up to `6` in this config) as queue depth grows.
- After queue drains, pods scale back to `1`.

## 7. Enable nightly CronJob emission (optional)

Set a real digest-pinned image ref:

```powershell
docker pull nginx:latest
$imgRef = docker image inspect nginx:latest --format '{{index .RepoDigests 0}}'
kubectl -n vulnsentinel set env cronjob/emitter-nightly EMITTER_IMAGE_REF=$imgRef
```

Unsuspend CronJob:

```powershell
kubectl -n vulnsentinel patch cronjob emitter-nightly -p '{"spec":{"suspend":false}}'
```

Manual run without waiting for schedule:

```powershell
kubectl -n vulnsentinel create job --from=cronjob/emitter-nightly emitter-manual-001
```

## 8. Useful checks

Current worker replica count:

```powershell
kubectl -n vulnsentinel get deploy worker -o custom-columns=NAME:.metadata.name,REPLICAS:.spec.replicas,AVAILABLE:.status.availableReplicas
```

ScaledObject health:

```powershell
kubectl -n vulnsentinel get scaledobject worker-rabbitmq-scaler -o yaml
```

RabbitMQ UI access:

```powershell
kubectl -n vulnsentinel port-forward svc/rabbitmq 15672:15672
```

Grafana UI access:

```powershell
kubectl -n vulnsentinel port-forward svc/grafana 3000:3000
```

Then open `http://localhost:3000` (`admin` / `admin` by default).

If `Dashboards` is empty, import the project dashboard manually:

1. Add datasource:
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
2. Import dashboard:
   - `Dashboards` -> `New` -> `Import`
   - Upload `grafana/dashboards/vulnsentinel-overview.json`
   - Select the datasource created above
   - Click `Import`

## 9. One-command validation script (PASS/FAIL)

Run full automated validation:

```powershell
.\scripts\validate_autoscaling.ps1
```

Useful options:

```powershell
# Use a different burst size
.\scripts\validate_autoscaling.ps1 -BurstCount 80

# Increase scale-up wait window
.\scripts\validate_autoscaling.ps1 -ScaleUpTimeoutSeconds 420

# Skip burst emission and only validate current state
.\scripts\validate_autoscaling.ps1 -SkipBurst
```

## 10. Cleanup

```powershell
kind delete cluster --name vulnsentinel
```

## 11. Troubleshooting

`Error: kubernetes cluster unreachable ... localhost:8080`

- Cause: no active cluster context.
- Fix:

```powershell
kubectl config use-context kind-vulnsentinel
kubectl get nodes
```

`kubelet not healthy after 4m / wait-control-plane timeout`

- Cause: Docker Desktop Linux engine or resource pressure.
- Fix:

```powershell
docker info --format '{{.OSType}} {{.ServerVersion}}'
kind delete cluster --name vulnsentinel
kind create cluster --name vulnsentinel --config .\k8s\kind-cluster.yaml
```

- If needed, increase Docker Desktop resources (CPU/RAM) and retry.
