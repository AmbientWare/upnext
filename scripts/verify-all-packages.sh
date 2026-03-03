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

uv run python -m pytest \
  packages/upnext/tests \
  packages/server/tests \
  --cov=upnext \
  --cov=server \
  --cov=shared \
  --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-fail-under=70

(
  cd packages/server/web
  if [[ -f bun.lock ]]; then
    if ! command -v bun >/dev/null 2>&1; then
      echo "bun is required for web lint/tests (bun.lock detected)" >&2
      exit 1
    fi
    if [[ ! -d node_modules ]]; then
      bun install --frozen-lockfile
    fi
    if command -v npm >/dev/null 2>&1; then
      npm run lint
      npm test
    else
      bun x eslint .
      bun x vitest run --coverage
    fi
  elif command -v npm >/dev/null 2>&1; then
    if [[ ! -d node_modules ]]; then
      npm ci
    fi
    npm run lint
    npm test
  elif command -v bun >/dev/null 2>&1; then
    if [[ ! -d node_modules ]]; then
      bun install --frozen-lockfile
    fi
    bun x eslint .
    bun x vitest run --coverage
  else
    echo "npm or bun is required for web lint/tests" >&2
    exit 1
  fi
)
