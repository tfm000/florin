"""
Domain exception hierarchy for Sentinel Terminal.

All application-specific exceptions inherit from SentinelError.
The dashboard exception handler maps these to proper HTTP responses.
"""

from __future__ import annotations


class SentinelError(Exception):
    """Base exception for all application errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(SentinelError):
    """Resource not found (404)."""

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, code="NOT_FOUND", status_code=404)


class ValidationError(SentinelError):
    """Invalid input data (422)."""

    def __init__(self, message: str = "Validation error") -> None:
        super().__init__(message, code="VALIDATION_ERROR", status_code=422)


class ConflictError(SentinelError):
    """Resource already exists or state conflict (409)."""

    def __init__(self, message: str = "Conflict") -> None:
        super().__init__(message, code="CONFLICT", status_code=409)


class ServiceUnavailableError(SentinelError):
    """Required service not available (503)."""

    def __init__(self, message: str = "Service unavailable") -> None:
        super().__init__(message, code="SERVICE_UNAVAILABLE", status_code=503)


class ForbiddenError(SentinelError):
    """Action not permitted (403)."""

    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message, code="FORBIDDEN", status_code=403)


class RateLimitError(SentinelError):
    """Too many requests (429)."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, code="RATE_LIMIT_EXCEEDED", status_code=429)


class ExternalServiceError(SentinelError):
    """External API call failed (502)."""

    def __init__(self, message: str = "External service error") -> None:
        super().__init__(message, code="EXTERNAL_SERVICE_ERROR", status_code=502)
