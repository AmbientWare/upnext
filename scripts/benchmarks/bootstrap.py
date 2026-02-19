from __future__ import annotations

import sys
from pathlib import Path


def bootstrap_workspace_imports() -> None:
    """Ensure workspace packages are importable when running benchmarks directly."""
    root = Path(__file__).resolve().parents[2]
    candidates = (
        root / "packages" / "upnext" / "src",
        root / "packages" / "server" / "src",
        root / "packages" / "shared" / "src",
    )
    for path in candidates:
        raw = str(path)
        if raw not in sys.path:
            sys.path.insert(0, raw)
