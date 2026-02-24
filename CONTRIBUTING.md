# Contributing Rules for AI Agents

1.  **Context First:** Always read `AGENT_CONTEXT.md` and `docs/architecture.md` before generating code. Do not hallucinate new architecture patterns.
2.  **No Docker Compose for Infra:** Do NOT generate `docker-compose.yml` files for Postgres, RustFS, or RabbitMQ. They are managed outside this repo.
3.  **Kubernetes Networking:** Any scripts designed to run inside Docker or Kubernetes MUST connect to the databases/queues using the host gateway IP (`host.docker.internal` or `host.minikube.internal`), NOT `localhost`.
4.  **No Cloud Bindings:** This is a local-only stack. Do not suggest AWS S3, RDS, or SQS. Use RustFS, Postgres, and RabbitMQ.
5.  **Schema Compliance:** Do not change the JSON structure in RabbitMQ or the SQL schema without updating `docs/message-schemas.md` first.
6.  **Minimal Diffs:** When modifying files, change only what is requested.
7.  **Security:** Hardcode credentials only for the local dev environment (e.g., `admin/password`). For production logic, assume env vars.
