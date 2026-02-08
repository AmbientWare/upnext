#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

.venv/bin/python -m pytest \
  packages/conduit/tests \
  --cov=conduit \
  --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-fail-under=55
