# API Tracking Implementation Notes

## Overview
Track API request metrics using Redis streams with periodic aggregation to Postgres.

## Architecture

### 1. FastAPI Middleware
Write to Redis stream on every request (microseconds latency):

```python
from fastapi import Request
from redis import Redis
import time

async def api_tracking_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = (time.perf_counter() - start) * 1000

    redis.xadd("conduit:api:requests", {
        "endpoint": request.url.path,
        "method": request.method,
        "status": response.status_code,
        "latency_ms": int(latency_ms),
        "ts": int(time.time() * 1000)
    })

    return response
```

### 2. Redis Stream Schema
Stream key: `conduit:api:requests`

Fields per entry:
- `endpoint` - request path (e.g., `/api/users`)
- `method` - HTTP method (GET, POST, etc.)
- `status` - response status code
- `latency_ms` - response time in milliseconds
- `ts` - timestamp in milliseconds

### 3. Aggregation Cron Job
Run every 1-5 minutes via Conduit cron:

```python
@cron("*/5 * * * *")
async def aggregate_api_metrics():
    # Read from stream with consumer group
    entries = redis.xreadgroup(
        groupname="api-metrics-aggregator",
        consumername="worker-1",
        streams={"conduit:api:requests": ">"},
        count=1000
    )

    # Aggregate in memory
    aggregates = {}  # keyed by (endpoint, method, hour)
    for entry_id, data in entries:
        key = (data["endpoint"], data["method"], truncate_to_hour(data["ts"]))
        if key not in aggregates:
            aggregates[key] = {
                "count": 0,
                "status_2xx": 0,
                "status_4xx": 0,
                "status_5xx": 0,
                "latencies": []
            }
        agg = aggregates[key]
        agg["count"] += 1
        agg["latencies"].append(int(data["latency_ms"]))

        status = int(data["status"])
        if 200 <= status < 300:
            agg["status_2xx"] += 1
        elif 400 <= status < 500:
            agg["status_4xx"] += 1
        elif status >= 500:
            agg["status_5xx"] += 1

    # Upsert to Postgres
    for (endpoint, method, hour), agg in aggregates.items():
        latencies = sorted(agg["latencies"])
        await db.execute("""
            INSERT INTO api_metrics_hourly
            (endpoint, method, hour, request_count, status_2xx, status_4xx, status_5xx, avg_latency_ms, p95_latency_ms)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (endpoint, method, hour) DO UPDATE SET
                request_count = api_metrics_hourly.request_count + EXCLUDED.request_count,
                status_2xx = api_metrics_hourly.status_2xx + EXCLUDED.status_2xx,
                status_4xx = api_metrics_hourly.status_4xx + EXCLUDED.status_4xx,
                status_5xx = api_metrics_hourly.status_5xx + EXCLUDED.status_5xx,
                avg_latency_ms = (api_metrics_hourly.avg_latency_ms + EXCLUDED.avg_latency_ms) / 2,
                p95_latency_ms = GREATEST(api_metrics_hourly.p95_latency_ms, EXCLUDED.p95_latency_ms)
        """, endpoint, method, hour,
            agg["count"], agg["status_2xx"], agg["status_4xx"], agg["status_5xx"],
            sum(latencies) / len(latencies),
            latencies[int(len(latencies) * 0.95)] if latencies else 0
        )

    # Acknowledge processed entries
    for entry_id, _ in entries:
        redis.xack("conduit:api:requests", "api-metrics-aggregator", entry_id)
```

### 4. Database Schema

```sql
CREATE TABLE api_metrics_hourly (
    id SERIAL PRIMARY KEY,
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    hour TIMESTAMPTZ NOT NULL,
    request_count INT DEFAULT 0,
    status_2xx INT DEFAULT 0,
    status_4xx INT DEFAULT 0,
    status_5xx INT DEFAULT 0,
    avg_latency_ms FLOAT DEFAULT 0,
    p95_latency_ms FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(endpoint, method, hour)
);

CREATE INDEX idx_api_metrics_hour ON api_metrics_hourly(hour);
CREATE INDEX idx_api_metrics_endpoint ON api_metrics_hourly(endpoint);
```

### 5. Dashboard API Endpoints

```python
@router.get("/api/metrics/trends")
async def get_api_trends(
    range: str = "24h",  # 24h, 7d, 30d
    interval: str = "hour",  # hour, day
    endpoint: str = None  # optional filter
):
    # Query aggregated data from Postgres
    pass

@router.get("/api/metrics/endpoints")
async def get_endpoint_stats():
    # Return top endpoints with metrics
    pass
```

## Dashboard Components

### API Trends Panel
- Similar to Job Trends but with status code colors:
  - 2xx: emerald/green
  - 4xx: amber/yellow
  - 5xx: red
- Time range selector (24h, 7d, 30d)
- Interval selector (hourly, daily)

### Active Endpoints Table
- Endpoint path
- Method (GET, POST, etc.)
- Requests/min
- Avg latency
- P95 latency
- Error rate (4xx + 5xx %)

## Consumer Group Setup

On startup, create consumer group if not exists:

```python
try:
    redis.xgroup_create("conduit:api:requests", "api-metrics-aggregator", mkstream=True)
except ResponseError as e:
    if "BUSYGROUP" not in str(e):
        raise
```

## Retention

- Redis stream: trim to last 100k entries or 24 hours
- Postgres hourly data: keep forever or archive after 90 days
