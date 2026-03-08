"""Interactive prompt helpers for `upnext init`."""

from __future__ import annotations

import re
import sys
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from upnext.cli._console import error, info, nl
from upnext.cli.init.discovery import DiscoveredApi
from upnext.cli.init.view import InitView

API_CONFIG_FIELDS = (
    "port",
    "domain",
    "min_replicas",
    "max_replicas",
    "target_concurrency",
    "cpu_request",
    "cpu_limit",
    "memory_request",
    "memory_limit",
)
WORKER_CONFIG_FIELDS = (
    "min_replicas",
    "max_replicas",
    "cpu_request",
    "cpu_limit",
    "memory_request",
    "memory_limit",
)


class ScaleTargetType(StrEnum):
    QUEUE = "queue"
    CPU = "cpu"
    MEMORY = "memory"


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


def build_api_config(discovered: DiscoveredApi) -> dict[str, Any]:
    config: dict[str, Any] = {field: None for field in API_CONFIG_FIELDS}
    config["port"] = discovered.port
    return config


def build_worker_config() -> dict[str, str | None]:
    return {field: None for field in WORKER_CONFIG_FIELDS}


def prompt_scale_target(worker_name: str) -> dict[str, Any] | None:
    scale_type = typer.prompt(
        f"  Scale target for '{worker_name}' (queue/cpu/memory, or press Enter to skip)",
        default="",
        show_default=False,
    ).strip().lower()

    if scale_type not in ScaleTargetType._value2member_map_:
        return None

    if scale_type == ScaleTargetType.QUEUE:
        jobs_raw = prompt_optional_value("    Jobs per replica before scaling up (default: 2, set to match worker concurrency)")
        result: dict[str, Any] = {"type": "queue"}
        if jobs_raw:
            result["jobs_per_replica"] = int(jobs_raw)
        return result

    # cpu or memory
    threshold_raw = prompt_optional_value(
        f"    {scale_type.upper()} utilization % threshold before scaling up (default: 80)"
    )
    result = {"type": scale_type}
    if threshold_raw:
        result["threshold"] = int(threshold_raw)
    return result


def configure_advanced_features(
    discovered_apis: list[DiscoveredApi],
    worker_names: list[str],
    *,
    view: InitView | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str | None]]]:
    apis = {api.name: build_api_config(api) for api in discovered_apis}
    workers = {name: build_worker_config() for name in worker_names}

    if not discovered_apis and not worker_names:
        return apis, workers

    if view is not None:
        view.show_advanced_section_intro()

    if not typer.confirm("Configure advanced features?", default=False):
        nl()
        return apis, workers

    nl()

    for api in discovered_apis:
        info(f"Configuring API '{api.name}'")
        apis[api.name]["domain"] = prompt_optional_value("  Domain")
        apis[api.name]["min_replicas"] = prompt_optional_value("  Min replicas (0 = scale to zero, default: 0)")
        apis[api.name]["max_replicas"] = prompt_optional_value("  Max replicas (default: 2)")
        apis[api.name]["target_concurrency"] = prompt_optional_value("  Target concurrent requests per replica before scaling up (default: 100)")
        apis[api.name]["cpu_request"] = prompt_optional_value("  CPU request")
        apis[api.name]["cpu_limit"] = prompt_optional_value("  CPU limit")
        apis[api.name]["memory_request"] = prompt_optional_value("  Memory request")
        apis[api.name]["memory_limit"] = prompt_optional_value("  Memory limit")

    for name in worker_names:
        info(f"Configuring worker '{name}'")
        workers[name]["min_replicas"] = prompt_optional_value("  Min replicas (0 = scale to zero, default: 0)")
        workers[name]["max_replicas"] = prompt_optional_value("  Max replicas (default: 2)")
        workers[name]["cpu_request"] = prompt_optional_value("  CPU request (cores)")
        workers[name]["cpu_limit"] = prompt_optional_value("  CPU limit (cores)")
        workers[name]["memory_request"] = prompt_optional_value("  Memory request (GB)")
        workers[name]["memory_limit"] = prompt_optional_value("  Memory limit (GB)")
        scale_target = prompt_scale_target(name)
        if scale_target:
            workers[name]["scale_target"] = scale_target

    # add final newline
    nl()

    return apis, workers
