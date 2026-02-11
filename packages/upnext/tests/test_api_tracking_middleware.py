from __future__ import annotations

import pytest
from shared.api import API_PREFIX
from shared.events import API_REQUESTS_STREAM
from starlette.requests import Request
from upnext.sdk.middleware import ApiTrackingConfig, ApiTrackingMiddleware


class _RouteStub:
    path_format = "/users/{user_id}"


def _request(path: str) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "route": _RouteStub(),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_normalize_path_prefers_route_template(fake_redis) -> None:
    middleware = ApiTrackingMiddleware(
        app=lambda scope, receive, send: None,
        api_name="orders",
        redis_client=fake_redis,
        config=ApiTrackingConfig(normalize_paths=True),
    )

    assert middleware._normalize_path(_request("/users/123")) == "/users/{user_id}"  # noqa: SLF001


@pytest.mark.asyncio
async def test_metrics_always_recorded_and_event_sampling_respects_error_and_slow(
    fake_redis,
) -> None:
    middleware = ApiTrackingMiddleware(
        app=lambda scope, receive, send: None,
        api_name="orders",
        redis_client=fake_redis,
        config=ApiTrackingConfig(
            normalize_paths=True,
            request_events_enabled=True,
            request_events_sample_rate=0.0,
            request_events_slow_ms=100.0,
            request_events_stream_max_len=100,
        ),
        api_instance_id="api_test_1",
    )

    path = "/orders/{order_id}"

    # Fast 2xx event should be sampled out when sample_rate=0.0.
    await middleware._record("GET", path, 200, 12.0)  # noqa: SLF001

    # Error and slow requests should still be emitted regardless of sample rate.
    await middleware._record("GET", path, 500, 25.0)  # noqa: SLF001
    await middleware._record("GET", path, 200, 250.0)  # noqa: SLF001

    minute_pattern = f"{API_PREFIX}:orders:GET:/orders/{{order_id}}:m:*"
    minute_keys = [key async for key in fake_redis.scan_iter(match=minute_pattern)]
    assert len(minute_keys) == 1

    minute_hash = await fake_redis.hgetall(minute_keys[0])
    assert int(minute_hash[b"requests"]) == 3
    assert int(minute_hash[b"errors"]) == 1

    rows = await fake_redis.xrevrange(API_REQUESTS_STREAM, count=10)
    assert len(rows) == 2

    newest_payload = rows[0][1][b"data"].decode()
    older_payload = rows[1][1][b"data"].decode()

    assert '"status": 200' in newest_payload
    assert '"latency_ms": 250.0' in newest_payload
    assert '"status": 500' in older_payload
    assert '"instance_id": "api_test_1"' in older_payload


@pytest.mark.asyncio
async def test_registry_refresh_only_writes_new_endpoint_without_periodic_refresh(
    fake_redis,
) -> None:
    middleware = ApiTrackingMiddleware(
        app=lambda scope, receive, send: None,
        api_name="orders",
        redis_client=fake_redis,
        config=ApiTrackingConfig(
            normalize_paths=True,
            registry_refresh_seconds=9999,
            request_events_enabled=False,
        ),
    )

    await middleware._record("GET", "/orders", 200, 10.0)  # noqa: SLF001
    await middleware._record("GET", "/orders", 200, 11.0)  # noqa: SLF001

    registry_members = await fake_redis.smembers(f"{API_PREFIX}:registry")
    endpoints_members = await fake_redis.smembers(f"{API_PREFIX}:orders:endpoints")

    assert registry_members == {b"orders"}
    assert endpoints_members == {b"GET:/orders"}

    ttl = await fake_redis.ttl(f"{API_PREFIX}:orders:endpoints")
    assert ttl > 0

    # Existing endpoint should not trigger extra endpoint set entries.
    assert len(endpoints_members) == 1

    # New endpoint should still be registered immediately.
    await middleware._record("POST", "/orders", 201, 9.0)  # noqa: SLF001
    endpoints_members = await fake_redis.smembers(f"{API_PREFIX}:orders:endpoints")
    assert endpoints_members == {b"GET:/orders", b"POST:/orders"}
