#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for integration verification" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required for integration verification" >&2
  exit 1
fi

REDIS_CONTAINER=""
POSTGRES_CONTAINER=""

cleanup() {
  if [[ -n "$REDIS_CONTAINER" ]]; then
    docker rm -f "$REDIS_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ -n "$POSTGRES_CONTAINER" ]]; then
    docker rm -f "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

REDIS_CONTAINER="$(docker run -d --rm -P redis:7-alpine redis-server --appendonly yes)"
POSTGRES_CONTAINER="$(
  docker run -d --rm -P \
    -e POSTGRES_DB=upnext \
    -e POSTGRES_USER=upnext \
    -e POSTGRES_PASSWORD=upnext \
    postgres:17-alpine
)"

for _ in {1..60}; do
  if docker exec "$REDIS_CONTAINER" redis-cli ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

for _ in {1..60}; do
  if docker exec "$POSTGRES_CONTAINER" pg_isready -U upnext -d upnext >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

REDIS_PORT="$(docker port "$REDIS_CONTAINER" 6379/tcp | awk -F: '{print $NF}')"
POSTGRES_PORT="$(docker port "$POSTGRES_CONTAINER" 5432/tcp | awk -F: '{print $NF}')"

export UPNEXT_TEST_REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
export UPNEXT_TEST_DATABASE_URL="postgresql+asyncpg://upnext:upnext@127.0.0.1:${POSTGRES_PORT}/upnext"
export UPNEXT_RUN_PACKAGE_SMOKE="1"

.venv/bin/python -m pytest \
  packages/server/tests/test_stream_pipeline_real_integration.py \
  packages/upnext/tests/test_package_publish_smoke.py \
  -m integration

