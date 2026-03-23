"""
Shared API response schemas for the Florin Terminal dashboard.

These provide consistent, typed responses across all endpoints:
- ErrorResponse for all error cases
- PaginatedResponse for list endpoints
- SuccessResponse for mutation confirmations
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error: str = Field(description="Machine-readable error code, e.g. NOT_FOUND")
    message: str = Field(description="Human-readable error description")
    request_id: str = Field(default="", description="Correlation ID from X-Request-ID header")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper for paginated list responses."""

    items: list[T]
    total: int = Field(description="Total number of items matching the query")
    limit: int
    offset: int
    has_more: bool = Field(description="Whether more items exist beyond this page")


class SuccessResponse(BaseModel):
    """Simple success acknowledgement for mutations (DELETE, etc.)."""

    status: str = "ok"
    request_id: str = ""
