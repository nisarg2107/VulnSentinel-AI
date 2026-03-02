# Kubernetes Permission Recovery (RustFS + Grafana)

Use this guide when infra rollout gets stuck with permission-related crashes in local kind.

## When to use this

Run this recovery if you see one or more of these errors:

- `kubectl -n vulnsentinel rollout status deploy/rustfs` shows:
  - `Waiting for deployment "rustfs" rollout to finish: 1 old replicas are pending termination...`
  - `error: deployment "rustfs" exceeded its progress deadline`
- RustFS logs include:
  - `Telemetry initialization failed: Set permissions failed: dir='/logs', want=0o755, have=0o777`
  - `Permission denied` or `Operation not permitted`
- Grafana logs include:
  - `GF_PATHS_DATA='/var/lib/grafana' is not writable`
  - `mkdir: can't create directory '/var/lib/grafana/plugins': Permission denied`

## Why this happens

`k8s/infra.yaml` mounts host paths under `/vulnsentinel-volumes/...`.
If those directories are owned by `root` with incompatible mode/ownership, RustFS and Grafana containers cannot write startup files.

Important RustFS detail:

- RustFS expects `/logs` to be mode `0755`.
- If `/logs` is `0777`, RustFS may try to correct it and fail when it does not own the directory.

## Step-by-step recovery (PowerShell)

### 1. Confirm the failing state

```powershell
kubectl -n vulnsentinel get pods -l app=rustfs -o wide
kubectl -n vulnsentinel get pods -l app=grafana -o wide
kubectl -n vulnsentinel logs -l app=rustfs --previous --tail=120
kubectl -n vulnsentinel logs -l app=grafana --previous --tail=120
```

### 2. Fix volume ownership/permissions on both kind workers

```powershell
docker exec vulnsentinel-worker sh -lc "chown -R 10001:10001 /vulnsentinel-volumes/rustfs/data /vulnsentinel-volumes/rustfs/logs && chmod 755 /vulnsentinel-volumes/rustfs/logs && chown -R 472:0 /vulnsentinel-volumes/grafana/data && chmod -R 775 /vulnsentinel-volumes/grafana/data"

docker exec vulnsentinel-worker2 sh -lc "chown -R 10001:10001 /vulnsentinel-volumes/rustfs/data /vulnsentinel-volumes/rustfs/logs && chmod 755 /vulnsentinel-volumes/rustfs/logs && chown -R 472:0 /vulnsentinel-volumes/grafana/data && chmod -R 775 /vulnsentinel-volumes/grafana/data"
```

### 3. Reset stuck pods cleanly

```powershell
kubectl -n vulnsentinel scale deploy/rustfs --replicas=0
kubectl -n vulnsentinel scale deploy/grafana --replicas=0

kubectl -n vulnsentinel delete pod -l app=rustfs --grace-period=0 --force --ignore-not-found
kubectl -n vulnsentinel delete pod -l app=grafana --grace-period=0 --force --ignore-not-found

kubectl -n vulnsentinel scale deploy/rustfs --replicas=1
kubectl -n vulnsentinel scale deploy/grafana --replicas=1
```

### 4. Verify rollout

```powershell
kubectl -n vulnsentinel rollout status deploy/rustfs --timeout=180s
kubectl -n vulnsentinel rollout status deploy/grafana --timeout=180s
kubectl -n vulnsentinel get pods -l app=rustfs -o wide
kubectl -n vulnsentinel get pods -l app=grafana -o wide
```

Expected:

- both deployments report `successfully rolled out`
- pods become `Running` and `READY 1/1`

## After recovery

Continue the normal demo flow in `docs/k8s-full-showcase.md`.

## Optional quick preflight before deploying infra

If you want to avoid repeating this issue after a clean reset, run this before `kubectl apply -f .\\k8s\\infra.yaml`:

```powershell
docker exec vulnsentinel-worker sh -lc "mkdir -p /vulnsentinel-volumes/rustfs/data /vulnsentinel-volumes/rustfs/logs /vulnsentinel-volumes/grafana/data && chown -R 10001:10001 /vulnsentinel-volumes/rustfs/data /vulnsentinel-volumes/rustfs/logs && chmod 755 /vulnsentinel-volumes/rustfs/logs && chown -R 472:0 /vulnsentinel-volumes/grafana/data && chmod -R 775 /vulnsentinel-volumes/grafana/data"

docker exec vulnsentinel-worker2 sh -lc "mkdir -p /vulnsentinel-volumes/rustfs/data /vulnsentinel-volumes/rustfs/logs /vulnsentinel-volumes/grafana/data && chown -R 10001:10001 /vulnsentinel-volumes/rustfs/data /vulnsentinel-volumes/rustfs/logs && chmod 755 /vulnsentinel-volumes/rustfs/logs && chown -R 472:0 /vulnsentinel-volumes/grafana/data && chmod -R 775 /vulnsentinel-volumes/grafana/data"
```
