# Contributing

Thanks for contributing to UpNext.

The core quality bar for this project is runtime correctness and test quality, not raw test count.

## Local Setup

```bash
uv sync --all-packages --all-groups
```

## Test and Coverage Requirements

All contributions that change runtime behavior must include tests.

- Add or update tests under `packages/upnext/tests` and/or `packages/server/tests`.
- Prefer behavior-level assertions over internals-only assertions.
- Avoid fixed timing sleeps for async behavior; use polling with explicit deadlines.
- Validate user-facing contracts: CLI behavior, task execution, retries, routing, serialization, and error handling.

Before opening a PR, run:

```bash
uv sync --all-packages --all-groups
./scripts/verify-upnext-package.sh
./scripts/verify-all-packages.sh
```

Before cutting a release or publishing packages, also run:

```bash
./scripts/verify-integration.sh
```

Current verification gates include:

- `pytest` pass for `packages/upnext/tests`
- branch coverage enabled
- minimum package coverage (`upnext`) of **55%**
- minimum workspace Python coverage (`upnext` + `server` + `shared`) of **60%**
- frontend unit coverage thresholds in `packages/server/web/vite.config.ts`:
  statements **70%**, branches **50%**, functions **70%**, lines **70%**
- integration checks for Redis+Postgres stream reliability and wheel/sdist smoke install

## Test Quality Standards

High-quality tests in this repo should be:

- Deterministic and isolated (no hidden dependence on external services for unit tests)
- Specific about behavior contracts (inputs, outputs, state transitions, and failure paths)
- Resistant to timing flakes and interpreter-specific exception message differences
- Minimal in private-attribute coupling (only when no public surface can prove behavior)

Use `fakeredis` or focused test doubles for queue/state assertions in unit tests.

## Linting and Type Safety (Tests)

Run strict checks across test files:

```bash
rg --files -g 'packages/**/tests/**/*.py' | xargs uv run --with ruff ruff check
rg --files -g 'packages/**/tests/**/*.py' | xargs uv run --with basedpyright basedpyright
```

## Packaging and Release Notes

Workspace package names are development-oriented and may not be globally publishable.
For public release, package names must be globally unique on PyPI.

When preparing a release:

- verify package names and metadata are publish-safe
- ensure dependency wiring works outside workspace-only sources
- ensure `upnext` default install and `upnext-server` package wiring work outside workspace-only sources
- run integration verification before publishing artifacts
- include release notes describing behavior, compatibility, and migration impact

## Pull Request Checklist

- Tests added/updated for behavior changes
- No flaky/brittle assertions introduced
- Verification scripts pass locally
- Docs updated when CLI/runtime behavior changes
- No unrelated code churn in the PR
