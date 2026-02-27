# Git Hygiene Guide

## Purpose

Keep generated runtime artifacts out of source control while preserving reproducible project configuration.

## Runtime Data Rule

- `volumes/` is ignored by Git (see `.gitignore`).
- This path is used for local Docker bind-mount state (Grafana DB/plugins, RustFS objects/logs, caches).
- These files are environment-specific and should not be committed.

## One-Time Cleanup For Existing Clones

If `volumes/` files were tracked in older history, run:

```powershell
git rm -r --cached volumes
git add .gitignore
git commit -m "chore: ignore runtime volumes and untrack generated artifacts"
```

This removes tracked runtime files from the Git index only. It does not delete your local runtime data from disk.

## Day-To-Day Workflow

Commit source-of-truth files only:

- `grafana/dashboards/*.json`
- `grafana/provisioning/**/*.yml`
- `docker-compose*.yml`
- `worker/`, `emitter/`, and `docs/`

Do not commit:

- `volumes/**`
- Local cache files, virtual environments, and editor-specific files covered by `.gitignore`
