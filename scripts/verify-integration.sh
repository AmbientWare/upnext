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
ARTIFACT_DIR="${UPNEXT_INTEGRATION_ARTIFACT_DIR:-.artifacts/integration}"
PYTEST_LOG="$ARTIFACT_DIR/pytest-integration.log"
INFRA_LOG="$ARTIFACT_DIR/infra.log"

mkdir -p "$ARTIFACT_DIR"

inspect_host_port() {
  local container="$1"
  local port_spec="$2"
  docker inspect \
    --format "{{(index (index .NetworkSettings.Ports \"$port_spec\") 0).HostPort}}" \
    "$container"
}

validate_port() {
  local name="$1"
  local port="$2"

  if [[ -z "$port" || ! "$port" =~ ^[0-9]+$ ]]; then
    echo "Invalid $name port mapping: '$port'" >&2
    return 1
  fi

  if (( port < 1 || port > 65535 )); then
    echo "$name port out of range: $port" >&2
    return 1
  fi
}

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

REDIS_PORT="$(inspect_host_port "$REDIS_CONTAINER" "6379/tcp")"
POSTGRES_PORT="$(inspect_host_port "$POSTGRES_CONTAINER" "5432/tcp")"
validate_port "Redis" "$REDIS_PORT"
validate_port "Postgres" "$POSTGRES_PORT"

export UPNEXT_TEST_REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
export UPNEXT_TEST_DATABASE_URL="postgresql+asyncpg://upnext:upnext@127.0.0.1:${POSTGRES_PORT}/upnext"
export UPNEXT_RUN_PACKAGE_SMOKE="1"

{
  echo "redis_container=$REDIS_CONTAINER"
  echo "redis_port=$REDIS_PORT"
  echo "postgres_container=$POSTGRES_CONTAINER"
  echo "postgres_port=$POSTGRES_PORT"
  echo "UPNEXT_TEST_REDIS_URL=$UPNEXT_TEST_REDIS_URL"
  echo "UPNEXT_TEST_DATABASE_URL=$UPNEXT_TEST_DATABASE_URL"
} >"$INFRA_LOG"

set +e
uv run python -m pytest \
  packages/server/tests/test_backend_contract_matrix.py \
  packages/server/tests/test_stream_pipeline_real_integration.py \
  packages/upnext/tests/test_package_publish_smoke.py \
  -m integration \
  2>&1 | tee "$PYTEST_LOG"
PYTEST_EXIT=${PIPESTATUS[0]}
set -e

if [[ "$PYTEST_EXIT" -ne 0 ]]; then
  echo "Integration verification failed. Logs: $PYTEST_LOG" >&2
  exit "$PYTEST_EXIT"
fi
