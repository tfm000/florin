"""
Production middleware for the Florin Terminal dashboard.

- RequestIdMiddleware: injects X-Request-ID header for request tracing
- florin_exception_handler: renders FlorinError as structured ErrorResponse
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from core.exceptions import FlorinError
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


async def florin_exception_handler(request: Request, exc: FlorinError) -> JSONResponse:
    """
    Global exception handler for FlorinError subclasses.

    Renders a structured ErrorResponse with the appropriate HTTP status code.
    """
    request_id = getattr(request.state, "request_id", "")

    logger.warning(
        "FlorinError: %s (code=%s, status=%d, request_id=%s)",
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
