"""Server middleware."""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Request-ID"

# ContextVar so the correlation ID is available to any code in the request path,
# including the logging filter below.
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request/response cycle.

    If the client sends an ``X-Request-ID`` header, it is preserved;
    otherwise a new UUID4 is generated.  The ID is set on
    ``request.state.correlation_id`` **and** stored in a ``ContextVar``
    so downstream logging can include it automatically.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        cid = request.headers.get(CORRELATION_ID_HEADER) or uuid.uuid4().hex
        request.state.correlation_id = cid
        correlation_id_var.set(cid)
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = cid
        return response


class CorrelationIDFilter(logging.Filter):
    """Logging filter that injects ``correlation_id`` into every log record.

    Add this filter to a handler (or the root logger) so formatters —
    including ``JSONFormatter`` — can emit the request ID without callers
    having to pass it explicitly.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()  # type: ignore[attr-defined]
        return True
