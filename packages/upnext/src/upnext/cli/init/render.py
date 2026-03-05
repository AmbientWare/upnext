"""Config data construction and YAML rendering for `upnext init`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from upnext.cli.init.paths import relative_to_root


def render_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def render_yaml_lines(value: Any, *, indent: int = 0) -> list[str]:
    prefix = " " * indent

    if isinstance(value, Mapping):
        if not value:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        for key, nested in value.items():
            if isinstance(nested, Mapping):
                if nested:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(render_yaml_lines(nested, indent=indent + 2))
                else:
                    lines.append(f"{prefix}{key}: {{}}")
            elif isinstance(nested, list):
                if nested:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(render_yaml_lines(nested, indent=indent + 2))
                else:
                    lines.append(f"{prefix}{key}: []")
            else:
                lines.append(f"{prefix}{key}: {render_scalar(nested)}")
        return lines

    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                lines.append(f"{prefix}-")
                lines.extend(render_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {render_scalar(item)}")
        return lines

    return [f"{prefix}{render_scalar(value)}"]


def build_config_data(
    *,
    entrypoint_path: Path,
    pyproject_path: Path,
    repo_root: Path,
    python_version: str,
    linux_packages: list[str],
    api_configs: dict[str, dict[str, str | None]],
    worker_configs: dict[str, dict[str, str | None]],
) -> dict[str, Any]:
    return {
        "version": 1,
        "deploy": {
            "entrypoint": relative_to_root(entrypoint_path, repo_root),
            "pyproject": relative_to_root(pyproject_path, repo_root),
            "python_version": python_version,
            "linux_packages": linux_packages,
        },
        "apis": api_configs,
        "workers": worker_configs,
    }


def render_yaml_document(config_data: dict[str, Any]) -> str:
    return "\n".join(render_yaml_lines(config_data)) + "\n"


def write_config(*, config_path: Path, config_data: dict[str, Any]) -> None:
    config_path.write_text(render_yaml_document(config_data), encoding="utf-8")
