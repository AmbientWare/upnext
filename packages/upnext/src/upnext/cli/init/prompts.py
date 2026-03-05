"""Interactive prompt helpers for `upnext init`."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import typer

from upnext.cli._console import error, info, nl
from upnext.cli.init.view import InitView

API_CONFIG_FIELDS = (
    "domain",
    "replicas",
    "cpu_request",
    "cpu_limit",
    "memory_request",
    "memory_limit",
)
WORKER_CONFIG_FIELDS = (
    "replicas",
    "cpu_request",
    "cpu_limit",
    "memory_request",
    "memory_limit",
)


def load_pyproject_data(pyproject_path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        error(f"Invalid pyproject.toml: {exc}")
        raise typer.Exit(1) from exc


def derive_python_version_from_requires_python(specifier: str | None) -> str | None:
    if not specifier:
        return None
    match = re.search(r"(\d+)\.(\d+)", specifier)
    if match is None:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def normalize_python_version(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"\d+\.\d+", normalized):
        error("Python version must use MAJOR.MINOR format, for example 3.12")
        raise typer.Exit(1)
    return normalized


def resolve_python_version(
    *,
    pyproject_path: Path,
    explicit_version: str | None,
) -> str:
    if explicit_version:
        return normalize_python_version(explicit_version)

    pyproject_data = load_pyproject_data(pyproject_path)
    project = pyproject_data.get("project", {})
    requires_python = (
        project.get("requires-python") if isinstance(project, dict) else None
    )
    derived = derive_python_version_from_requires_python(requires_python)
    default_version = derived or f"{sys.version_info.major}.{sys.version_info.minor}"
    chosen = typer.prompt("Python version", default=default_version)
    return normalize_python_version(chosen)


def normalize_linux_packages(values: list[str]) -> list[str]:
    packages: list[str] = []
    for value in values:
        candidate = value.strip()
        if candidate and candidate not in packages:
            packages.append(candidate)
    return packages


def resolve_linux_packages(explicit_packages: list[str] | None) -> list[str]:
    if explicit_packages:
        return normalize_linux_packages(explicit_packages)

    raw = typer.prompt(
        "Additional Linux packages (comma-separated, optional)",
        default="",
        show_default=False,
    )
    return normalize_linux_packages(raw.split(","))


def prompt_optional_value(label: str) -> str | None:
    value = typer.prompt(label, default="", show_default=False).strip()
    return value or None


def build_api_config() -> dict[str, str | None]:
    return {field: None for field in API_CONFIG_FIELDS}


def build_worker_config() -> dict[str, str | None]:
    return {field: None for field in WORKER_CONFIG_FIELDS}


def configure_advanced_features(
    api_names: list[str],
    worker_names: list[str],
    *,
    view: InitView | None = None,
) -> tuple[dict[str, dict[str, str | None]], dict[str, dict[str, str | None]]]:
    apis = {name: build_api_config() for name in api_names}
    workers = {name: build_worker_config() for name in worker_names}

    if not api_names and not worker_names:
        return apis, workers

    if view is not None:
        view.show_advanced_section_intro()

    if not typer.confirm("Configure advanced features?", default=False):
        nl()
        return apis, workers

    nl()

    for name in api_names:
        info(f"Configuring API '{name}'")
        apis[name]["domain"] = prompt_optional_value("  Domain")
        apis[name]["replicas"] = prompt_optional_value("  Replicas")
        apis[name]["cpu_request"] = prompt_optional_value("  CPU request")
        apis[name]["cpu_limit"] = prompt_optional_value("  CPU limit")
        apis[name]["memory_request"] = prompt_optional_value("  Memory request")
        apis[name]["memory_limit"] = prompt_optional_value("  Memory limit")

    for name in worker_names:
        info(f"Configuring worker '{name}'")
        workers[name]["replicas"] = prompt_optional_value("  Replicas")
        workers[name]["cpu_request"] = prompt_optional_value("  CPU request")
        workers[name]["cpu_limit"] = prompt_optional_value("  CPU limit")
        workers[name]["memory_request"] = prompt_optional_value("  Memory request")
        workers[name]["memory_limit"] = prompt_optional_value("  Memory limit")

    # add final newline
    nl()

    return apis, workers
