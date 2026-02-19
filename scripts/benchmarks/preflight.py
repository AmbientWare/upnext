from __future__ import annotations

from importlib import import_module
from typing import Any

_FRAMEWORK_IMPORT_TARGETS = {
    "upnext-async": "upnext.sdk.worker",
    "upnext-sync": "upnext.sdk.worker",
    "celery": "celery",
    "saq": "saq",
}


def check_redis(redis_url: str) -> tuple[bool, str]:
    try:
        from redis import Redis
    except Exception as exc:
        return False, f"redis dependency missing: {exc}"

    client = Redis.from_url(redis_url, decode_responses=False)
    try:
        client.ping()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
    finally:
        client.close()


def check_framework_imports(frameworks: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for framework in frameworks:
        module_name = _FRAMEWORK_IMPORT_TARGETS.get(framework)
        if not module_name:
            out[framework] = {"ok": False, "detail": "unsupported framework"}
            continue
        try:
            import_module(module_name)
            out[framework] = {"ok": True, "detail": module_name}
        except Exception as exc:
            out[framework] = {"ok": False, "detail": str(exc)}
    return out
