from __future__ import annotations

import asyncio
import signal
import time
from dataclasses import dataclass, field
from typing import Callable, cast

import pytest
import upnext.engine.runner as runner_module
from upnext.sdk.api import Api
from upnext.sdk.worker import Worker


@dataclass
class _SignalLoopStub:
    handlers: dict[signal.Signals, Callable[[], None]] = field(default_factory=dict)
    removed: list[signal.Signals] = field(default_factory=list)

    def add_signal_handler(
        self, sig: signal.Signals, callback: Callable[[], None]
    ) -> None:
        self.handlers[sig] = callback

    def remove_signal_handler(self, sig: signal.Signals) -> None:
        self.removed.append(sig)
        self.handlers.pop(sig, None)


class _BlockingApi:
    def __init__(self, name: str) -> None:
        self.name = name
        self.handle_signals = True
        self.stop_calls = 0
        self.start_cancelled = False
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        try:
            await self._stopped.wait()
        except asyncio.CancelledError:
            self.start_cancelled = True
            raise

    def stop(self) -> None:
        self.stop_calls += 1
        self._stopped.set()


class _NeverStoppingApi(_BlockingApi):
    def stop(self) -> None:
        self.stop_calls += 1
        # Intentionally do not release start(); run_services should cancel this task.


class _CrashApi:
    def __init__(self, name: str, exc: Exception) -> None:
        self.name = name
        self.handle_signals = True
        self.stop_calls = 0
        self._exc = exc

    async def start(self) -> None:
        raise self._exc

    def stop(self) -> None:
        self.stop_calls += 1


class _ExitApi:
    def __init__(self, name: str) -> None:
        self.name = name
        self.handle_signals = True
        self.stop_calls = 0

    async def start(self) -> None:
        return None

    def stop(self) -> None:
        self.stop_calls += 1


class _CancelledApi:
    def __init__(self, name: str) -> None:
        self.name = name
        self.handle_signals = True
        self.stop_calls = 0

    async def start(self) -> None:
        raise asyncio.CancelledError

    def stop(self) -> None:
        self.stop_calls += 1


class _BlockingWorker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.handle_signals = True
        self.stop_timeouts: list[float] = []
        self.start_cancelled = False
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        try:
            await self._stopped.wait()
        except asyncio.CancelledError:
            self.start_cancelled = True
            raise

    async def stop(self, timeout: float = 30.0) -> None:
        self.stop_timeouts.append(timeout)
        self._stopped.set()


class _StopErrorWorker(_BlockingWorker):
    async def stop(self, timeout: float = 30.0) -> None:
        self.stop_timeouts.append(timeout)
        raise RuntimeError("worker stop failed")


async def _wait_for(predicate: Callable[[], bool], *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("Timed out waiting for condition")


@pytest.mark.asyncio
async def test_run_services_graceful_shutdown_stops_components(monkeypatch) -> None:
    loop_stub = _SignalLoopStub()
    api = _BlockingApi("api-main")
    worker = _BlockingWorker("worker-main")
    monkeypatch.setattr(runner_module.asyncio, "get_running_loop", lambda: loop_stub)

    run_task = asyncio.create_task(
        runner_module.run_services(
            cast(list[Api], [api]),
            cast(list[Worker], [worker]),
            worker_timeout=2.5,
            api_timeout=0.05,
        )
    )

    await _wait_for(lambda: signal.SIGINT in loop_stub.handlers)
    loop_stub.handlers[signal.SIGINT]()
    await run_task

    assert api.handle_signals is False
    assert worker.handle_signals is False
    assert api.stop_calls == 1
    assert worker.stop_timeouts == [2.5]
    assert set(loop_stub.removed) == {signal.SIGINT, signal.SIGTERM}


@pytest.mark.asyncio
async def test_run_services_ignores_duplicate_second_signal_within_debounce(
    monkeypatch,
) -> None:
    loop_stub = _SignalLoopStub()
    api = _BlockingApi("api-debounce")
    worker = _BlockingWorker("worker-debounce")
    monkeypatch.setattr(runner_module.asyncio, "get_running_loop", lambda: loop_stub)

    monotonic_values = [100.0, 100.1]

    def _monotonic() -> float:
        if monotonic_values:
            return monotonic_values.pop(0)
        return 100.1

    monkeypatch.setattr(runner_module.time, "monotonic", _monotonic)

    def _unexpected_exit(code: int) -> None:
        raise AssertionError(
            f"os._exit({code}) should not be called for duplicate signal"
        )

    monkeypatch.setattr(runner_module.os, "_exit", _unexpected_exit)

    run_task = asyncio.create_task(
        runner_module.run_services(
            cast(list[Api], [api]),
            cast(list[Worker], [worker]),
            api_timeout=0.05,
        )
    )
    await _wait_for(lambda: signal.SIGINT in loop_stub.handlers)

    loop_stub.handlers[signal.SIGINT]()
    loop_stub.handlers[signal.SIGINT]()
    await run_task

    assert api.stop_calls == 1
    assert worker.stop_timeouts == [runner_module.DEFAULT_WORKER_TIMEOUT]


@pytest.mark.asyncio
async def test_run_services_raises_when_service_crashes(monkeypatch) -> None:
    loop_stub = _SignalLoopStub()
    api = _CrashApi("api-crash", RuntimeError("boom"))
    worker = _BlockingWorker("worker-crash")
    monkeypatch.setattr(runner_module.asyncio, "get_running_loop", lambda: loop_stub)

    with pytest.raises(
        RuntimeError, match="Service 'api:api-crash' crashed; shutting down."
    ):
        await runner_module.run_services(
            cast(list[Api], [api]),
            cast(list[Worker], [worker]),
            api_timeout=0.05,
        )

    assert api.stop_calls == 1
    assert worker.stop_timeouts == [runner_module.DEFAULT_WORKER_TIMEOUT]
    assert set(loop_stub.removed) == {signal.SIGINT, signal.SIGTERM}


@pytest.mark.asyncio
async def test_run_services_raises_when_service_exits_without_error(
    monkeypatch,
) -> None:
    loop_stub = _SignalLoopStub()
    api = _ExitApi("api-exit")
    worker = _BlockingWorker("worker-exit")
    monkeypatch.setattr(runner_module.asyncio, "get_running_loop", lambda: loop_stub)

    with pytest.raises(
        RuntimeError,
        match="Service 'api:api-exit' exited unexpectedly; shutting down.",
    ):
        await runner_module.run_services(
            cast(list[Api], [api]),
            cast(list[Worker], [worker]),
            api_timeout=0.05,
        )

    assert api.stop_calls == 1
    assert worker.stop_timeouts == [runner_module.DEFAULT_WORKER_TIMEOUT]


@pytest.mark.asyncio
async def test_run_services_treats_cancelled_service_task_as_unexpected_exit(
    monkeypatch,
) -> None:
    loop_stub = _SignalLoopStub()
    api = _CancelledApi("api-cancelled")
    worker = _BlockingWorker("worker-cancelled")
    monkeypatch.setattr(runner_module.asyncio, "get_running_loop", lambda: loop_stub)

    with pytest.raises(
        RuntimeError,
        match="Service 'api:api-cancelled' exited unexpectedly; shutting down.",
    ):
        await runner_module.run_services(
            cast(list[Api], [api]),
            cast(list[Worker], [worker]),
            api_timeout=0.05,
        )

    assert api.stop_calls == 1
    assert worker.stop_timeouts == [runner_module.DEFAULT_WORKER_TIMEOUT]


@pytest.mark.asyncio
async def test_run_services_cancels_pending_api_tasks_after_timeout(
    monkeypatch,
) -> None:
    loop_stub = _SignalLoopStub()
    api = _NeverStoppingApi("api-pending")
    monkeypatch.setattr(runner_module.asyncio, "get_running_loop", lambda: loop_stub)

    run_task = asyncio.create_task(
        runner_module.run_services(cast(list[Api], [api]), [], api_timeout=0.01)
    )
    await _wait_for(lambda: signal.SIGINT in loop_stub.handlers)
    loop_stub.handlers[signal.SIGINT]()
    await run_task

    assert api.stop_calls == 1
    assert api.start_cancelled is True


@pytest.mark.asyncio
async def test_run_services_swallows_worker_stop_exceptions(monkeypatch) -> None:
    loop_stub = _SignalLoopStub()
    api = _BlockingApi("api-stop-exc")
    worker = _StopErrorWorker("worker-stop-exc")
    monkeypatch.setattr(runner_module.asyncio, "get_running_loop", lambda: loop_stub)

    run_task = asyncio.create_task(
        runner_module.run_services(
            cast(list[Api], [api]),
            cast(list[Worker], [worker]),
            worker_timeout=1.25,
            api_timeout=0.01,
        )
    )
    await _wait_for(lambda: signal.SIGINT in loop_stub.handlers)
    loop_stub.handlers[signal.SIGINT]()
    await run_task

    assert api.stop_calls == 1
    assert worker.stop_timeouts == [1.25]
    assert worker.start_cancelled is True
