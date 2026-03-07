"""Request logging middleware — structured per-request context and timing.

Attaches a unique ``X-Request-ID`` to every request (or honours one sent
by a reverse proxy), logs the request and response on completion, and
makes the request ID available to all downstream log calls via
:class:`contextvars.ContextVar`.

In production JSON mode, every log record includes structured fields
(http_method, http_path, http_status, duration_ms, account_id, username,
client_ip, user_agent, content_type, content_length) to support
post-mortem debugging without reproduction.
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
    """Log every request with method, path, status, duration, and identity context.

    Captures enough structured context per request so that a single log
    line can answer "who did what, when, and how long did it take" for
    post-mortem debugging.
    """

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
        username: str | None = None
        try:
            account_id = request.session.get("account_id")
            username = request.session.get("username")
        except Exception:
            pass

        # Capture request metadata for structured logs
        content_length = request.headers.get("content-length", "0")
        content_type = request.headers.get("content-type", "")
        user_agent = request.headers.get("user-agent", "")
        client_ip = request.client.host if request.client else None
        forwarded_for = request.headers.get("x-forwarded-for")
        effective_ip = forwarded_for or client_ip

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "%s %s → crashed (%.1fms) [rid=%s user=%s/%s ip=%s]",
                request.method,
                request.url.path,
                duration_ms,
                rid,
                account_id,
                username,
                effective_ip,
                exc_info=True,
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_query": str(request.url.query) if request.url.query else None,
                    "duration_ms": round(duration_ms, 1),
                    "account_id": account_id,
                    "username": username,
                    "client_ip": effective_ip,
                    "user_agent": user_agent,
                    "content_type": content_type,
                    "content_length": content_length,
                },
            )
            raise

        duration_ms = (time.monotonic() - start) * 1000

        # Attach request ID to the response
        response.headers["X-Request-ID"] = rid

        # Ensure caches respect varying by cookie and origin
        existing_vary = response.headers.get("vary", "")
        needed = {"Cookie", "Origin"}
        present = {v.strip() for v in existing_vary.split(",") if v.strip()}
        missing = needed - present
        if missing:
            parts = [existing_vary] if existing_vary else []
            parts.extend(missing)
            response.headers["Vary"] = ", ".join(parts)

        # Choose log level based on status code
        status_code = response.status_code
        if status_code >= 500:
            log = logger.error
        elif status_code >= 400:
            log = logger.warning
        else:
            log = logger.info

        log(
            "%s %s → %d (%.1fms) [rid=%s user=%s/%s]",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
            rid,
            account_id,
            username,
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_query": str(request.url.query) if request.url.query else None,
                "http_status": status_code,
                "duration_ms": round(duration_ms, 1),
                "account_id": account_id,
                "username": username,
                "client_ip": effective_ip,
                "user_agent": user_agent,
                "content_type": content_type,
                "content_length": content_length,
            },
        )

        return response
