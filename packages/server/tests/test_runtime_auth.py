from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import server.auth as auth_module
from server.runtime_scope import RuntimeModes, RuntimeRoles


def _make_request(token: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/jobs",
            "headers": headers,
        }
    )


def _encode_runtime_token(secret: str, payload: dict[str, object]) -> str:
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    body = _b64url(json.dumps(payload).encode("utf-8"))
    signing_input = f"{header}.{body}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(signature)}"


@dataclass
class _SelfHostedSettings:
    auth_enabled: bool = False
    api_key: str | None = None
    runtime_token_secret: str | None = None
    runtime_token_issuer: str = "upnext-saas"
    runtime_token_audience: str = "upnext-runtime"
    default_deployment_id: str = "local"
    is_cloud_runtime: bool = False

    @property
    def normalized_default_deployment_id(self) -> str:
        return self.default_deployment_id


@dataclass
class _CloudRuntimeSettings:
    auth_enabled: bool = True
    runtime_token_secret: str = "cloud-secret"
    runtime_token_issuer: str = "upnext-saas"
    runtime_token_audience: str = "upnext-runtime"
    default_deployment_id: str = "dep_orders_api"
    is_cloud_runtime: bool = True

    @property
    def normalized_default_deployment_id(self) -> str:
        return self.default_deployment_id


@pytest.mark.asyncio
async def test_require_api_key_returns_local_admin_scope_when_self_hosted_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "get_settings", lambda: _SelfHostedSettings())

    scope = await auth_module.require_api_key(_make_request())

    assert scope.deployment_id == "local"
    assert scope.mode == RuntimeModes.SELF_HOSTED
    assert scope.role == RuntimeRoles.ADMIN


@pytest.mark.asyncio
async def test_require_api_key_validates_static_self_hosted_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: _SelfHostedSettings(auth_enabled=True, api_key="local-secret"),
    )

    scope = await auth_module.require_api_key(_make_request("local-secret"))

    assert scope.deployment_id == "local"
    assert scope.mode == RuntimeModes.SELF_HOSTED
    assert scope.role == RuntimeRoles.ADMIN
    assert scope.subject == "self-hosted-token"


@pytest.mark.asyncio
async def test_require_api_key_decodes_cloud_runtime_token_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _CloudRuntimeSettings()
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)

    token = _encode_runtime_token(
        settings.runtime_token_secret,
        {
            "iss": settings.runtime_token_issuer,
            "aud": settings.runtime_token_audience,
            "sub": "dep_orders_api:user_demo_01",
            "workspace_id": "ws_demo_01",
            "deployment_id": "dep_orders_api",
            "role": "admin",
            "exp": int(time()) + 300,
        },
    )

    scope = await auth_module.require_api_key(_make_request(token))

    assert scope.deployment_id == "dep_orders_api"
    assert scope.workspace_id == "ws_demo_01"
    assert scope.mode == RuntimeModes.CLOUD_RUNTIME
    assert scope.role == RuntimeRoles.ADMIN
    assert scope.subject == "dep_orders_api:user_demo_01"


@pytest.mark.asyncio
async def test_require_admin_allows_cloud_runtime_admin_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _CloudRuntimeSettings()
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)

    token = _encode_runtime_token(
        settings.runtime_token_secret,
        {
            "iss": settings.runtime_token_issuer,
            "aud": settings.runtime_token_audience,
            "sub": "dep_orders_api:user_demo_01",
            "workspace_id": "ws_demo_01",
            "deployment_id": "dep_orders_api",
            "role": "admin",
            "exp": int(time()) + 300,
        },
    )

    scope = await auth_module.require_admin(
        await auth_module.require_api_key(_make_request(token))
    )

    assert scope.role == RuntimeRoles.ADMIN


@pytest.mark.asyncio
async def test_require_admin_rejects_non_admin_cloud_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _CloudRuntimeSettings()
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)

    token = _encode_runtime_token(
        settings.runtime_token_secret,
        {
            "iss": settings.runtime_token_issuer,
            "aud": settings.runtime_token_audience,
            "sub": "dep_orders_api:user_demo_01",
            "workspace_id": "ws_demo_01",
            "deployment_id": "dep_orders_api",
            "role": "viewer",
            "exp": int(time()) + 300,
        },
    )

    with pytest.raises(HTTPException, match="Admin access required") as exc:
        await auth_module.require_admin(
            await auth_module.require_api_key(_make_request(token))
        )

    assert exc.value.status_code == 403
