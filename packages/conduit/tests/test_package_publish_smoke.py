from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_PACKAGES = ("shared", "conduit", "server")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _require_package_smoke_enabled() -> None:
    if os.getenv("CONDUIT_RUN_PACKAGE_SMOKE") != "1":
        pytest.skip("Set CONDUIT_RUN_PACKAGE_SMOKE=1 to run package publish smoke tests.")
    if shutil.which("uv") is None:
        pytest.skip("uv is required for package smoke tests.")


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_all(dist_dir: Path) -> None:
    root = _repo_root()
    dist_dir.mkdir(parents=True, exist_ok=True)
    for package_name in _PACKAGES:
        _run(
            [
                "uv",
                "build",
                str(root / "packages" / package_name),
                "--out-dir",
                str(dist_dir),
            ],
            cwd=root,
        )


def _create_venv(venv_dir: Path) -> Path:
    _run(["uv", "venv", str(venv_dir)])
    python_bin = venv_dir / "bin" / "python"
    assert python_bin.exists()
    return python_bin


def _assert_all_modules_importable(python_bin: Path) -> None:
    _run(
        [
            str(python_bin),
            "-c",
            "import conduit,server,shared; print(conduit.__name__, server.__name__, shared.__name__)",
        ]
    )


def _assert_conduit_cli_entrypoint(venv_python: Path) -> None:
    conduit_bin = venv_python.parent / "conduit"
    assert conduit_bin.exists(), "conduit console script was not installed"
    _run([str(conduit_bin), "--help"])


def test_build_produces_wheel_and_sdist_for_all_packages(tmp_path: Path) -> None:
    _require_package_smoke_enabled()
    dist_dir = tmp_path / "dist"
    _build_all(dist_dir)

    for package_name in _PACKAGES:
        wheels = list(dist_dir.glob(f"{package_name}-*.whl"))
        sdists = list(dist_dir.glob(f"{package_name}-*.tar.gz"))
        assert wheels, f"Missing wheel for {package_name}"
        assert sdists, f"Missing sdist for {package_name}"


def test_install_from_built_wheels_in_clean_venv(tmp_path: Path) -> None:
    _require_package_smoke_enabled()
    dist_dir = tmp_path / "dist"
    _build_all(dist_dir)

    python_bin = _create_venv(tmp_path / "venv-wheel")
    wheel_paths = sorted(dist_dir.glob("*.whl"))
    assert wheel_paths

    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python_bin),
            *[str(path) for path in wheel_paths],
        ]
    )
    _assert_all_modules_importable(python_bin)
    _assert_conduit_cli_entrypoint(python_bin)


def test_install_from_built_sdists_in_clean_venv(tmp_path: Path) -> None:
    _require_package_smoke_enabled()
    dist_dir = tmp_path / "dist"
    _build_all(dist_dir)

    python_bin = _create_venv(tmp_path / "venv-sdist")
    sdist_paths = sorted(dist_dir.glob("*.tar.gz"))
    assert sdist_paths

    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python_bin),
            *[str(path) for path in sdist_paths],
        ]
    )
    _assert_all_modules_importable(python_bin)
