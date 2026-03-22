"""Tests for dashboard middleware and exception handling."""

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import APIRouter, FastAPI

from config.settings import Settings
from core.events import EventBus
from core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    SentinelError,
    ServiceUnavailableError,
    ValidationError,
)
from dashboard.app import create_app
from dashboard.middleware import (
    RequestIdMiddleware,
    sentinel_exception_handler,
)
from db.database import Database


@pytest.fixture
async def app():
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()
    event_bus = EventBus()
    app = create_app(settings, db, event_bus)
    yield app
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_error_app() -> FastAPI:
    """Minimal FastAPI app with exception handler and test error routes."""
    app = FastAPI()
    app.add_exception_handler(SentinelError, sentinel_exception_handler)
    app.add_middleware(RequestIdMiddleware)

    router = APIRouter()

    @router.get("/test-error")
    async def raise_not_found():
        raise NotFoundError("Ticker XXXX not found")

    @router.get("/test-conflict")
    async def raise_conflict():
        raise ConflictError("Ticker already in watchlist")

    @router.get("/test-503")
    async def raise_503():
        raise ServiceUnavailableError("Broker not configured")

    @router.get("/test-422")
    async def raise_422():
        raise ValidationError("Invalid ticker format")

    @router.get("/test-403")
    async def raise_403():
        raise ForbiddenError("Paper trading mode — orders blocked")

    app.include_router(router, prefix="/api")
    return app


@pytest.fixture
def error_app():
    return _make_error_app()


@pytest.fixture
async def error_client(error_app):
    transport = ASGITransport(app=error_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestRequestIdMiddleware:
    @pytest.mark.asyncio
    async def test_response_has_request_id_header(self, client):
        resp = await client.get("/api/health/live")
        assert "x-request-id" in resp.headers

    @pytest.mark.asyncio
    async def test_client_provided_request_id_preserved(self, client):
        resp = await client.get(
            "/api/health/live",
            headers={"X-Request-ID": "my-custom-id"},
        )
        assert resp.headers["x-request-id"] == "my-custom-id"

    @pytest.mark.asyncio
    async def test_generated_request_id_is_nonempty(self, client):
        resp = await client.get("/api/health/live")
        assert len(resp.headers["x-request-id"]) > 0


class TestExceptionHandler:
    @pytest.mark.asyncio
    async def test_sentinel_error_rendered_as_json(self, error_client):
        resp = await error_client.get("/api/test-error")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"] == "NOT_FOUND"
        assert body["message"] == "Ticker XXXX not found"
        assert "request_id" in body
        assert "timestamp" in body

    @pytest.mark.asyncio
    async def test_conflict_error_409(self, error_client):
        resp = await error_client.get("/api/test-conflict")
        assert resp.status_code == 409
        assert resp.json()["error"] == "CONFLICT"

    @pytest.mark.asyncio
    async def test_service_unavailable_503(self, error_client):
        resp = await error_client.get("/api/test-503")
        assert resp.status_code == 503
        assert resp.json()["error"] == "SERVICE_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_validation_error_422(self, error_client):
        resp = await error_client.get("/api/test-422")
        assert resp.status_code == 422
        assert resp.json()["error"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_forbidden_error_403(self, error_client):
        resp = await error_client.get("/api/test-403")
        assert resp.status_code == 403
        assert resp.json()["error"] == "FORBIDDEN"


class TestExceptionClasses:
    def test_sentinel_error_base(self):
        e = SentinelError("something broke", code="CUSTOM", status_code=418)
        assert e.message == "something broke"
        assert e.code == "CUSTOM"
        assert e.status_code == 418
        assert str(e) == "something broke"

    def test_not_found_defaults(self):
        e = NotFoundError()
        assert e.status_code == 404
        assert e.code == "NOT_FOUND"

    def test_conflict_defaults(self):
        e = ConflictError()
        assert e.status_code == 409
        assert e.code == "CONFLICT"

    def test_rate_limit_defaults(self):
        e = RateLimitError()
        assert e.status_code == 429
        assert e.code == "RATE_LIMIT_EXCEEDED"

    def test_all_exceptions_inherit_from_sentinel_error(self):
        for cls in [NotFoundError, ValidationError, ConflictError,
                    ServiceUnavailableError, ForbiddenError,
                    RateLimitError]:
            assert issubclass(cls, SentinelError)


class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_liveness_always_200(self, client):
        resp = await client.get("/api/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    @pytest.mark.asyncio
    async def test_readiness_checks_db(self, client):
        resp = await client.get("/api/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["database"] is True

    @pytest.mark.asyncio
    async def test_health_includes_paper_trading(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "paper_trading" in data
        assert "trading_mode" in data
        assert data["trading_mode"] in ("PAPER", "LIVE")

    @pytest.mark.asyncio
    async def test_health_includes_broker_is_live(self, client):
        resp = await client.get("/api/health")
        data = resp.json()
        assert "is_live" in data["broker"]
