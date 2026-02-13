from __future__ import annotations

from typing import Any, cast

import pytest
from shared.artifacts import ArtifactType
from shared.contracts.artifacts import CreateArtifactRequest, ErrorResponse
from upnext.engine.backend_api import BackendAPI
from upnext.sdk.artifacts import create_artifact, create_artifact_sync
from upnext.sdk.context import Context, set_current_context


class _ResponseStub:
    def __init__(
        self,
        *,
        status: int,
        json_payload: dict[str, Any],
        text_payload: str = "",
    ) -> None:
        self.status = status
        self._json_payload = json_payload
        self._text_payload = text_payload

    async def __aenter__(self) -> "_ResponseStub":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._json_payload

    async def text(self) -> str:
        return self._text_payload


class _SessionStub:
    def __init__(self, response: _ResponseStub) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any]) -> _ResponseStub:
        self.calls.append({"url": url, "json": json})
        return self._response


class _BackendStub:
    def __init__(self) -> None:
        self.last_job_id: str | None = None
        self.last_payload: CreateArtifactRequest | None = None

    async def __aenter__(self) -> "_BackendStub":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        return None

    async def create_artifact(
        self,
        job_id: str,
        payload: CreateArtifactRequest,
    ) -> ErrorResponse:
        self.last_job_id = job_id
        self.last_payload = payload
        return ErrorResponse(detail="stubbed")


@pytest.mark.asyncio
async def test_backend_api_create_artifact_serializes_model_payload() -> None:
    session = _SessionStub(
        _ResponseStub(
            status=200,
            json_payload={
                "id": "art_1",
                "job_id": "job_1",
                "name": "result",
                "type": "json",
                "storage_backend": "local",
                "storage_key": "a/b/c",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )
    )
    api = BackendAPI.__new__(BackendAPI)
    api._session = cast(Any, session)
    api._base_url = "http://test.local/api/v1"

    result = await api.create_artifact(
        "job_1",
        CreateArtifactRequest(
            name="result",
            type=ArtifactType.JSON,
            data={"ok": True},
        ),
    )

    assert session.calls[0]["url"] == "http://test.local/api/v1/jobs/job_1/artifacts"
    assert session.calls[0]["json"] == {
        "name": "result",
        "type": "json",
        "data": {"ok": True},
    }
    assert getattr(result, "job_id", None) == "job_1"


@pytest.mark.asyncio
async def test_create_artifact_uses_current_context_job_id(monkeypatch) -> None:
    backend = _BackendStub()
    monkeypatch.setattr("upnext.sdk.artifacts.get_backend_api", lambda: backend)

    set_current_context(
        Context(
            job_id="job_ctx_1",
            job_key="ctx-key",
        )
    )
    try:
        result = await create_artifact(
            "artifact.json",
            {"value": 1},
            ArtifactType.JSON,
        )
    finally:
        set_current_context(None)

    assert isinstance(result, ErrorResponse)
    assert backend.last_job_id == "job_ctx_1"
    assert backend.last_payload is not None
    assert backend.last_payload.name == "artifact.json"
    assert backend.last_payload.type == ArtifactType.JSON
    assert backend.last_payload.data == {"value": 1}


@pytest.mark.asyncio
async def test_create_artifact_sync_rejects_running_event_loop() -> None:
    with pytest.raises(RuntimeError, match="cannot run inside an active event loop"):
        create_artifact_sync("artifact.json", {"value": 1}, ArtifactType.JSON)
