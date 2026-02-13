#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uv run --with ruff ruff check \
  packages/upnext/src \
  packages/server/src \
  packages/shared/src \
  packages/upnext/tests \
  packages/server/tests

uv run --with basedpyright basedpyright

.venv/bin/python -m pytest \
  packages/upnext/tests \
  packages/server/tests \
  --cov=upnext \
  --cov=server \
  --cov=shared \
  --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-fail-under=60

(
  cd packages/server/web
  npm run lint
  npm test
)
