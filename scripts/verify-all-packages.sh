#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

.venv/bin/python -m pytest \
  packages/conduit/tests \
  packages/server/tests \
  --cov=conduit \
  --cov=server \
  --cov=shared \
  --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-fail-under=60

(
  cd packages/server/web
  npm test
)
