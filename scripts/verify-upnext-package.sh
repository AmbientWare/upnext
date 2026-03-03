#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uv run python -m pytest \
  packages/upnext/tests \
  --cov=upnext \
  --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-fail-under=70
