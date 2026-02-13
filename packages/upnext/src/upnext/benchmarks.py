from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Run the workspace benchmark harness from the `benchmarks` console script."""
    workspace_root = Path(__file__).resolve().parents[4]
    root_str = str(workspace_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from scripts.benchmarks.cli import main as benchmark_main

    return benchmark_main()
