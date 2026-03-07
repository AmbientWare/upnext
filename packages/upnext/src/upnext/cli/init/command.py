"""Command entrypoint for `upnext init`."""

from __future__ import annotations

import typer

from upnext.cli._console import error, error_panel, nl
from upnext.cli.init.discovery import discover_components
from upnext.cli.init.paths import (
    relative_to_root,
    resolve_pyproject,
    validate_entrypoint,
)
from upnext.cli.init.prompts import (
    configure_advanced_features,
    resolve_linux_packages,
    resolve_python_version,
)
from upnext.cli.init.render import build_config_data, write_config
from upnext.cli.init.view import InitView

CONFIG_FILE_NAME = "upnext.yaml"


def init(
    entrypoint: str = typer.Argument(..., help="Python entrypoint file to deploy"),
    pyproject: str | None = typer.Option(
        None,
        "--pyproject",
        help="Path to pyproject.toml to use for the deployment build",
    ),
    python_version: str | None = typer.Option(
        None,
        "--python-version",
        help="Python version to write to upnext.yaml (for example 3.12)",
    ),
    linux_package: list[str] | None = typer.Option(
        None,
        "--linux-package",
        help="Additional Linux package to install during build (repeatable)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing upnext.yaml",
    ),
) -> None:
    """
    Initialize hosted deploy configuration for an UpNext entrypoint.

    Examples:
        upnext init service.py
        upnext init app/service.py --pyproject pyproject.toml
        upnext init app/service.py --python-version 3.12 --linux-package ffmpeg
    """
    entrypoint_path = validate_entrypoint(entrypoint)
    pyproject_path, repo_root = resolve_pyproject(
        entrypoint_path=entrypoint_path,
        pyproject=pyproject,
    )

    try:
        entrypoint_path.relative_to(repo_root)
    except ValueError:
        error("Entrypoint must be inside the repository root")
        raise typer.Exit(1) from None

    config_path = repo_root / CONFIG_FILE_NAME
    if config_path.exists() and not force:
        error_panel(
            f"{CONFIG_FILE_NAME} already exists. Re-run with --force to overwrite.",
            title="Configuration exists",
        )
        raise typer.Exit(1)

    view = InitView()
    entrypoint_rel = relative_to_root(entrypoint_path, repo_root)
    pyproject_rel = relative_to_root(pyproject_path, repo_root)
    view.show_discovery_summary(
        entrypoint=entrypoint_rel,
        repo_root=".",
        pyproject=pyproject_rel,
        config_path=CONFIG_FILE_NAME,
        overwrite=force,
    )

    resolved_python_version = resolve_python_version(
        pyproject_path=pyproject_path,
        explicit_version=python_version,
    )
    resolved_linux_packages = resolve_linux_packages(linux_package)
    nl()
    discovered_apis, worker_names, discovery_succeeded = discover_components(
        entrypoint_path
    )
    api_names = [api.name for api in discovered_apis]
    view.show_build_configuration(
        python_version=resolved_python_version,
        linux_packages=resolved_linux_packages,
    )
    view.show_component_summary(
        api_names=api_names,
        worker_names=worker_names,
        discovery_succeeded=discovery_succeeded,
    )
    api_configs, worker_configs = configure_advanced_features(
        discovered_apis,
        worker_names,
        view=view,
    )

    config_data = build_config_data(
        entrypoint_path=entrypoint_path,
        pyproject_path=pyproject_path,
        repo_root=repo_root,
        python_version=resolved_python_version,
        linux_packages=resolved_linux_packages,
        api_configs=api_configs,
        worker_configs=worker_configs,
    )
    write_config(config_path=config_path, config_data=config_data)

    view.show_success(
        config_path=CONFIG_FILE_NAME,
        entrypoint=entrypoint_rel,
        pyproject=pyproject_rel,
        python_version=resolved_python_version,
        linux_packages=resolved_linux_packages,
        api_count=len(api_configs),
        worker_count=len(worker_configs),
    )
