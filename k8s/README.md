# Kubernetes Assets (kind + KEDA MVP)

- `kind-cluster.yaml`: kind cluster config (`1` control-plane + `2` worker nodes)
  - Uses `kindest/node:v1.33.1` tag validated in local autoscaling tests.
  - Mounts local project `volumes/` into kind nodes at `/vulnsentinel-volumes`.
- `namespace.yaml`: `vulnsentinel` namespace
- `infra.yaml`: static infra deployments/services (RabbitMQ, Postgres, RustFS, Grafana)
  - Uses `hostPath` (`/vulnsentinel-volumes/...`) so K8s and Docker Compose share the same runtime data folders.
- `worker-migrate-job.yaml`: one-time Alembic migration job
- `worker.yaml`: worker Deployment
- `worker-autoscale.yaml`: KEDA ScaledObject for worker autoscaling on RabbitMQ queue depth
- `emitter-cronjob.yaml`: suspended-by-default emitter CronJob template
- `loadtest-burst-job.template.yaml`: template used by `scripts/test_scale.ps1`
