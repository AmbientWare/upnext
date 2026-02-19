from __future__ import annotations

import json
from pathlib import Path
from typing import Any

JSON_START_MARKER = "===BENCHMARK_JSON_START==="
JSON_END_MARKER = "===BENCHMARK_JSON_END==="


def emit_marked_json(payload: dict[str, Any]) -> None:
    print(JSON_START_MARKER)
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(JSON_END_MARKER)


def extract_marked_json(text: str) -> dict[str, Any]:
    start = text.find(JSON_START_MARKER)
    end = text.find(JSON_END_MARKER)
    if start < 0 or end < 0 or end <= start:
        raise ValueError("Benchmark output markers missing")
    payload = text[start + len(JSON_START_MARKER) : end].strip()
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise TypeError("Expected JSON object payload")
    return raw


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def load_matrix_payloads(results_dir: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    seen_configs: set[str] = set()

    for path in sorted(results_dir.rglob("*")):
        if not path.is_file():
            continue

        payload: dict[str, Any] | None = None
        if path.suffix == ".json":
            payload = _load_json_file(path)
        elif path.suffix in (".txt", ".log"):
            try:
                payload = extract_marked_json(path.read_text())
            except Exception:
                payload = None

        if not payload:
            continue
        if payload.get("kind") != "benchmark-matrix":
            continue

        config = payload.get("config", {})
        config_key = json.dumps(config, sort_keys=True)
        if config_key in seen_configs:
            continue
        seen_configs.add(config_key)
        payloads.append(payload)

    return payloads
