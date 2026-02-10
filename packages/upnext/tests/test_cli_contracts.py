from __future__ import annotations

import asyncio
import builtins
import importlib
import logging
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
import typer
from rich.panel import Panel
from typer.testing import CliRunner
from upnext.cli.__init__ import _version_callback, app
from upnext.cli._console import (
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
from upnext.cli._display import filter_components, print_services_panel, worker_lines
from upnext.cli._loader import discover_objects, import_file
from upnext.cli.list import list_cmd
from upnext.cli.server import (
    _build_alembic_config,
    _ensure_database_schema_ready,
    _find_server_root_dir,
    _import_server_main,
    _resolve_alembic_config,
    _set_server_env,
)
from upnext.sdk.api import Api
from upnext.sdk.worker import Worker

call_module = importlib.import_module("upnext.cli.call")
run_module = importlib.import_module("upnext.cli.run")
server_module = importlib.import_module("upnext.cli.server")


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
    assert "upnext" in help_result.stdout
    assert "run" in help_result.stdout
    assert "call" in help_result.stdout

    version_result = runner.invoke(app, ["--version"])
    assert version_result.exit_code == 0
    assert "upnext" in version_result.stdout


def test_version_callback_noop_when_false() -> None:
    assert _version_callback(False) is None


def test_console_helpers_emit_output(monkeypatch) -> None:
    outputs: list[str] = []
    monkeypatch.setattr(
        "upnext.cli._console.console.print",
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
    assert logging.getLogger("upnext").level == logging.INFO

    setup_logging(verbose=True)
    assert logging.getLogger("upnext").level == logging.DEBUG


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
                "from upnext import Api, Worker",
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
        "upnext.cli._display.console.print",
        lambda *args, **kwargs: rendered.append(args[0] if args else ""),
    )
    monkeypatch.setattr("upnext.cli._display.nl", lambda: None)

    api = Api("api-1", redis_url=None)
    print_services_panel(
        [api],
        [worker],
        title="upnext",
        worker_line_fn=line_fn_spy,
        redis_url="redis://test",
    )
    assert line_fn_calls == ["display-worker"]
    assert len(rendered) == 1
    assert isinstance(rendered[0], Panel)
    assert "upnext" in str(rendered[0].title)
    assert "redis://test" in str(rendered[0].subtitle)


def test_run_command_success(monkeypatch) -> None:
    worker = Worker(name="runner-worker", redis_url="redis://worker")
    api = Api("runner-api", redis_url="redis://api")
    captured: dict[str, Any] = {}

    async def fake_run_services(apis: list[Api], workers: list[Worker]) -> None:
        captured["apis"] = apis
        captured["workers"] = workers

    monkeypatch.setattr("upnext.sdk.worker.create_redis_client", lambda _url: object())
    monkeypatch.setattr(
        run_module, "discover_objects", lambda _files: ([api], [worker])
    )
    monkeypatch.setattr(run_module, "run_services", fake_run_services)
    monkeypatch.setattr(
        run_module, "print_services_panel", lambda *args, **kwargs: None
    )
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
    monkeypatch.setattr("upnext.sdk.worker.create_redis_client", lambda _url: object())
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
    monkeypatch.setattr("upnext.cli.list.discover_objects", lambda _files: ([], []))
    monkeypatch.setattr("upnext.cli.list.error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("upnext.cli.list.nl", lambda: None)
    with pytest.raises(typer.Exit):
        list_cmd(files=["service.py"])

    api = Api("api-list", redis_url=None)
    worker = Worker("worker-list", redis_url="redis://worker")

    @worker.task
    async def ping() -> str:
        return "pong"

    monkeypatch.setattr(
        "upnext.cli.list.discover_objects", lambda _files: ([api], [worker])
    )
    rendered: list[object] = []
    summaries: list[str] = []
    monkeypatch.setattr(
        "upnext.cli.list.console.print",
        lambda *args, **_kwargs: rendered.append(args[0] if args else ""),
    )
    monkeypatch.setattr(
        "upnext.cli.list.dim",
        lambda message, *_args, **_kwargs: summaries.append(str(message)),
    )
    monkeypatch.setattr("upnext.cli.list.nl", lambda: None)
    list_cmd(files=["service.py"])
    assert len(rendered) == 2
    assert summaries == ["1 API · 1 Worker · 1 task"]


def test_server_helpers(monkeypatch, tmp_path: Path) -> None:
    original_env = {
        "UPNEXT_DATABASE_URL": os.environ.get("UPNEXT_DATABASE_URL"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "UPNEXT_REDIS_URL": os.environ.get("UPNEXT_REDIS_URL"),
    }
    try:
        _set_server_env("sqlite:///tmp.db", "redis://localhost:6379")
        assert os.environ["UPNEXT_DATABASE_URL"] == "sqlite:///tmp.db"
        assert os.environ["DATABASE_URL"] == "sqlite:///tmp.db"
        assert os.environ["UPNEXT_REDIS_URL"] == "redis://localhost:6379"
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    server_root = _find_server_root_dir()
    assert server_root is not None

    cfg = _build_alembic_config(server_root)
    script_location = cfg.get_main_option("script_location")
    prepend_sys_path = cfg.get_main_option("prepend_sys_path")
    assert script_location is not None
    assert prepend_sys_path is not None
    assert script_location.endswith("alembic")
    assert prepend_sys_path.endswith("src")

    packaged_ini = tmp_path / "alembic.ini"
    packaged_script_location = tmp_path / "_alembic"
    packaged_script_location.mkdir()
    packaged_ini.write_text("[alembic]\n", encoding="utf-8")
    packaged_cfg = _build_alembic_config(
        alembic_ini=packaged_ini,
        script_location=packaged_script_location,
    )
    packaged_script = packaged_cfg.get_main_option("script_location")
    assert packaged_script is not None
    assert packaged_script.endswith("_alembic")

    monkeypatch.setattr("upnext.cli.server._find_server_root_dir", lambda: None)
    monkeypatch.setattr(
        "upnext.cli.server._find_packaged_alembic_paths",
        lambda: (packaged_ini, packaged_script_location),
    )
    with _resolve_alembic_config() as resolved_cfg:
        resolved_script = cast(Any, resolved_cfg).get_main_option("script_location")
        assert resolved_script is not None
        assert resolved_script.endswith("_alembic")

    missing_root = tmp_path / "missing-server"
    missing_root.mkdir()
    monkeypatch.setattr("upnext.cli.server.error_panel", lambda *_args, **_kwargs: None)
    with pytest.raises(typer.Exit):
        _build_alembic_config(missing_root)


def test_import_server_main_fails_fast_on_missing_dependency(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "server.main":
            raise ModuleNotFoundError("No module named 'sqlalchemy'", name="sqlalchemy")
        return real_import(name, *args, **kwargs)

    errors: list[str] = []
    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.setattr(
        "upnext.cli.server.error_panel",
        lambda message, **_kwargs: errors.append(str(message)),
    )

    with pytest.raises(typer.Exit):
        _import_server_main()

    assert errors
    assert "missing dependency" in errors[0]


def test_db_commands_preserve_typer_exit(monkeypatch) -> None:
    @contextmanager
    def raise_exit() -> Any:
        raise typer.Exit(7)
        yield  # pragma: no cover

    monkeypatch.setattr(server_module, "_resolve_alembic_config", raise_exit)
    error_calls: list[str] = []
    monkeypatch.setattr(
        "upnext.cli.server.error_panel",
        lambda message, **_kwargs: error_calls.append(str(message)),
    )

    with pytest.raises(typer.Exit) as upgrade_exc:
        server_module.db_upgrade(revision="head", database_url=None, verbose=False)
    assert upgrade_exc.value.exit_code == 7

    with pytest.raises(typer.Exit) as current_exc:
        server_module.db_current(database_url=None, verbose=False)
    assert current_exc.value.exit_code == 7

    with pytest.raises(typer.Exit) as history_exc:
        server_module.db_history(rev_range=None, database_url=None, verbose=False)
    assert history_exc.value.exit_code == 7

    assert error_calls == []


def test_server_start_passes_reload_dir_for_monorepo_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    env_calls: list[tuple[str | None, str | None]] = []
    server_src = tmp_path / "server-src"
    server_src.mkdir()

    monkeypatch.setattr(server_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        server_module,
        "_set_server_env",
        lambda database_url, redis_url: env_calls.append((database_url, redis_url)),
    )
    monkeypatch.setattr(
        server_module,
        "_ensure_database_schema_ready",
        lambda database_url, verbose: None,
    )
    monkeypatch.setattr(server_module, "_import_server_main", lambda: server_src)

    def fake_uvicorn_run(app: str, **kwargs: Any) -> None:
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )

    server_module.start(
        host="127.0.0.1",
        port=9090,
        reload=True,
        database_url="sqlite:///test.db",
        redis_url="redis://localhost:6379",
        verbose=True,
    )

    assert env_calls == [("sqlite:///test.db", "redis://localhost:6379")]
    assert captured["app"] == "server.main:app"
    run_kwargs = cast(dict[str, Any], captured["kwargs"])
    assert run_kwargs["host"] == "127.0.0.1"
    assert run_kwargs["port"] == 9090
    assert run_kwargs["reload"] is True
    assert run_kwargs["reload_dirs"] == [str(server_src)]


def test_server_start_wraps_uvicorn_runtime_errors(monkeypatch) -> None:
    errors: list[str] = []

    monkeypatch.setattr(server_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        server_module, "_set_server_env", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        server_module,
        "_ensure_database_schema_ready",
        lambda database_url, verbose: None,
    )
    monkeypatch.setattr(server_module, "_import_server_main", lambda: None)
    monkeypatch.setattr(
        server_module,
        "error_panel",
        lambda message, **_kwargs: errors.append(str(message)),
    )

    def fake_uvicorn_run(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("uvicorn failure")

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=fake_uvicorn_run)
    )

    with pytest.raises(typer.Exit) as exc:
        server_module.start(
            host="0.0.0.0",
            port=8080,
            reload=False,
            database_url=None,
            redis_url=None,
            verbose=False,
        )
    assert exc.value.exit_code == 1
    assert errors == ["uvicorn failure"]


def test_db_commands_invoke_expected_alembic_apis(monkeypatch) -> None:
    env_calls: list[tuple[str | None, str | None]] = []
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    cfg = object()

    @contextmanager
    def fake_resolve_cfg() -> Any:
        yield cfg

    monkeypatch.setattr(server_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        server_module,
        "_set_server_env",
        lambda database_url, redis_url: env_calls.append((database_url, redis_url)),
    )
    monkeypatch.setattr(server_module, "_resolve_alembic_config", fake_resolve_cfg)

    class CommandStub:
        def upgrade(self, config: Any, revision: str) -> None:
            calls.append(("upgrade", (config, revision), {}))

        def current(self, config: Any, *, verbose: bool) -> None:
            calls.append(("current", (config,), {"verbose": verbose}))

        def history(
            self,
            config: Any,
            *,
            rev_range: str | None,
            verbose: bool,
            indicate_current: bool,
        ) -> None:
            calls.append(
                (
                    "history",
                    (config,),
                    {
                        "rev_range": rev_range,
                        "verbose": verbose,
                        "indicate_current": indicate_current,
                    },
                )
            )

    alembic_module = types.ModuleType("alembic")
    alembic_module.command = CommandStub()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "alembic", alembic_module)

    server_module.db_upgrade(
        revision="head",
        database_url="sqlite:///migrations.db",
        verbose=False,
    )
    server_module.db_current(
        database_url="sqlite:///migrations.db",
        verbose=True,
    )
    server_module.db_history(
        rev_range="base:head",
        database_url="sqlite:///migrations.db",
        verbose=True,
    )

    assert env_calls == [
        ("sqlite:///migrations.db", None),
        ("sqlite:///migrations.db", None),
        ("sqlite:///migrations.db", None),
    ]
    assert calls == [
        ("upgrade", (cfg, "head"), {}),
        ("current", (cfg,), {"verbose": True}),
        (
            "history",
            (cfg,),
            {"rev_range": "base:head", "verbose": True, "indicate_current": True},
        ),
    ]


def test_ensure_database_schema_ready_runs_migrations_when_confirmed(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str | None, bool]] = []

    monkeypatch.setattr(
        server_module,
        "_resolve_effective_database_url",
        lambda _database_url: "postgresql+asyncpg://user:pass@localhost/upnext",
    )

    async def fake_missing_tables(_database_url: str) -> list[str]:
        return ["artifacts", "job_history"]

    monkeypatch.setattr(
        server_module, "_get_missing_required_tables", fake_missing_tables
    )
    monkeypatch.setattr(server_module.typer, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        server_module,
        "db_upgrade",
        lambda revision, database_url, verbose: calls.append(
            (revision, database_url, verbose)
        ),
    )
    monkeypatch.setattr(server_module, "warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server_module, "success", lambda *_args, **_kwargs: None)

    _ensure_database_schema_ready(database_url=None, verbose=True)

    assert calls == [("head", "postgresql+asyncpg://user:pass@localhost/upnext", True)]


def test_ensure_database_schema_ready_exits_when_migration_declined(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server_module,
        "_resolve_effective_database_url",
        lambda _database_url: "postgresql+asyncpg://user:pass@localhost/upnext",
    )

    async def fake_missing_tables(_database_url: str) -> list[str]:
        return ["job_history"]

    monkeypatch.setattr(
        server_module, "_get_missing_required_tables", fake_missing_tables
    )
    monkeypatch.setattr(server_module.typer, "confirm", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(server_module, "warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server_module, "dim", lambda *_args, **_kwargs: None)

    with pytest.raises(typer.Exit) as exc:
        _ensure_database_schema_ready(database_url=None, verbose=False)

    assert exc.value.exit_code == 0


def test_resolve_alembic_config_fails_when_no_sources(monkeypatch) -> None:
    errors: list[str] = []

    monkeypatch.setattr(server_module, "_find_server_root_dir", lambda: None)
    monkeypatch.setattr(server_module, "_find_packaged_alembic_paths", lambda: None)
    monkeypatch.setattr(
        server_module,
        "error_panel",
        lambda message, **_kwargs: errors.append(str(message)),
    )

    with pytest.raises(typer.Exit) as exc:
        with _resolve_alembic_config():
            pass

    assert exc.value.exit_code == 1
    assert errors
    assert "Could not locate server migration files." in errors[0]
