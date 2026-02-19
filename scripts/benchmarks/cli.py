from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import asdict
from typing import Any

from .models import (
    BenchmarkConfig,
    BenchmarkProfile,
    BenchmarkResult,
    SUPPORTED_FRAMEWORKS,
    SUPPORTED_PROFILES,
)
from .orchestrator import BenchmarkOrchestrator, BenchmarkRunSettings
from .reporting import json_payload, print_raw_runs, print_summary_table, summarize_framework_runs
from .runners import ensure_redis, parse_frameworks, run_single_framework
from .subprocess_client import (
    JSON_END_MARKER,
    JSON_START_MARKER,
    SubprocessBenchmarkClient,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-framework Redis queue benchmark for upnext/celery/dramatiq. "
            "Defaults are tuned for a fair, reproducible single-command run."
        )
    )
    parser.add_argument(
        "--framework",
        action="append",
        help=(
            "Framework(s) to run. Repeat flag or use comma list. "
            f"Default: {', '.join(SUPPORTED_FRAMEWORKS)}"
        ),
    )
    parser.add_argument(
        "--single-framework",
        choices=SUPPORTED_FRAMEWORKS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument(
        "--profile",
        type=BenchmarkProfile,
        choices=SUPPORTED_PROFILES,
        default=BenchmarkProfile.THROUGHPUT,
        help=(
            "Benchmark profile. 'throughput' maximizes jobs/s, "
            "'durability' favors stricter delivery semantics."
        ),
    )

    parser.add_argument("--jobs", type=int, default=10000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--payload-bytes", type=int, default=256)
    parser.add_argument(
        "--producer-concurrency",
        type=int,
        default=0,
        help="Submitter parallelism. 0 = same as --concurrency.",
    )
    parser.add_argument(
        "--consumer-prefetch",
        type=int,
        default=0,
        help=(
            "Target reserved/inbox messages for Celery consumers. "
            "Mapped to Celery prefetch multiplier. "
            "0 = profile default."
        ),
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--redis-url",
        default=os.getenv("UPNEXT_PERF_REDIS_URL", "redis://127.0.0.1:6379/15"),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    parser.add_argument(
        "--show-runs",
        action="store_true",
        help="Print per-run details in addition to framework summary.",
    )
    parser.add_argument(
        "--fail-on-non-ok",
        action="store_true",
        help="Exit with status 1 if any measured run is not status=ok.",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: implies --json and --fail-on-non-ok.",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.jobs <= 0:
        parser.error("--jobs must be > 0")
    if args.concurrency <= 0:
        parser.error("--concurrency must be > 0")
    if args.payload_bytes <= 0:
        parser.error("--payload-bytes must be > 0")
    if args.producer_concurrency < 0:
        parser.error("--producer-concurrency must be >= 0")
    if args.consumer_prefetch < 0:
        parser.error("--consumer-prefetch must be >= 0")
    if args.repeats <= 0:
        parser.error("--repeats must be > 0")
    if args.warmups < 0:
        parser.error("--warmups must be >= 0")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be > 0")


def _effective_producer_concurrency(args: argparse.Namespace) -> int:
    return args.producer_concurrency if args.producer_concurrency > 0 else args.concurrency


def _resolve_consumer_prefetch(
    *,
    profile: BenchmarkProfile,
    consumer_prefetch: int,
    concurrency: int,
) -> int:
    if consumer_prefetch > 0:
        return consumer_prefetch
    if profile == BenchmarkProfile.DURABILITY:
        return 1
    return concurrency


def _to_config(
    args: argparse.Namespace,
    frameworks: list[str],
    producer_concurrency: int,
    *,
    consumer_prefetch: int,
) -> dict[str, Any]:
    return {
        "profile": args.profile.value,
        "frameworks": frameworks,
        "jobs": args.jobs,
        "concurrency": args.concurrency,
        "payload_bytes": args.payload_bytes,
        "producer_concurrency": producer_concurrency,
        "consumer_prefetch": consumer_prefetch,
        "repeats": args.repeats,
        "warmups": args.warmups,
        "timeout_seconds": args.timeout_seconds,
        "redis_url": args.redis_url,
    }


def _single_framework_mode(
    args: argparse.Namespace,
    producer_concurrency: int,
    *,
    consumer_prefetch: int,
) -> int:
    cfg = BenchmarkConfig(
        framework=args.single_framework,
        profile=args.profile,
        jobs=args.jobs,
        concurrency=args.concurrency,
        payload_bytes=args.payload_bytes,
        producer_concurrency=producer_concurrency,
        consumer_prefetch=consumer_prefetch,
        timeout_seconds=args.timeout_seconds,
        redis_url=args.redis_url,
        run_id=args.run_id or uuid.uuid4().hex[:10],
    )
    result = run_single_framework(cfg)

    print(JSON_START_MARKER)
    print(json.dumps(asdict(result), sort_keys=True))
    print(JSON_END_MARKER)
    return 0 if result.status == "ok" or not args.fail_on_non_ok else 1


def _normal_mode(
    args: argparse.Namespace,
    frameworks: list[str],
    producer_concurrency: int,
    *,
    consumer_prefetch: int,
) -> int:
    settings = BenchmarkRunSettings(
        profile=args.profile,
        jobs=args.jobs,
        concurrency=args.concurrency,
        payload_bytes=args.payload_bytes,
        producer_concurrency=producer_concurrency,
        consumer_prefetch=consumer_prefetch,
        timeout_seconds=args.timeout_seconds,
        redis_url=args.redis_url,
        repeats=args.repeats,
        warmups=args.warmups,
    )
    client = SubprocessBenchmarkClient()
    orchestrator = BenchmarkOrchestrator(client=client)

    warmups_by_framework: dict[str, list[BenchmarkResult]] = {}
    runs_by_framework: dict[str, list[BenchmarkResult]] = {}
    summaries = []
    for framework in frameworks:
        warmups, measured = orchestrator.run_framework(framework, settings=settings)
        warmups_by_framework[framework] = warmups
        runs_by_framework[framework] = measured
        summaries.append(
            summarize_framework_runs(framework, measured, requested_runs=settings.repeats)
        )

    if args.json:
        payload = json_payload(
            config=_to_config(
                args,
                frameworks,
                producer_concurrency,
                consumer_prefetch=consumer_prefetch,
            ),
            runs_by_framework=runs_by_framework,
            summaries=summaries,
        )
        payload["warmups"] = {
            framework: [asdict(run) for run in runs]
            for framework, runs in warmups_by_framework.items()
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_summary_table(summaries)
        if args.warmups > 0:
            print(f"\nWarmups per framework: {args.warmups} (excluded from summary).")
        if args.show_runs:
            for framework in frameworks:
                print_raw_runs(framework, runs_by_framework[framework])

    any_non_ok = any(
        run.status != "ok"
        for framework_runs in runs_by_framework.values()
        for run in framework_runs
    )
    return 1 if args.fail_on_non_ok and any_non_ok else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.ci:
        args.json = True
        args.fail_on_non_ok = True
    _validate_args(parser, args)

    producer_concurrency = _effective_producer_concurrency(args)
    consumer_prefetch = _resolve_consumer_prefetch(
        profile=args.profile,
        consumer_prefetch=args.consumer_prefetch,
        concurrency=args.concurrency,
    )
    frameworks = (
        [args.single_framework] if args.single_framework else parse_frameworks(args.framework)
    )

    # Fail fast before scheduling warmups/repeats.
    try:
        ensure_redis(args.redis_url)
    except Exception as exc:
        if args.json:
            payload = {
                "config": _to_config(
                    args,
                    frameworks,
                    producer_concurrency,
                    consumer_prefetch=consumer_prefetch,
                ),
                "error": f"Redis unavailable ({args.redis_url}): {exc}",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Redis unavailable ({args.redis_url}): {exc}")
        return 2

    if args.single_framework:
        return _single_framework_mode(
            args,
            producer_concurrency,
            consumer_prefetch=consumer_prefetch,
        )
    return _normal_mode(
        args,
        frameworks,
        producer_concurrency,
        consumer_prefetch=consumer_prefetch,
    )


if __name__ == "__main__":
    raise SystemExit(main())
