"""Tests for LLM model registry API endpoints.

Covers: CRUD operations, health-check, hosts listing, LLM settings
management, API key masking, validation, and edge cases.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database
from db.models import LLMModelORM, SettingORM


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def app():
    """Create a test app with an in-memory database."""
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
    """Create an async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def db_session(app):
    """Get the test database for direct queries."""
    from dashboard.deps import get_db
    return get_db()


# =============================================================================
# Hosts listing
# =============================================================================


class TestListHosts:
    """Tests for GET /api/llm-models/hosts."""

    @pytest.mark.asyncio
    async def test_returns_supported_hosts(self, client):
        """Should return all 4 supported LLM hosts."""
        resp = await client.get("/api/llm-models/hosts")
        assert resp.status_code == 200

        hosts = resp.json()
        assert len(hosts) == 4

        host_ids = {h["id"] for h in hosts}
        assert host_ids == {"anthropic-cli", "openrouter", "gemini", "groq"}

    @pytest.mark.asyncio
    async def test_hosts_have_required_fields(self, client):
        """Each host should have id, name, models_hint, and requires_api_key."""
        resp = await client.get("/api/llm-models/hosts")
        for host in resp.json():
            assert "id" in host
            assert "name" in host
            assert "models_hint" in host
            assert "requires_api_key" in host


# =============================================================================
# CRUD operations
# =============================================================================


class TestCreateModel:
    """Tests for POST /api/llm-models."""

    @pytest.mark.asyncio
    async def test_create_model_success(self, client):
        """Should create a model and return it with masked API key."""
        resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama-4-scout",
            "api_key": "sk-test-1234567890abcdef",
        })
        assert resp.status_code == 201

        data = resp.json()
        assert data["host"] == "groq"
        assert data["model"] == "llama-4-scout"
        assert data["display_name"] == "Groq / llama-4-scout"
        assert data["enabled"] is True
        assert "id" in data
        assert len(data["id"]) == 16

        # API key should be masked
        assert "sk-" not in data["api_key_masked"] or data["api_key_masked"].count("•") > 0

    @pytest.mark.asyncio
    async def test_create_model_invalid_host(self, client):
        """Should reject unsupported host."""
        resp = await client.post("/api/llm-models", json={
            "host": "invalid_host",
            "model": "test",
            "api_key": "key",
        })
        assert resp.status_code == 400
        assert "Unsupported host" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_model_empty_fields(self, client):
        """Should reject empty model or api_key."""
        resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "",
            "api_key": "key",
        })
        assert resp.status_code == 422  # Pydantic validation

    @pytest.mark.asyncio
    async def test_create_multiple_models(self, client):
        """Should allow multiple models from same or different hosts."""
        resp1 = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama-4-scout",
            "api_key": "key1",
        })
        resp2 = await client.post("/api/llm-models", json={
            "host": "gemini",
            "model": "gemini-2.0-flash",
            "api_key": "key2",
        })
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] != resp2.json()["id"]


class TestListModels:
    """Tests for GET /api/llm-models."""

    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        """Should return empty list when no models exist."""
        resp = await client.get("/api/llm-models")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_after_create(self, client):
        """Should include created models."""
        await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key123",
        })

        resp = await client.get("/api/llm-models")
        models = resp.json()
        assert len(models) == 1
        assert models[0]["host"] == "groq"
        assert models[0]["model"] == "llama"

    @pytest.mark.asyncio
    async def test_api_key_never_exposed(self, client):
        """API key should never appear unmasked in list response."""
        await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "super-secret-key-12345",
        })

        resp = await client.get("/api/llm-models")
        model = resp.json()[0]
        assert "api_key" not in model  # Only api_key_masked
        assert "super-secret" not in model["api_key_masked"]


class TestUpdateModel:
    """Tests for PUT /api/llm-models/{id}."""

    @pytest.mark.asyncio
    async def test_update_model_name(self, client):
        """Should update model name and regenerate display_name."""
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key",
        })
        model_id = create_resp.json()["id"]

        resp = await client.put(f"/api/llm-models/{model_id}", json={
            "model": "llama-small",
        })
        assert resp.status_code == 200
        assert resp.json()["model"] == "llama-small"
        assert resp.json()["display_name"] == "Groq / llama-small"

    @pytest.mark.asyncio
    async def test_update_enabled_status(self, client):
        """Should toggle enabled status."""
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key",
        })
        model_id = create_resp.json()["id"]

        resp = await client.put(f"/api/llm-models/{model_id}", json={
            "enabled": False,
        })
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    @pytest.mark.asyncio
    async def test_update_api_key(self, client):
        """Should update API key (masked in response)."""
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "old-key-1234567890",
        })
        model_id = create_resp.json()["id"]

        resp = await client.put(f"/api/llm-models/{model_id}", json={
            "api_key": "new-key-abcdefghij",
        })
        assert resp.status_code == 200
        # Should show the new masked key
        assert resp.json()["api_key_masked"].startswith("new")

    @pytest.mark.asyncio
    async def test_update_nonexistent_model(self, client):
        """Should return 404 for unknown model ID."""
        resp = await client.put("/api/llm-models/nonexistent", json={
            "model": "test",
        })
        assert resp.status_code == 404


class TestDeleteModel:
    """Tests for DELETE /api/llm-models/{id}."""

    @pytest.mark.asyncio
    async def test_delete_model(self, client):
        """Should delete model and return confirmation."""
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key",
        })
        model_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/llm-models/{model_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == model_id

        # Verify it's gone
        list_resp = await client.get("/api/llm-models")
        assert len(list_resp.json()) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_model(self, client):
        """Should return 404 for unknown model ID."""
        resp = await client.delete("/api/llm-models/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_assigned_model_warns(self, client):
        """Should warn when deleting a model assigned to an analysis role."""
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key",
        })
        model_id = create_resp.json()["id"]

        # Assign it to sentiment
        await client.put("/api/llm-settings", json={
            "sentiment_model_id": model_id,
        })

        # Delete it — should succeed but include warning
        resp = await client.delete(f"/api/llm-models/{model_id}")
        assert resp.status_code == 200
        assert "warnings" in resp.json()
        assert any("sentiment" in w for w in resp.json()["warnings"])


# =============================================================================
# Health check
# =============================================================================


class TestHealthCheck:
    """Tests for POST /api/llm-models/{id}/health-check."""

    @pytest.mark.asyncio
    async def test_health_check_nonexistent(self, client):
        """Should return 404 for unknown model ID."""
        resp = await client.post("/api/llm-models/nonexistent/health-check")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_health_check_bad_key(self, client):
        """Health check with invalid key should return ok=False."""
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama-4-scout-17b-16e-instruct",
            "api_key": "invalid-key",
        })
        model_id = create_resp.json()["id"]

        resp = await client.post(f"/api/llm-models/{model_id}/health-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["error"] is not None


# =============================================================================
# LLM settings
# =============================================================================


class TestLLMSettings:
    """Tests for GET/PUT /api/llm-settings."""

    @pytest.mark.asyncio
    async def test_get_default_settings(self, client):
        """Should return default LLM settings."""
        resp = await client.get("/api/llm-settings")
        assert resp.status_code == 200

        data = resp.json()
        assert "mode" in data
        assert "announcement_model_id" in data
        assert "sentiment_model_id" in data
        assert "consensus_leader_model_id" in data
        assert "user_context" in data

    @pytest.mark.asyncio
    async def test_update_mode(self, client):
        """Should update analysis mode."""
        resp = await client.put("/api/llm-settings", json={
            "mode": "consensus",
        })
        assert resp.status_code == 200
        assert "llm_mode" in resp.json()["updated"]

        # Verify it persisted
        get_resp = await client.get("/api/llm-settings")
        assert get_resp.json()["mode"] == "consensus"

    @pytest.mark.asyncio
    async def test_update_invalid_mode(self, client):
        """Should reject invalid mode."""
        resp = await client.put("/api/llm-settings", json={
            "mode": "invalid",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_model_assignment(self, client):
        """Should assign a model to an analysis role."""
        # Create a model first
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key",
        })
        model_id = create_resp.json()["id"]

        resp = await client.put("/api/llm-settings", json={
            "announcement_model_id": model_id,
        })
        assert resp.status_code == 200

        get_resp = await client.get("/api/llm-settings")
        assert get_resp.json()["announcement_model_id"] == model_id

    @pytest.mark.asyncio
    async def test_update_nonexistent_model_id(self, client):
        """Should reject assignment of nonexistent model ID."""
        resp = await client.put("/api/llm-settings", json={
            "sentiment_model_id": "nonexistent123",
        })
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_disabled_model_id(self, client):
        """Should reject assignment of disabled model."""
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key",
        })
        model_id = create_resp.json()["id"]

        # Disable it
        await client.put(f"/api/llm-models/{model_id}", json={"enabled": False})

        # Try to assign it
        resp = await client.put("/api/llm-settings", json={
            "sentiment_model_id": model_id,
        })
        assert resp.status_code == 400
        assert "disabled" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_user_context(self, client):
        """Should update user context."""
        resp = await client.put("/api/llm-settings", json={
            "user_context": "Focus on biotech catalysts",
        })
        assert resp.status_code == 200

        get_resp = await client.get("/api/llm-settings")
        assert get_resp.json()["user_context"] == "Focus on biotech catalysts"

    @pytest.mark.asyncio
    async def test_clear_model_assignment(self, client):
        """Should allow clearing a model assignment with empty string."""
        # Create and assign a model
        create_resp = await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "key",
        })
        model_id = create_resp.json()["id"]

        await client.put("/api/llm-settings", json={
            "sentiment_model_id": model_id,
        })

        # Clear it
        resp = await client.put("/api/llm-settings", json={
            "sentiment_model_id": "",
        })
        assert resp.status_code == 200

        get_resp = await client.get("/api/llm-settings")
        assert get_resp.json()["sentiment_model_id"] == ""


# =============================================================================
# API key masking
# =============================================================================


class TestAPIKeyMasking:
    """Tests for API key masking helper."""

    @pytest.mark.asyncio
    async def test_short_key_fully_masked(self, client):
        """Keys <= 6 chars should be fully masked."""
        await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "abc",
        })

        resp = await client.get("/api/llm-models")
        assert resp.json()[0]["api_key_masked"] == "••••••"

    @pytest.mark.asyncio
    async def test_long_key_partially_masked(self, client):
        """Keys > 6 chars should show first 3 and last 3."""
        await client.post("/api/llm-models", json={
            "host": "groq",
            "model": "llama",
            "api_key": "gsk-1234567890abcdef",
        })

        resp = await client.get("/api/llm-models")
        masked = resp.json()[0]["api_key_masked"]
        assert masked.startswith("gsk")
        assert masked.endswith("def")
        assert "•" in masked
