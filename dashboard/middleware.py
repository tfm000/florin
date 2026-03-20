"""
Production middleware for the Sentinel Terminal dashboard.

- RequestIdMiddleware: injects X-Request-ID header for request tracing
- RateLimitMiddleware: sliding-window per-IP rate limiting
- sentinel_exception_handler: renders SentinelError as structured ErrorResponse
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from core.exceptions import SentinelError
from dashboard.schemas import ErrorResponse

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Inject X-Request-ID header into every request/response.

    If the client sends X-Request-ID, it is preserved.
    Otherwise a new UUID is generated.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid4().hex[:16]
        # Store on request state for downstream access
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple sliding-window rate limiter per client IP.

    Defaults: 100 requests per 60 seconds.
    Exempt paths: /api/health, /api/health/live, /api/health/ready, /ws
    """

    def __init__(
        self,
        app: object,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        # IP → list of request timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    _EXEMPT_PREFIXES = ("/api/health", "/ws", "/api/docs", "/openapi.json")

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self._EXEMPT_PREFIXES):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self._window_seconds

        # Prune old entries
        timestamps = self._requests[client_ip]
        self._requests[client_ip] = [t for t in timestamps if t > cutoff]

        if len(self._requests[client_ip]) >= self._max_requests:
            logger.warning("Rate limit exceeded for %s on %s", client_ip, path)
            error = ErrorResponse(
                error="RATE_LIMIT_EXCEEDED",
                message=f"Too many requests. Limit: {self._max_requests} per {self._window_seconds}s",
                request_id=getattr(request.state, "request_id", ""),
                timestamp=datetime.now(UTC),
            )
            return JSONResponse(
                status_code=429,
                content=error.model_dump(mode="json"),
                headers={"Retry-After": str(self._window_seconds)},
            )

        self._requests[client_ip].append(now)
        return await call_next(request)


async def sentinel_exception_handler(request: Request, exc: SentinelError) -> JSONResponse:
    """
    Global exception handler for SentinelError subclasses.

    Renders a structured ErrorResponse with the appropriate HTTP status code.
    """
    request_id = getattr(request.state, "request_id", "")

    logger.warning(
        "SentinelError: %s (code=%s, status=%d, request_id=%s)",
        exc.message, exc.code, exc.status_code, request_id,
    )

    error = ErrorResponse(
        error=exc.code,
        message=exc.message,
        request_id=request_id,
        timestamp=datetime.now(UTC),
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error.model_dump(mode="json"),
    )
