# Contributing

## Test and Coverage Requirements

All contributions that change runtime behavior must include tests.

- Add or update tests under `packages/conduit/tests`.
- Prefer behavior tests over internals-only tests.
- Avoid fixed timing sleeps when asserting async/queue behavior; prefer polling with deadlines.
- New tests should validate user-facing contracts (CLI output, task execution, retry behavior, routing, serialization).

Before opening a PR, run:

```bash
uv sync --all-packages --all-groups
./scripts/verify-conduit-package.sh
./scripts/verify-all-packages.sh
```

Before cutting a release or publishing packages, also run:

```bash
./scripts/verify-integration.sh
```

This enforces:

- `pytest` pass for `packages/conduit/tests`
- branch coverage enabled
- minimum package coverage (`conduit`) of **55%**
- minimum workspace Python coverage (`conduit` + `server` + `shared`) of **60%**
- frontend unit coverage thresholds in `packages/server/web/vite.config.ts`:
  statements **70%**, branches **50%**, functions **70%**, lines **70%**
- opt-in integration checks for:
  Redis+Postgres stream reliability (reclaim/restart scenarios)
  and build/install smoke from built wheel+sdist artifacts

## Quality Guidelines

- Keep tests deterministic and isolated (no external Redis/Postgres required for unit tests).
- Use `fakeredis` or test doubles for queue/state assertions.
- When tests require private attributes, keep usage minimal and justify it in comments.
- Integration tests are environment-gated:
  `CONDUIT_TEST_REDIS_URL`, `CONDUIT_TEST_DATABASE_URL`, `CONDUIT_RUN_PACKAGE_SMOKE=1`.
