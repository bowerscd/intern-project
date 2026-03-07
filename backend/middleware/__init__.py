"""Request logging middleware — structured per-request context and timing.

Attaches a unique ``X-Request-ID`` to every request (or honours one sent
by a reverse proxy), logs the request and response on completion, and
makes the request ID available to all downstream log calls via
:class:`contextvars.ContextVar`.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("request")

# Context var so any logger in the call chain can include the request ID
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, duration, and user context."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process a request, attaching an ID and logging the outcome.

        :param request: The incoming HTTP request.
        :param call_next: The next middleware/route handler.
        :returns: The HTTP response.
        """
        # Use an existing X-Request-ID header (from a reverse proxy) or generate one
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)

        start = time.monotonic()

        # Extract user context from session (best-effort, session may not exist yet)
        account_id: int | None = None
        try:
            account_id = request.session.get("account_id")
        except Exception:
            pass

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "%s %s → crashed (%.1fms) [rid=%s user=%s]",
                request.method,
                request.url.path,
                duration_ms,
                rid,
                account_id,
                exc_info=True,
            )
            raise

        duration_ms = (time.monotonic() - start) * 1000

        # Attach request ID to the response
        response.headers["X-Request-ID"] = rid

        # Choose log level based on status code
        status_code = response.status_code
        if status_code >= 500:
            log = logger.error
        elif status_code >= 400:
            log = logger.warning
        else:
            log = logger.info

        log(
            "%s %s → %d (%.1fms) [rid=%s user=%s]",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
            rid,
            account_id,
        )

        return response
