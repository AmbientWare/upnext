"""Path and pyproject resolution helpers for `upnext init`."""

from __future__ import annotations

from pathlib import Path

import typer

from upnext.cli._console import error, info


def validate_entrypoint(entrypoint: str) -> Path:
    path = Path(entrypoint).expanduser().resolve()
    if not path.exists():
        error(f"File not found: {entrypoint}")
        raise typer.Exit(1)
    if path.suffix != ".py":
        error(f"Not a Python file: {entrypoint}")
        raise typer.Exit(1)
    return path


def find_git_repo_root(start: Path) -> Path | None:
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def find_nearest_pyproject(start: Path, stop_at: Path | None = None) -> Path | None:
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            return pyproject
        if stop_at is not None and candidate == stop_at:
            break
    return None


def find_repo_pyprojects(repo_root: Path) -> list[Path]:
    return sorted(
        path
        for path in repo_root.rglob("pyproject.toml")
        if path.is_file() and ".git" not in path.parts
    )


def resolve_repo_root(entrypoint_path: Path, pyproject_path: Path) -> Path:
    return find_git_repo_root(entrypoint_path) or pyproject_path.parent


def relative_to_root(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def select_pyproject_from_candidates(
    candidates: list[Path],
    repo_root: Path,
) -> Path:
    info("Multiple pyproject.toml files found. Select one:")
    for index, candidate in enumerate(candidates, start=1):
        typer.echo(f"  {index}. {relative_to_root(candidate, repo_root)}")

    selection = typer.prompt("Pyproject number", type=int)
    if selection < 1 or selection > len(candidates):
        error("Invalid pyproject selection")
        raise typer.Exit(1)
    return candidates[selection - 1]


def prompt_for_pyproject(repo_root: Path | None) -> Path:
    value = typer.prompt("Path to pyproject.toml")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        error(f"pyproject.toml not found: {value}")
        raise typer.Exit(1)
    if path.name != "pyproject.toml":
        error(f"Not a pyproject.toml file: {value}")
        raise typer.Exit(1)
    if repo_root is not None:
        try:
            path.relative_to(repo_root)
        except ValueError:
            error("Selected pyproject.toml must be inside the repository root")
            raise typer.Exit(1) from None
    return path


def resolve_pyproject(
    *,
    entrypoint_path: Path,
    pyproject: str | None,
) -> tuple[Path, Path]:
    git_root = find_git_repo_root(entrypoint_path)

    if pyproject:
        selected = Path(pyproject).expanduser().resolve()
        if not selected.is_file():
            error(f"pyproject.toml not found: {pyproject}")
            raise typer.Exit(1)
        if selected.name != "pyproject.toml":
            error(f"Not a pyproject.toml file: {pyproject}")
            raise typer.Exit(1)
        if git_root is not None:
            try:
                selected.relative_to(git_root)
            except ValueError:
                error("Selected pyproject.toml must be inside the repository root")
                raise typer.Exit(1) from None
        return selected, (git_root or selected.parent)

    nearest = find_nearest_pyproject(entrypoint_path, stop_at=git_root)
    if nearest is not None:
        return nearest, resolve_repo_root(entrypoint_path, nearest)

    if git_root is not None:
        candidates = find_repo_pyprojects(git_root)
        if len(candidates) == 1:
            return candidates[0], git_root
        if len(candidates) > 1:
            return select_pyproject_from_candidates(candidates, git_root), git_root

    selected = prompt_for_pyproject(git_root)
    return selected, (git_root or selected.parent)
