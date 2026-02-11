import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from shared.models import Job

logger = logging.getLogger(__name__)


@dataclass
class Context:
    """
    Execution context passed to every job handler.

    Provides access to job metadata and methods for progress tracking,
    heartbeats, checkpointing, and event emission.

    Example:
        @task(retries=3)
        async def process_file(ctx: Context, file_path: str) -> dict:
            ctx.log.info(f"Processing {file_path}")

            for i, chunk in enumerate(read_chunks(file_path)):
                if ctx.is_cancelled:
                    return {"partial": True}

                process(chunk)
                ctx.set_progress(i / total_chunks)

            return {"processed": True}
    """

    # Identity
    job_id: str
    job_key: str

    # Hierarchy (for nested tasks)
    parent_id: str | None = None
    root_id: str = ""

    # Execution info
    attempt: int = 1  # Current attempt (1-indexed)
    max_attempts: int = 1  # Total allowed attempts
    started_at: datetime | None = None
    timeout: float | None = None

    # Function info
    function: str = ""
    function_name: str = ""

    # internal
    _metadata: dict[str, Any] = field(default_factory=dict)
    _cmd_queue: Any = field(default=None, repr=False)

    @classmethod
    def from_job(cls, job: Job) -> Self:
        """Create context from a job.

        Automatically captures parent_id from the current context if
        running inside another task (enables automatic hierarchy tracking).

        Args:
            job: Job to create context from
        """
        # Check for parent from current context (automatic propagation)
        parent_ctx = _current_context.get()  # Don't raise if no parent
        parent_id = job.parent_id

        if parent_ctx and not parent_id:
            # Inherit from current context
            parent_id = parent_ctx.job_id

        if job.root_id:
            root_id = job.root_id
        elif parent_ctx:
            root_id = parent_ctx.root_id or parent_ctx.job_id
        else:
            root_id = job.id

        metadata = dict(job.metadata)

        return cls(
            job_id=job.id,
            job_key=job.key,
            parent_id=parent_id,
            root_id=root_id,
            attempt=job.attempts,
            max_attempts=job.max_retries + 1,
            started_at=job.started_at,
            timeout=job.timeout,
            function=job.function,
            function_name=job.function_name,
            _metadata=metadata,
        )

    @property
    def log(self) -> logging.Logger:
        """Get logger for this job (recreated lazily, not stored — keeps Context picklable)."""
        return logging.getLogger(f"upnext.job.{self.job_id}")

    def set_progress(self, progress: float, message: str | None = None) -> None:
        """
        Update job progress.

        Progress is visible in the dashboard and can be used for monitoring.
        Sync-safe: works in async, threaded, and process-pool tasks.

        Args:
            progress: Progress value. Can be 0.0-1.0 or 0-100. Values > 1 are
                treated as percentages and divided by 100.
            message: Optional status message to display with progress.
        """
        # Support both 0-1 and 0-100 ranges
        if progress > 1.0:
            progress = progress / 100.0

        if not 0.0 <= progress <= 1.0:
            raise ValueError(
                f"Progress must be between 0.0 and 1.0 (or 0-100), got {progress}"
            )

        if self._cmd_queue is not None:
            self._cmd_queue.put(("set_progress", self.job_id, progress, message))

    def set_metadata(self, key: str, value: Any) -> None:
        """
        Store arbitrary metadata with the job.

        Metadata is persisted and visible in the dashboard.
        Sync-safe: works in async, threaded, and process-pool tasks.

        Args:
            key: Metadata key
            value: Metadata value (must be JSON-serializable)
        """
        self._metadata[key] = value
        if self._cmd_queue is not None:
            self._cmd_queue.put(("set_metadata", self.job_id, key, value))

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        Retrieve metadata from local cache.

        Args:
            key: Metadata key
            default: Default value if key not found

        Returns:
            Metadata value or default
        """
        return self._metadata.get(key, default)

    def checkpoint(self, state: dict[str, Any]) -> None:
        """
        Save checkpoint for crash recovery.

        Use this in tasks to save intermediate state. If the worker
        crashes, the task can resume from the last checkpoint.
        Sync-safe: works in async, threaded, and process-pool tasks.

        Args:
            state: State to save (must be JSON-serializable)
        """
        if self._cmd_queue is not None:
            self._cmd_queue.put(("checkpoint", self.job_id, state))

    def send_log(
        self,
        level: str,
        message: str,
        **extra: Any,
    ) -> None:
        """
        Send a log entry to the UpNext dashboard.

        Use this to send structured logs that will appear in the job's
        log viewer in the dashboard.
        Sync-safe: works in async, threaded, and process-pool tasks.

        Args:
            level: Log level (debug, info, warning, error)
            message: Log message
            **extra: Additional context to include
        """
        if self._cmd_queue is not None:
            self._cmd_queue.put(("send_log", self.job_id, level, message, extra))


# ContextVar for tracking the current execution context
# This enables automatic parent tracking - child tasks can find their parent
_current_context: ContextVar[Context | None] = ContextVar(
    "current_context", default=None
)


def get_current_context() -> Context:
    """
    Get the current execution context.

    If no context is found, raises a RuntimeError.
    """
    ctx = _current_context.get()
    if ctx is None:
        raise RuntimeError("No current context found - must be inside a task")
    return ctx


def set_current_context(ctx: Context | None) -> None:
    """Set or clear the current execution context."""
    _current_context.set(ctx)
