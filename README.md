# Conduit

Background jobs and APIs for Python.

Conduit is an alpha-stage framework for running workers, APIs, cron jobs, and event-driven tasks with a shared Redis-backed runtime.

## Why Conduit

- Task, cron, and event APIs with simple decorators
- Built-in job state transitions, retries, and progress updates
- Artifact support for attaching output to jobs
- Hosted server package for job history and dashboard APIs
- Monorepo with package-level and workspace-level verification scripts

## Repository Layout

- `packages/conduit`: SDK, runtime engine, and `conduit` CLI
- `packages/server`: hosted API server + web dashboard
- `packages/shared`: shared models and schemas
- `examples/service.py`: sample API + worker service
- `examples/client.py`: traffic generator for the example service
- `scripts/verify-*.sh`: verification scripts used for CI/release readiness

## Quickstart (From Source)

### Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- Redis 7+
- Docker (optional, but easiest for local Redis/Postgres)

### 1) Install workspace dependencies

```bash
uv sync --all-packages --all-groups
```

### 2) Start Redis

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

### 3) Run the example service (API + worker)

```bash
CONDUIT_REDIS_URL=redis://localhost:6379 \
uv run --package conduit-py conduit run examples/service.py
```

The example API listens on `http://localhost:8001`.

### 4) Generate traffic

```bash
API_URL=http://localhost:8001 \
uv run --package conduit-py python examples/client.py
```

### 5) Call the API directly

```bash
curl -X POST http://localhost:8001/orders \
  -H 'content-type: application/json' \
  -d '{"user_id":"user_1","items":["Widget A","Widget B"]}'
```

## Install

SDK + CLI + hosted server commands:

```bash
uv add conduit-py
```

Server-only environments can install just:

```bash
uv add conduit-server
```

## Hosted Server

Server commands work from source checkout and installed package environments.

Start server (SQLite + Redis):

```bash
CONDUIT_DATABASE_URL=sqlite+aiosqlite:///conduit.db \
CONDUIT_REDIS_URL=redis://localhost:6379 \
uv run --package conduit-py conduit server start --port 8080
```

If using PostgreSQL, run migrations first:

```bash
CONDUIT_DATABASE_URL=postgresql+asyncpg://conduit:conduit@localhost:5432/conduit \
uv run --package conduit-py conduit server db upgrade head
```

## Testing and Verification

Package-level:

```bash
./scripts/verify-conduit-package.sh
```

Workspace-level (Python + web):

```bash
./scripts/verify-all-packages.sh
```

Integration checks (real Redis/Postgres + publish smoke):

```bash
./scripts/verify-integration.sh
```

## Packaging Direction

This repo publishes using globally unique package names:

- `conduit-py`
- `conduit-server`
- `conduit-shared`

while keeping:

- import package: `conduit`
- CLI command: `conduit`
- product name: Conduit

## Contributing

See `CONTRIBUTING.md` for quality bar, tests, and release checks.

Built by LazyCloud.
