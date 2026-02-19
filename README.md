# UpNext

Background jobs and APIs for Python.

UpNext is an alpha-stage framework for running workers, APIs, cron jobs, and event-driven tasks with a shared Redis-backed runtime.

[Documentation](https://docs.upnext.run) | [PyPI](https://pypi.org/project/upnext/) | [GitHub](https://github.com/AmbientWare/upnext)

## Why UpNext

- Task, cron, and event APIs with simple decorators
- Built-in job state transitions, retries, and progress updates
- Artifact support for attaching output to jobs
- Hosted server package for job history and dashboard APIs
- Monorepo with package-level and workspace-level verification scripts

## Repository Layout

- `packages/upnext`: SDK, runtime engine, and `upnext` CLI
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
UPNEXT_REDIS_URL=redis://localhost:6379 \
uv run --package upnext upnext run examples/service.py
```

The example API listens on `http://localhost:8001`.

### 4) Generate traffic

```bash
API_URL=http://localhost:8001 \
uv run --package upnext python examples/client.py
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
uv add upnext
```

Server-only environments can install just:

```bash
uv add upnext-server
```

## Hosted Server

Server commands work from source checkout and installed package environments.

Start server (SQLite + Redis):

```bash
UPNEXT_DATABASE_URL=sqlite+aiosqlite:///upnext.db \
UPNEXT_REDIS_URL=redis://localhost:6379 \
uv run --package upnext upnext server start --port 8080
```

If using PostgreSQL, run migrations first:

```bash
UPNEXT_DATABASE_URL=postgresql+asyncpg://upnext:upnext@localhost:5432/upnext \
uv run --package upnext upnext server db upgrade head
```

## Realtime Update Model

The dashboard and API views use a stream-first model:

- SSE streams are the primary source for live job/API/artifact/trend updates.
- Polling is retained only as a low-frequency safety resync or where no stream exists yet.
- On SSE reconnect, key caches are invalidated to recover cleanly from missed events.

This keeps UI updates near-realtime while reducing avoidable polling load.

## Worker Queue Defaults

Workers now run with fixed, safe queue tuning defaults. Queue profile selection
and custom profile overrides are intentionally not exposed in the public
constructor.

## Benchmarking

The benchmark suite is fully command-driven:

```bash
# Validate Redis + framework imports
uv run benchmarks doctor

# Primary benchmark: sustained API-like workload (recommended)
uv run benchmarks matrix \
  --workload sustained \
  --duration-seconds 60 \
  --arrival-rate 200 \
  --framework upnext-async \
  --framework upnext-sync \
  --framework celery \
  --framework saq

# Secondary benchmark: burst/backpressure guardrail
uv run benchmarks matrix \
  --workload burst \
  --jobs 10000 \
  --framework upnext-async \
  --framework upnext-sync \
  --framework celery \
  --framework saq
```

For GitHub Actions, use the `Benchmarks` workflow with:
- `mode=quick` for routine checks (sustained only, light settings)
- `mode=full` for deeper comparisons (sustained + burst)

Both modes are deterministic/fair by default:
- fixed framework set (`upnext-async`, `upnext-sync`, `celery`, `saq`)
- fixed matrix seed (`42`)
- quick: sustained `duration=30s`, `arrival=150/s`, `repeats=1`, `warmups=1`
- full: sustained `duration=60s`, `arrival=200/s` + burst `jobs=10000`, `repeats=2`, `warmups=1`

## Testing and Verification

Package-level:

```bash
./scripts/verify-upnext-package.sh
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

- `upnext`
- `upnext-server`
- `upnext-shared`

while keeping:

- import package: `upnext`
- CLI command: `upnext`
- product name: upnext

## Contributing

See `CONTRIBUTING.md` for quality bar, tests, and release checks.

Built by [AmbientWare](https://github.com/AmbientWare).
