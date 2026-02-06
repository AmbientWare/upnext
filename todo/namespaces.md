# Redis Namespace Support

Add a configurable namespace prefix to all Redis keys so multiple Conduit deployments can share a single Redis instance without collisions.

## Current State

Every Redis key starts with `conduit:`. This is hardcoded across three layers:

**Shared constants** (`shared/workers.py`, `shared/api.py`, `shared/events.py`):
- `conduit:workers:{id}` — worker heartbeats
- `conduit:functions:{worker_id}:{name}` — function definitions
- `conduit:api_instances:{id}` — API instance heartbeats
- `conduit:api:registry` — set of API names
- `conduit:api:{name}:endpoints` — endpoint sets
- `conduit:api:{name}:{method}:{path}:m:{minute}` — minute metrics
- `conduit:api:{name}:{method}:{path}:h:{hour}` — hourly metrics
- `conduit:status:events` — job status event stream
- `conduit:api:requests` — API request stream

**Queue engine** (`conduit/engine/queue/redis/queue.py`, `sweeper.py`, `finisher.py`):
- `conduit:fn:{function}:stream` — job queue stream
- `conduit:fn:{function}:scheduled` — delayed jobs sorted set
- `conduit:fn:{function}:dedup` — deduplication set
- `conduit:job:{function}:{id}` — job data hash
- `conduit:result:{job_id}` — job result
- `conduit:cron_registry` — cron job registry
- `conduit:sweep_lock` — distributed sweep lock
- `conduit:stream:{name}` — user-facing streams

**Job history** (`conduit/engine/database/redis.py`):
- `conduit:job:{id}` — job record
- `conduit:jobs:by_status:{status}` — jobs by status index
- `conduit:jobs:by_time` — jobs by time index
- `conduit:jobs:by_function:{function}` — jobs by function index

## Design

### Configuration

Add `namespace` to SDK Settings, defaulting to `"conduit"`:

```python
# conduit/config.py
class Settings(BaseSettings):
    namespace: str = "conduit"
```

Set via env: `CONDUIT_NAMESPACE=myapp`.

The server gets a matching setting:

```python
# server/config.py
class Settings(BaseSettings):
    namespace: str = "conduit"
```

Set via env: `SERVER_NAMESPACE=myapp` (or whatever its prefix is).

### Shared key builders

Replace static constants with functions in the shared package. A single module (`shared/keys.py`) that all key patterns flow through:

```python
# shared/keys.py

# Defaults (used when no namespace override)
DEFAULT_NAMESPACE = "conduit"

# Worker keys
def worker_key(namespace: str, worker_id: str) -> str:
    return f"{namespace}:workers:{worker_id}"

def worker_scan_pattern(namespace: str) -> str:
    return f"{namespace}:workers:*"

def function_key(namespace: str, worker_id: str, name: str) -> str:
    return f"{namespace}:functions:{worker_id}:{name}"

def function_scan_pattern(namespace: str) -> str:
    return f"{namespace}:functions:*"

# API instance keys
def api_instance_key(namespace: str, api_id: str) -> str:
    return f"{namespace}:api_instances:{api_id}"

def api_instance_scan_pattern(namespace: str) -> str:
    return f"{namespace}:api_instances:*"

# API tracking keys
def api_registry_key(namespace: str) -> str:
    return f"{namespace}:api:registry"

def api_endpoints_key(namespace: str, api_name: str) -> str:
    return f"{namespace}:api:{api_name}:endpoints"

def api_minute_key(namespace: str, api_name: str, method: str, path: str, minute: str) -> str:
    return f"{namespace}:api:{api_name}:{method}:{path}:m:{minute}"

def api_hourly_key(namespace: str, api_name: str, method: str, method: str, path: str, hour: str) -> str:
    return f"{namespace}:api:{api_name}:{method}:{path}:h:{hour}"

# Queue keys
def fn_stream_key(namespace: str, function: str) -> str:
    return f"{namespace}:fn:{function}:stream"

def fn_scheduled_key(namespace: str, function: str) -> str:
    return f"{namespace}:fn:{function}:scheduled"

def fn_dedup_key(namespace: str, function: str) -> str:
    return f"{namespace}:fn:{function}:dedup"

def job_key(namespace: str, function: str, job_id: str) -> str:
    return f"{namespace}:job:{function}:{job_id}"

def result_key(namespace: str, job_id: str) -> str:
    return f"{namespace}:result:{job_id}"

def cron_registry_key(namespace: str) -> str:
    return f"{namespace}:cron_registry"

def sweep_lock_key(namespace: str) -> str:
    return f"{namespace}:sweep_lock"

# Streams
def events_stream(namespace: str) -> str:
    return f"{namespace}:status:events"

def user_stream_key(namespace: str, name: str) -> str:
    return f"{namespace}:stream:{name}"

# Job history
def job_record_key(namespace: str, job_id: str) -> str:
    return f"{namespace}:job:{job_id}"

def jobs_by_status_key(namespace: str, status: str) -> str:
    return f"{namespace}:jobs:by_status:{status}"

def jobs_by_time_key(namespace: str) -> str:
    return f"{namespace}:jobs:by_time"

def jobs_by_function_key(namespace: str, function: str) -> str:
    return f"{namespace}:jobs:by_function:{function}"
```

### SDK side — threading the namespace

`Api` and `Worker` both already read from `settings`. They pass `settings.namespace` into the key builder functions:

```python
# In worker.py
from shared.keys import worker_key, function_key

async def _write_worker_heartbeat(self) -> None:
    key = worker_key(self._namespace, self._worker_id)
    await self._redis_client.setex(key, WORKER_TTL, self._worker_data())
```

The namespace is read once at init from settings:

```python
class Worker:
    def __init__(self, name: str, ...):
        self._namespace = settings.namespace
```

Same pattern for `Api`, middleware, queue engine, database, status publisher, etc.

### Server side

Server services read namespace from their own config and pass to key builders:

```python
# In server/services/workers.py
from shared.keys import worker_scan_pattern, worker_key

async def list_workers(namespace: str) -> list[Worker]:
    async for key in r.scan_iter(match=worker_scan_pattern(namespace)):
        ...
```

Routes pass namespace from server config into service functions.

### What gets deleted

- `shared/workers.py` — constants replaced by `shared/keys.py` functions
- `WORKER_KEY_PREFIX`, `FUNCTION_KEY_PREFIX` constants
- `API_PREFIX`, `API_INSTANCE_PREFIX` constants from `shared/api.py`
- `EVENTS_STREAM`, `API_REQUESTS_STREAM` constants from `shared/events.py`
- All hardcoded `"conduit:"` strings in queue.py, sweeper.py, finisher.py, database/redis.py, middleware.py, status.py

### TTL constants stay

`WORKER_TTL`, `API_INSTANCE_TTL`, `MINUTE_BUCKET_TTL`, `HOURLY_BUCKET_TTL`, `REGISTRY_TTL` are not key patterns — they stay as-is in their current locations.

## Files to modify

**New:**
- `packages/shared/src/shared/keys.py` — all key builder functions

**Shared package:**
- `shared/workers.py` — delete (replaced by keys.py)
- `shared/api.py` — remove prefix constants, keep TTL constants
- `shared/events.py` — remove stream name constants
- `shared/__init__.py` — update exports

**SDK (conduit) package:**
- `conduit/config.py` — add `namespace: str = "conduit"`
- `conduit/sdk/worker.py` — use key builders with `self._namespace`
- `conduit/sdk/api.py` — use key builders with `self._namespace`
- `conduit/sdk/middleware.py` — use key builders with namespace
- `conduit/engine/queue/redis/queue.py` — use key builders with namespace
- `conduit/engine/queue/redis/sweeper.py` — use key builders with namespace
- `conduit/engine/queue/redis/finisher.py` — use key builders with namespace
- `conduit/engine/database/redis.py` — use key builders with namespace
- `conduit/engine/status.py` — use key builders with namespace
- `conduit/engine/stream_subscriber.py` — use key builders with namespace (if exists in SDK)

**Server package:**
- `server/config.py` — add `namespace: str = "conduit"`
- `server/services/workers.py` — use key builders
- `server/services/api_instances.py` — use key builders
- `server/services/api_tracking.py` — use key builders
- `server/services/queue.py` — use key builders
- `server/services/stream_subscriber.py` — use key builders

**No frontend changes** — the frontend talks to the server API, not Redis.
