from __future__ import annotations

import asyncio
import importlib
import logging
import os
from pathlib import Path
from typing import Any

import pytest
import typer
from rich.panel import Panel
from typer.testing import CliRunner

from conduit.cli.__init__ import _version_callback, app
from conduit.cli._console import (
    dim,
    error,
    error_panel,
    header,
    info,
    nl,
    setup_logging,
    success,
    warning,
)
from conduit.cli._display import filter_components, print_services_panel, worker_lines
from conduit.cli._loader import discover_objects, import_file
from conduit.cli.list import list_cmd
from conduit.cli.server import _build_alembic_config, _find_server_root_dir, _set_server_env
from conduit.sdk.api import Api
from conduit.sdk.worker import Worker

call_module = importlib.import_module("conduit.cli.call")
run_module = importlib.import_module("conduit.cli.run")


def _run_coroutine(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_cli_app_help_and_version() -> None:
    runner = CliRunner()
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "conduit" in help_result.stdout
    assert "run" in help_result.stdout
    assert "call" in help_result.stdout

    version_result = runner.invoke(app, ["--version"])
    assert version_result.exit_code == 0
    assert "conduit" in version_result.stdout


def test_version_callback_noop_when_false() -> None:
    assert _version_callback(False) is None


def test_console_helpers_emit_output(monkeypatch) -> None:
    outputs: list[str] = []
    monkeypatch.setattr(
        "conduit.cli._console.console.print",
        lambda *args, **kwargs: outputs.append(str(args[0]) if args else ""),
    )

    header("Title")
    success("ok")
    error("bad")
    warning("warn")
    info("info")
    dim("dim")
    error_panel("boom", title="Failed")
    nl()

    assert any("Title" in line for line in outputs)
    assert any("ok" in line for line in outputs)
    assert any("bad" in line for line in outputs)
    assert any("warn" in line for line in outputs)
    assert any("info" in line for line in outputs)
    assert any("dim" in line for line in outputs)
    assert len(outputs) >= 8


def test_setup_logging_sets_expected_levels() -> None:
    setup_logging(verbose=False)
    assert logging.getLogger("conduit").level == logging.INFO

    setup_logging(verbose=True)
    assert logging.getLogger("conduit").level == logging.DEBUG


def test_import_file_validation_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    with pytest.raises(typer.Exit):
        import_file(str(missing))

    text_file = tmp_path / "not_python.txt"
    text_file.write_text("hello", encoding="utf-8")
    with pytest.raises(typer.Exit):
        import_file(str(text_file))


def test_discover_objects_loads_apis_and_workers(tmp_path: Path) -> None:
    service_file = tmp_path / "service.py"
    service_file.write_text(
        "\n".join(
            [
                "from conduit import Api, Worker",
                "api = Api('api-1', redis_url=None)",
                "worker = Worker('worker-1', redis_url='redis://test')",
            ]
        ),
        encoding="utf-8",
    )

    apis, workers = discover_objects([str(service_file)])
    assert [api.name for api in apis] == ["api-1"]
    assert [worker.name for worker in workers] == ["worker-1"]


def test_filter_components_happy_path_and_errors() -> None:
    api = Api("api-1", redis_url=None)
    worker = Worker("worker-1", redis_url="redis://test")

    filtered_apis, filtered_workers = filter_components(
        [api], [worker], only=["worker-1"]
    )
    assert filtered_apis == []
    assert filtered_workers == [worker]

    with pytest.raises(typer.Exit):
        filter_components([api], [worker], only=["missing"])

    with pytest.raises(typer.Exit):
        filter_components([], [], only=None)


def test_worker_lines_and_services_panel_render(monkeypatch) -> None:
    worker = Worker(name="display-worker", redis_url="redis://test")

    @worker.task
    async def task_a() -> str:
        return "ok"

    @worker.cron("* * * * *")
    async def cron_a() -> None:
        return None

    event = worker.event("user.*")

    @event.on(name="handler-a")
    async def event_handler(user_id: str) -> None:
        return None

    lines = worker_lines(worker)
    joined = "\n".join(str(line) for line in lines)
    assert "display-worker" in joined
    assert "tasks" in joined
    assert "crons" in joined
    assert "events" in joined

    rendered: list[object] = []
    line_fn_calls: list[str] = []

    def line_fn_spy(display_worker: Worker):  # type: ignore[no-untyped-def]
        line_fn_calls.append(display_worker.name)
        return worker_lines(display_worker)

    monkeypatch.setattr(
        "conduit.cli._display.console.print",
        lambda *args, **kwargs: rendered.append(args[0] if args else ""),
    )
    monkeypatch.setattr("conduit.cli._display.nl", lambda: None)

    api = Api("api-1", redis_url=None)
    print_services_panel(
        [api],
        [worker],
        title="conduit",
        worker_line_fn=line_fn_spy,
        redis_url="redis://test",
    )
    assert line_fn_calls == ["display-worker"]
    assert len(rendered) == 1
    assert isinstance(rendered[0], Panel)
    assert "conduit" in str(rendered[0].title)
    assert "redis://test" in str(rendered[0].subtitle)


def test_run_command_success(monkeypatch) -> None:
    worker = Worker(name="runner-worker", redis_url="redis://worker")
    api = Api("runner-api", redis_url="redis://api")
    captured: dict[str, Any] = {}

    async def fake_run_services(apis: list[Api], workers: list[Worker]) -> None:
        captured["apis"] = apis
        captured["workers"] = workers

    monkeypatch.setattr("conduit.sdk.worker.create_redis_client", lambda _url: object())
    monkeypatch.setattr(run_module, "discover_objects", lambda _files: ([api], [worker]))
    monkeypatch.setattr(run_module, "run_services", fake_run_services)
    monkeypatch.setattr(run_module, "print_services_panel", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_module, "nl", lambda: None)
    monkeypatch.setattr(run_module.asyncio, "run", _run_coroutine)

    run_module.run(
        files=["service.py"], redis_url="redis://override", only=None, verbose=False
    )
    assert captured["apis"] == [api]
    assert captured["workers"] == [worker]
    assert worker.resolved_redis_url == "redis://override"


def test_run_command_exits_on_worker_configuration_error(monkeypatch) -> None:
    worker = Worker(name="runner-worker")
    monkeypatch.setattr(run_module, "discover_objects", lambda _files: ([], [worker]))
    monkeypatch.setattr(run_module, "error_panel", lambda *_args, **_kwargs: None)

    with pytest.raises(typer.Exit):
        run_module.run(files=["service.py"], redis_url=None, only=None, verbose=False)


def test_call_command_success_and_argument_parsing(monkeypatch) -> None:
    worker = Worker(name="caller-worker", redis_url="redis://worker")

    @worker.task(name="add")
    async def add(x: int, y: int) -> int:
        return x + y

    async def fake_execute(function_name: str, kwargs: dict[str, Any]) -> Any:
        assert function_name == "add"
        return kwargs["x"] + kwargs["y"]

    monkeypatch.setattr(worker, "execute", fake_execute)
    monkeypatch.setattr("conduit.sdk.worker.create_redis_client", lambda _url: object())
    monkeypatch.setattr(call_module, "discover_objects", lambda _files: ([], [worker]))
    monkeypatch.setattr(call_module, "_print_call_panel", lambda *args, **kwargs: None)

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        call_module,
        "_print_result_panel",
        lambda result, duration_ms: captured.setdefault("result", result),
    )
    monkeypatch.setattr(call_module, "nl", lambda: None)
    monkeypatch.setattr(call_module.asyncio, "run", _run_coroutine)

    call_module.call(
        file="service.py",
        function="add",
        redis_url="redis://override",
        args=["x=1", "y=2"],
        json_args=None,
        verbose=False,
    )
    assert captured["result"] == 3


def test_call_command_error_paths(monkeypatch) -> None:
    with pytest.raises(typer.Exit):
        call_module.call(
            file="service.py",
            function="noop",
            redis_url=None,
            args=None,
            json_args="{bad-json}",
            verbose=False,
        )

    worker = Worker(name="caller-worker", redis_url="redis://worker")
    monkeypatch.setattr(call_module, "discover_objects", lambda _files: ([], [worker]))
    monkeypatch.setattr(call_module, "error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(call_module, "nl", lambda: None)

    with pytest.raises(typer.Exit):
        call_module.call(
            file="service.py",
            function="missing",
            redis_url=None,
            args=None,
            json_args=None,
            verbose=False,
        )


def test_list_command_handles_empty_and_populated_results(monkeypatch) -> None:
    monkeypatch.setattr("conduit.cli.list.discover_objects", lambda _files: ([], []))
    monkeypatch.setattr("conduit.cli.list.error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("conduit.cli.list.nl", lambda: None)
    with pytest.raises(typer.Exit):
        list_cmd(files=["service.py"])

    api = Api("api-list", redis_url=None)
    worker = Worker("worker-list", redis_url="redis://worker")

    @worker.task
    async def ping() -> str:
        return "pong"

    monkeypatch.setattr("conduit.cli.list.discover_objects", lambda _files: ([api], [worker]))
    rendered: list[object] = []
    summaries: list[str] = []
    monkeypatch.setattr(
        "conduit.cli.list.console.print",
        lambda *args, **_kwargs: rendered.append(args[0] if args else ""),
    )
    monkeypatch.setattr(
        "conduit.cli.list.dim",
        lambda message, *_args, **_kwargs: summaries.append(str(message)),
    )
    monkeypatch.setattr("conduit.cli.list.nl", lambda: None)
    list_cmd(files=["service.py"])
    assert len(rendered) == 2
    assert summaries == ["1 API · 1 Worker · 1 task"]


def test_server_helpers(monkeypatch, tmp_path: Path) -> None:
    _set_server_env("sqlite:///tmp.db", "redis://localhost:6379")
    assert os.environ["CONDUIT_DATABASE_URL"] == "sqlite:///tmp.db"
    assert os.environ["DATABASE_URL"] == "sqlite:///tmp.db"
    assert os.environ["CONDUIT_REDIS_URL"] == "redis://localhost:6379"

    server_root = _find_server_root_dir()
    assert server_root is not None

    cfg = _build_alembic_config(server_root)
    script_location = cfg.get_main_option("script_location")
    prepend_sys_path = cfg.get_main_option("prepend_sys_path")
    assert script_location is not None
    assert prepend_sys_path is not None
    assert script_location.endswith("alembic")
    assert prepend_sys_path.endswith("src")

    missing_root = tmp_path / "missing-server"
    missing_root.mkdir()
    monkeypatch.setattr("conduit.cli.server.error_panel", lambda *_args, **_kwargs: None)
    with pytest.raises(typer.Exit):
        _build_alembic_config(missing_root)
