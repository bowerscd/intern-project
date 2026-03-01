"""Rate limiting configuration using slowapi.

Applies per-IP rate limits to auth-sensitive endpoints.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
)
"""Application-wide rate limiter instance.

Uses ``request.client.host`` (corrected by :class:`ProxyHeadersMiddleware`)
as the client key.  Set ``RATELIMIT_ENABLED=false`` to disable (e.g. in
integration tests).
"""
