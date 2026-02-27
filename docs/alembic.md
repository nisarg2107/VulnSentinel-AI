# Alembic Folder Quick Guide

This project uses Alembic to version and apply PostgreSQL schema changes for the worker.

## Why we have `worker/alembic.ini`

- Main Alembic configuration file.
- Tells Alembic where migration scripts live (`script_location = alembic`).
- Includes a default DB URL for local usage, but runtime URL is overridden from environment in `alembic/env.py`.
- Defines migration logging format and levels.

## Why we have `worker/alembic/`

This folder is the migration workspace.

### `worker/alembic/env.py`

- The runtime entrypoint Alembic executes for every migration command.
- Loads project modules (`db.Base`, `infra.Postgres`) so Alembic knows this project's metadata.
- Reads Postgres settings from environment variables and injects the final SQLAlchemy URL into Alembic config.
- Handles both migration modes:
  - offline mode (`--sql`) to generate SQL scripts
  - online mode to connect and apply changes directly

### `worker/alembic/script.py.mako`

- Template used when creating a new migration file with `alembic revision ...`.
- Provides the standard structure (`revision`, `down_revision`, `upgrade()`, `downgrade()`).
- Keeps every migration file consistent.

### `worker/alembic/versions/`

- Stores actual migration versions in execution order.
- Each file is one schema step, tracked by `revision` and `down_revision`.
- Alembic uses this chain to know what to apply and how to roll back.

### `worker/alembic/versions/20260224_0001_initial_schema.py`

- Initial schema migration for VulnSentinel.
- Creates core tables (`assets`, `scans`, `scan_results`), constraints, indexes, and trigger/function used by scanning flow.
- `downgrade()` removes those DB objects in reverse.

## Common commands

Run from `worker/`:

```powershell
alembic upgrade head        # apply all pending migrations
alembic downgrade -1        # rollback one migration
alembic revision -m "msg"   # create a new migration file
```
