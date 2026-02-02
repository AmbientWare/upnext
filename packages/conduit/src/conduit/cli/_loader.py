"""Module loader utilities."""

import importlib.util
import sys
from pathlib import Path

import typer

from conduit.cli._console import error
from conduit.sdk.api import Api
from conduit.sdk.worker import Worker


def import_file(file_path: str) -> object:
    """Import a Python file and return the module."""
    path = Path(file_path).resolve()

    if not path.exists():
        error(f"File not found: {file_path}")
        raise typer.Exit(1)

    if path.suffix != ".py":
        error(f"Not a Python file: {file_path}")
        raise typer.Exit(1)

    # Add parent directory to path so imports work
    parent_dir = str(path.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    # Also add cwd if different
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    # Import the file as a module
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        error(f"Could not load: {file_path}")
        raise typer.Exit(1)

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


def discover_objects(files: list[str]) -> tuple[list[Api], list[Worker]]:
    """Import files and discover Api/Worker objects."""

    apis: list[Api] = []
    workers: list[Worker] = []

    for file_path in files:
        module = import_file(file_path)

        for name in dir(module):
            if name.startswith("_"):
                continue

            obj = getattr(module, name)
            if isinstance(obj, Api):
                apis.append(obj)
            elif isinstance(obj, Worker):
                workers.append(obj)

    return apis, workers
