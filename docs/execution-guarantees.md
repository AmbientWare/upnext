# Execution Guarantees

This document defines the runtime contract for enqueue/dequeue/retry/cancel behavior.

## Delivery Model

- Jobs are delivered with **at-least-once** semantics.
- A job that was dequeued but not acknowledged (for example, worker crash) may be reclaimed and delivered again.
- Handlers should be idempotent for safe duplicate execution.

## Queue + State Transitions

- `enqueue`: persists job payload and makes it runnable immediately or at a scheduled time.
- `dequeue`: moves a queued job into active processing.
- `finish`: writes a terminal result (`complete`, `failed`, `cancelled`) and removes active queue state.
- `retry`: re-queues a non-terminal job (immediate or delayed) with updated attempt state.
- `cancel`: marks a non-terminal job cancelled and prevents queued execution.

## Deduplication / Idempotency Key

- If a job key is supplied at enqueue time, duplicate keys are rejected while the key is active.
- Dedup entries are released when the job reaches terminal state (or is cancelled).
- External callers can supply stable keys via `TaskHandle.submit_idempotent(...)`, `TaskHandle.wait_idempotent(...)`, and `EventHandle.send_idempotent(...)`.
- Manual retries restore dedupe membership before re-enqueueing; retries with an already-active key are rejected with `409`.

## Pause / Resume Behavior

- Paused functions are not dispatched for execution.
- Jobs queued while paused remain durable in queue storage.
- On resume, queued jobs continue processing normally.

## Dead-Letter Behavior

- Terminal failed jobs are appended to a per-function dead-letter stream (`...:fn:{function}:dlq`) with failure reason and timestamp.
- Dead-letter records can be listed and replayed through queue APIs.
- Replay enqueues a fresh job payload and removes the replayed dead-letter record only on successful enqueue.

## Source of Truth Tests

These tests enforce the contract:

- `packages/upnext/tests/test_execution_guarantees_contract.py`
- `packages/upnext/tests/test_redis_queue.py`
- `packages/upnext/tests/test_job_processor.py`
- `packages/server/tests/test_routes.py`
