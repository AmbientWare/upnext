from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .config import (
    MatrixSettings,
    parse_frameworks,
    resolve_consumer_prefetch,
    resolve_workload_parameters,
    validate_common_numeric_args,
)
from .engine import MatrixEngine
from .io import emit_marked_json, load_matrix_payloads, write_json_file
from .models import (
    SCHEMA_VERSION,
    BenchmarkConfig,
    BenchmarkWorkload,
    SUPPORTED_WORKLOADS,
)
from .report_json import matrix_json_payload
from .report_markdown import build_markdown_report
from .reporting import print_matrix_report, print_single_result
from .subprocess_client import SubprocessBenchmarkClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "UpNext benchmark suite focused on realistic sustained load and burst backpressure."
        )
    )
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Run a single benchmark sample")
    _add_common_case_args(run)
    run.add_argument("--framework", required=True)
    run.add_argument("--run-id", default="")
    run.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    run.add_argument("--output-json", default="", help="Write JSON payload to file")
    run.add_argument("--fail-on-non-ok", action="store_true")

    matrix = subparsers.add_parser(
        "matrix",
        help="Run warmup/measured rounds across frameworks with fair interleaving",
    )
    _add_common_case_args(matrix)
    matrix.add_argument("--framework", action="append")
    matrix.add_argument("--repeats", type=int, default=3)
    matrix.add_argument("--warmups", type=int, default=1)
    matrix.add_argument("--seed", type=int, default=42)
    matrix.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    matrix.add_argument("--output-json", default="", help="Write JSON payload to file")
    matrix.add_argument("--show-runs", action="store_true")
    matrix.add_argument("--fail-on-non-ok", action="store_true")
    matrix.add_argument("--ci", action="store_true", help="Set --json and --fail-on-non-ok")

    summarize = subparsers.add_parser(
        "summarize",
        help="Summarize benchmark artifacts into markdown or JSON",
    )
    summarize.add_argument("--input", required=True, help="Artifacts directory")
    summarize.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
    )
    summarize.add_argument("--output", default="", help="Optional output file")

    doctor = subparsers.add_parser("doctor", help="Validate benchmark environment")
    doctor.add_argument(
        "--redis-url",
        default=os.getenv("UPNEXT_PERF_REDIS_URL", "redis://127.0.0.1:6379/15"),
    )
    doctor.add_argument("--framework", action="append")
    doctor.add_argument("--json", action="store_true")

    return parser


def _add_common_case_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workload",
        type=BenchmarkWorkload,
        choices=SUPPORTED_WORKLOADS,
        default=BenchmarkWorkload.SUSTAINED,
    )
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Used by sustained workload.",
    )
    parser.add_argument(
        "--arrival-rate",
        type=float,
        default=None,
        help="Target jobs/second for sustained workload.",
    )
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--payload-bytes", type=int, default=256)
    parser.add_argument(
        "--producer-concurrency",
        type=int,
        default=None,
        help="Submitter parallelism.",
    )
    parser.add_argument(
        "--consumer-prefetch",
        type=int,
        default=0,
        help="Consumer reserve depth target. 0 = auto.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument(
        "--redis-url",
        default=os.getenv("UPNEXT_PERF_REDIS_URL", "redis://127.0.0.1:6379/15"),
    )
    parser.add_argument("--queue-wait-sample-rate", type=float, default=0.10)
    parser.add_argument("--queue-wait-max-samples", type=int, default=5_000)


def _resolve_case_args(
    args: argparse.Namespace,
    *,
    repeats: int,
    warmups: int,
) -> tuple[int, int, int, int, float, float, float]:
    (
        jobs,
        concurrency,
        producer_concurrency,
        timeout_seconds,
        arrival_rate,
        duration_seconds,
    ) = resolve_workload_parameters(
        workload=args.workload,
        jobs=args.jobs,
        duration_seconds=args.duration_seconds,
        arrival_rate=args.arrival_rate,
        concurrency=args.concurrency,
        producer_concurrency=args.producer_concurrency,
        timeout_seconds=args.timeout_seconds,
    )
    consumer_prefetch = resolve_consumer_prefetch(
        consumer_prefetch=args.consumer_prefetch,
        concurrency=concurrency,
    )

    validate_common_numeric_args(
        workload=args.workload,
        jobs=jobs,
        concurrency=concurrency,
        payload_bytes=args.payload_bytes,
        producer_concurrency=producer_concurrency,
        consumer_prefetch=consumer_prefetch,
        timeout_seconds=timeout_seconds,
        arrival_rate=arrival_rate,
        duration_seconds=duration_seconds,
        repeats=repeats,
        warmups=warmups,
        queue_wait_sample_rate=args.queue_wait_sample_rate,
        queue_wait_max_samples=args.queue_wait_max_samples,
    )
    return (
        jobs,
        concurrency,
        producer_concurrency,
        consumer_prefetch,
        timeout_seconds,
        arrival_rate,
        duration_seconds,
    )


def _build_cfg_from_run_args(args: argparse.Namespace) -> BenchmarkConfig:
    (
        jobs,
        concurrency,
        producer_concurrency,
        consumer_prefetch,
        timeout_seconds,
        arrival_rate,
        duration_seconds,
    ) = _resolve_case_args(args, repeats=1, warmups=0)

    return BenchmarkConfig(
        framework=args.framework,
        workload=args.workload,
        jobs=jobs,
        concurrency=concurrency,
        payload_bytes=args.payload_bytes,
        producer_concurrency=producer_concurrency,
        consumer_prefetch=consumer_prefetch,
        timeout_seconds=timeout_seconds,
        redis_url=args.redis_url,
        run_id=args.run_id or uuid.uuid4().hex[:10],
        arrival_rate=arrival_rate,
        duration_seconds=duration_seconds,
        queue_wait_sample_rate=args.queue_wait_sample_rate,
        queue_wait_max_samples=args.queue_wait_max_samples,
    )


def _run_command(args: argparse.Namespace) -> int:
    from .runners import ensure_redis, run_single_framework

    cfg = _build_cfg_from_run_args(args)

    try:
        ensure_redis(cfg.redis_url)
    except Exception as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "kind": "benchmark-run",
            "config": cfg.runtime_config(),
            "error": f"Redis unavailable ({cfg.redis_url}): {exc}",
        }
        if args.output_json:
            write_json_file(Path(args.output_json), result)
        if args.json:
            emit_marked_json(result)
        else:
            print(result["error"])
        return 2

    result = run_single_framework(cfg)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "benchmark-run",
        "config": cfg.runtime_config(),
        "result": result.to_dict(),
    }

    if args.output_json:
        write_json_file(Path(args.output_json), payload)

    if args.json:
        emit_marked_json(payload)
    else:
        print_single_result(result)

    if args.fail_on_non_ok and result.status != "ok":
        return 1
    return 0


def _matrix_command(args: argparse.Namespace) -> int:
    from .runners import ensure_redis

    if args.ci:
        args.json = True
        args.fail_on_non_ok = True

    (
        jobs,
        concurrency,
        producer_concurrency,
        consumer_prefetch,
        timeout_seconds,
        arrival_rate,
        duration_seconds,
    ) = _resolve_case_args(args, repeats=args.repeats, warmups=args.warmups)
    frameworks = parse_frameworks(args.framework)

    try:
        ensure_redis(args.redis_url)
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "kind": "benchmark-matrix",
            "config": {
                "workload": args.workload.value,
                "frameworks": frameworks,
                "jobs": jobs,
                "concurrency": concurrency,
                "payload_bytes": args.payload_bytes,
                "producer_concurrency": producer_concurrency,
                "consumer_prefetch": consumer_prefetch,
                "timeout_seconds": timeout_seconds,
                "arrival_rate": arrival_rate,
                "duration_seconds": duration_seconds,
                "repeats": args.repeats,
                "warmups": args.warmups,
                "redis_url": args.redis_url,
                "seed": args.seed,
                "queue_wait_sample_rate": args.queue_wait_sample_rate,
                "queue_wait_max_samples": args.queue_wait_max_samples,
            },
            "error": f"Redis unavailable ({args.redis_url}): {exc}",
        }
        if args.output_json:
            write_json_file(Path(args.output_json), payload)
        if args.json:
            emit_marked_json(payload)
        else:
            print(payload["error"])
        return 2

    settings = MatrixSettings(
        workload=args.workload,
        frameworks=frameworks,
        jobs=jobs,
        concurrency=concurrency,
        payload_bytes=args.payload_bytes,
        producer_concurrency=producer_concurrency,
        consumer_prefetch=consumer_prefetch,
        timeout_seconds=timeout_seconds,
        arrival_rate=arrival_rate,
        duration_seconds=duration_seconds,
        repeats=args.repeats,
        warmups=args.warmups,
        redis_url=args.redis_url,
        seed=args.seed,
        queue_wait_sample_rate=args.queue_wait_sample_rate,
        queue_wait_max_samples=args.queue_wait_max_samples,
    )

    engine = MatrixEngine(client=SubprocessBenchmarkClient())
    execution = engine.run(settings)

    payload = matrix_json_payload(
        config={
            "workload": settings.workload.value,
            "frameworks": settings.frameworks,
            "jobs": settings.jobs,
            "concurrency": settings.concurrency,
            "payload_bytes": settings.payload_bytes,
            "producer_concurrency": settings.producer_concurrency,
            "consumer_prefetch": settings.consumer_prefetch,
            "timeout_seconds": settings.timeout_seconds,
            "arrival_rate": settings.arrival_rate,
            "duration_seconds": settings.duration_seconds,
            "repeats": settings.repeats,
            "warmups": settings.warmups,
            "redis_url": settings.redis_url,
            "seed": settings.seed,
            "queue_wait_sample_rate": settings.queue_wait_sample_rate,
            "queue_wait_max_samples": settings.queue_wait_max_samples,
        },
        warmups=execution.warmups,
        runs=execution.runs,
        summaries=execution.summaries,
    )

    if args.output_json:
        write_json_file(Path(args.output_json), payload)

    if args.json:
        emit_marked_json(payload)
    else:
        print_matrix_report(
            config=payload["config"],
            summaries=payload["summaries"],
            runs=execution.runs,
            show_runs=args.show_runs,
        )

    any_non_ok = any(record.result.status != "ok" for record in execution.runs)
    if args.fail_on_non_ok and any_non_ok:
        return 1
    return 0


def _summarize_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.is_dir():
        print(f"Not a directory: {input_path}")
        return 1

    payloads = load_matrix_payloads(input_path)

    if args.format == "markdown":
        text = build_markdown_report(payloads)
    else:
        json_payload = {
            "schema_version": SCHEMA_VERSION,
            "kind": "benchmark-summary",
            "payload_count": len(payloads),
            "payloads": payloads,
        }
        text = json.dumps(json_payload, indent=2, sort_keys=True)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + ("\n" if not text.endswith("\n") else ""))

    print(text)
    return 0


def _doctor_command(args: argparse.Namespace) -> int:
    from .preflight import check_framework_imports, check_redis

    frameworks = parse_frameworks(args.framework)
    redis_ok, redis_detail = check_redis(args.redis_url)
    imports = check_framework_imports(frameworks)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "benchmark-doctor",
        "redis": {"ok": redis_ok, "detail": redis_detail, "url": args.redis_url},
        "frameworks": imports,
    }

    if args.json:
        emit_marked_json(payload)
    else:
        redis_status = "ok" if redis_ok else "error"
        print(f"redis: {redis_status} ({redis_detail})")
        for framework in frameworks:
            fw = imports.get(framework, {})
            status = "ok" if fw.get("ok") else "error"
            print(f"{framework}: {status} ({fw.get('detail', 'unknown')})")

    all_frameworks_ok = all(bool(item.get("ok")) for item in imports.values())
    return 0 if redis_ok and all_frameworks_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "run":
            return _run_command(args)
        if args.command == "matrix":
            return _matrix_command(args)
        if args.command == "summarize":
            return _summarize_command(args)
        if args.command == "doctor":
            return _doctor_command(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
