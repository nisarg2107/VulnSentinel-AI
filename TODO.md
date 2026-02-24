# Project TODOs

## Completed (MVP Core Happy Flow)

- [x] Verify local PostgreSQL + RabbitMQ + RustFS are running.
- [x] Pivot architecture from Kubernetes MVP to plain Docker containers.
- [x] Create and apply `init.sql` schema (`assets`, `scans`, `scan_results`).
- [x] Implement `emitter/emitter.py` and `emitter/Dockerfile`.
- [x] Implement `worker/worker.py` and `worker/Dockerfile`.
- [x] Implement SBOM caching in RustFS (cache miss -> Syft, cache hit -> reuse).
- [x] Implement Grype scan wrapper and parse findings.
- [x] Implement context-aware VEX rule (critical + not exposed => downgraded and suppressed).
- [x] Persist per-scan metadata and deduplicated findings in PostgreSQL.
- [x] Validate happy flow (Emitter -> Queue -> Worker -> DB -> RustFS).

## Remaining Work

- [ ] **Frontend (Later)**
- [ ] Setup Next.js + Shadcn.
- [ ] Build risk views aligned with Grafana and OpenVEX statuses.

## Deferred Until End Of Project

- [ ] Implement deferred hardening backlog in [docs/deferred-hardening.md](docs/deferred-hardening.md):
- [ ] Worker ACK/NACK safety and reconnect loop for broker disconnects.
- [ ] Artifact integrity checker and repair policy (DB object keys vs RustFS objects).
- [ ] Emitter digest strictness (require explicit digest or resolve from Docker inspect).
