"""LLM Model Registry API — CRUD, health-check, and analysis settings.

Provides endpoints for managing registered LLM models and configuring
which models are assigned to each analysis role (announcement, sentiment,
consensus leader).

API keys are **never** returned unmasked in responses.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from dashboard.deps import get_analyser_refresh_callback, get_db, get_settings
from db.models import LLMModelORM, SettingORM, generate_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["llm-models"])

# ── Supported hosts metadata ──────────────────────────────────────────────────

_HOSTS = [
    {
        "id": "anthropic-cli",
        "name": "Anthropic (CLI)",
        "models_hint": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
        "requires_api_key": False,
        "note": (
            "Uses Claude Code CLI auth. API key optional. "
            "Install CLI: npm install -g @anthropic-ai/claude-code, "
            "then: claude login"
        ),
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "models_hint": [],
        "requires_api_key": True,
        "note": "Any model available on openrouter.ai",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "models_hint": ["gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "requires_api_key": True,
    },
    {
        "id": "groq",
        "name": "Groq",
        "models_hint": ["llama-4-scout-17b-16e-instruct"],
        "requires_api_key": True,
    },
]

_VALID_THINKING_MODES = {"off", "low", "medium", "high", "max"}

_VALID_HOSTS: set[str] = {str(h["id"]) for h in _HOSTS}


# ── Request / Response schemas ────────────────────────────────────────────────


class CreateLLMModel(BaseModel):
    """Request body for creating a new LLM model registration."""

    host: str = Field(
        ...,
        description="Provider host: anthropic-cli, openrouter, gemini, groq",
    )
    model: str = Field(
        ..., min_length=1, description="Model identifier (e.g. claude-sonnet-4-20250514)"
    )
    api_key: str = Field(default="", description="API key (optional for CLI-auth providers)")
    thinking_mode: str = Field(default="low", description="Thinking depth (anthropic-cli only)")


class UpdateLLMModel(BaseModel):
    """Request body for updating an existing LLM model registration."""

    model: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    thinking_mode: str | None = None


class LLMModelResponse(BaseModel):
    """Response model for a registered LLM model (API key masked)."""

    id: str
    host: str
    model: str
    api_key_masked: str
    display_name: str
    enabled: bool
    thinking_mode: str | None = None


class LLMSettingsUpdate(BaseModel):
    """Request body for updating LLM analysis settings."""

    mode: str | None = None  # "single" | "consensus"
    announcement_model_id: str | None = None
    sentiment_model_id: str | None = None
    consensus_leader_model_id: str | None = None
    user_context: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mask_key(key: str) -> str:
    """Mask an API key for safe display.

    Shows first 3 and last 3 characters with dots in between.
    Short keys (<=6 chars) are fully masked.
    """
    if not key:
        return ""
    if len(key) <= 6:
        return "••••••"
    return key[:3] + "•" * (len(key) - 6) + key[-3:]


def _make_display_name(host: str, model: str) -> str:
    """Generate a human-friendly display name for a host + model pair."""
    host_labels = {
        "anthropic-cli": "Anthropic CLI",
        "openrouter": "OpenRouter",
        "gemini": "Gemini",
        "groq": "Groq",
    }
    label = host_labels.get(host, host.title())
    return f"{label} / {model}"


def _orm_to_response(orm: LLMModelORM) -> LLMModelResponse:
    """Convert an ORM instance to a masked response model."""
    return LLMModelResponse(
        id=orm.id,
        host=orm.host,
        model=orm.model,
        api_key_masked=_mask_key(orm.api_key),
        display_name=orm.display_name,
        enabled=orm.enabled,
        thinking_mode=orm.thinking_mode,
    )


async def _trigger_refresh() -> None:
    """Trigger analyser refresh if callback is registered."""
    callback = get_analyser_refresh_callback()
    if callback:
        try:
            await callback()
            logger.info("LLM analysers refreshed after model change")
        except Exception as e:
            logger.error("Failed to refresh LLM analysers: %s", e)


# ── Model CRUD endpoints ─────────────────────────────────────────────────────


@router.get("/llm-models/hosts")
async def list_hosts() -> list[dict]:
    """Return the list of supported LLM hosts with metadata.

    Each entry includes the host ID, display name, suggested models,
    and whether an API key is required.
    """
    return _HOSTS


@router.get("/llm-models")
async def list_models() -> list[LLMModelResponse]:
    """Return all registered LLM models with masked API keys.

    Models are ordered by host then display name.
    """
    db = get_db()
    async with db.session() as session:
        result = await session.execute(
            select(LLMModelORM).order_by(LLMModelORM.host, LLMModelORM.display_name)
        )
        models = result.scalars().all()
    return [_orm_to_response(m) for m in models]


@router.post("/llm-models", status_code=201)
async def create_model(payload: CreateLLMModel) -> LLMModelResponse:
    """Register a new LLM model.

    Validates that the host is supported, generates an ID and display
    name, and persists the model to the database. Triggers analyser
    refresh so the new model is immediately available.

    Args:
        payload: Host, model name, and API key.

    Returns:
        The created model with masked API key.

    Raises:
        HTTPException 400: If the host is not supported.
    """
    if payload.host not in _VALID_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported host '{payload.host}'. Must be one of: {sorted(_VALID_HOSTS)}",
        )

    # Validate API key requirement per host
    host_meta = next((h for h in _HOSTS if h["id"] == payload.host), None)
    if host_meta and host_meta.get("requires_api_key") and not payload.api_key:
        raise HTTPException(
            status_code=400,
            detail=f"API key is required for host '{payload.host}'",
        )

    # Validate thinking_mode for anthropic-cli
    thinking_mode: str | None = None
    if payload.host == "anthropic-cli":
        if payload.thinking_mode not in _VALID_THINKING_MODES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid thinking_mode '{payload.thinking_mode}'. "
                    f"Must be one of: {sorted(_VALID_THINKING_MODES)}"
                ),
            )
        thinking_mode = payload.thinking_mode

    model_id = generate_id()
    display_name = _make_display_name(payload.host, payload.model)

    orm = LLMModelORM(
        id=model_id,
        host=payload.host,
        model=payload.model,
        api_key=payload.api_key,
        display_name=display_name,
        enabled=True,
        thinking_mode=thinking_mode,
    )

    db = get_db()
    async with db.session() as session:
        session.add(orm)
        await session.commit()
        await session.refresh(orm)

    logger.info("Registered LLM model: %s (%s)", display_name, model_id)
    await _trigger_refresh()

    return _orm_to_response(orm)


@router.put("/llm-models/{model_id}")
async def update_model(model_id: str, payload: UpdateLLMModel) -> LLMModelResponse:
    """Update a registered LLM model.

    Supports partial updates — only provided fields are changed.
    If the model name changes, the display name is regenerated.
    Triggers analyser refresh after successful update.

    Args:
        model_id: ID of the model to update.
        payload: Fields to update (model, api_key, enabled).

    Returns:
        The updated model with masked API key.

    Raises:
        HTTPException 404: If the model ID is not found.
    """
    db = get_db()
    async with db.session() as session:
        orm = await session.get(LLMModelORM, model_id)
        if not orm:
            raise HTTPException(status_code=404, detail="Model not found")

        if payload.model is not None:
            orm.model = payload.model
            orm.display_name = _make_display_name(orm.host, orm.model)

        if payload.api_key is not None:
            orm.api_key = payload.api_key

        if payload.enabled is not None:
            orm.enabled = payload.enabled

        if payload.thinking_mode is not None and orm.host == "anthropic-cli":
            if payload.thinking_mode not in _VALID_THINKING_MODES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid thinking_mode '{payload.thinking_mode}'. "
                        f"Must be one of: {sorted(_VALID_THINKING_MODES)}"
                    ),
                )
            orm.thinking_mode = payload.thinking_mode

        orm.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(orm)

    logger.info("Updated LLM model: %s (%s)", orm.display_name, model_id)
    await _trigger_refresh()

    return _orm_to_response(orm)


@router.delete("/llm-models/{model_id}")
async def delete_model(model_id: str) -> dict:
    """Delete a registered LLM model.

    Warns (but still deletes) if the model is currently assigned to
    an analysis role. Triggers analyser refresh after deletion.

    Args:
        model_id: ID of the model to delete.

    Returns:
        Confirmation with any warnings about active assignments.

    Raises:
        HTTPException 404: If the model ID is not found.
    """
    db = get_db()
    settings = get_settings()

    # Check if model is assigned to any role
    warnings: list[str] = []
    if settings.llm_announcement_model_id == model_id:
        warnings.append("This model was assigned for announcement analysis")
    if settings.llm_sentiment_model_id == model_id:
        warnings.append("This model was assigned for sentiment analysis")
    if settings.llm_consensus_leader_model_id == model_id:
        warnings.append("This model was assigned as consensus leader")

    async with db.session() as session:
        orm = await session.get(LLMModelORM, model_id)
        if not orm:
            raise HTTPException(status_code=404, detail="Model not found")

        display_name = orm.display_name
        await session.delete(orm)
        await session.commit()

    logger.info("Deleted LLM model: %s (%s)", display_name, model_id)
    await _trigger_refresh()

    result: dict = {"deleted": model_id, "display_name": display_name}
    if warnings:
        result["warnings"] = warnings
    return result


@router.post("/llm-models/{model_id}/health-check")
async def health_check(model_id: str) -> dict:
    """Test connectivity for a registered LLM model.

    Creates a temporary analyser instance with the model's credentials
    and runs its health_check() method. Does not persist anything.

    Args:
        model_id: ID of the model to test.

    Returns:
        Dict with ``ok`` (bool) and optional ``error`` message.

    Raises:
        HTTPException 404: If the model ID is not found.
    """
    db = get_db()
    async with db.session() as session:
        orm = await session.get(LLMModelORM, model_id)
        if not orm:
            raise HTTPException(status_code=404, detail="Model not found")

        host = orm.host
        model = orm.model
        api_key = orm.api_key
        thinking_mode = orm.thinking_mode

    # Create a temporary analyser and run health check
    try:
        analyser = _create_temp_analyser(host, model, api_key, thinking_mode)
        if analyser is None:
            return {"ok": False, "error": f"Unsupported host: {host}"}

        ok = await analyser.health_check()
        return {"ok": ok, "error": None if ok else "Health check returned False"}

    except Exception as e:
        logger.warning("Health check failed for %s/%s: %s", host, model, e)
        return {"ok": False, "error": str(e)}


def _create_temp_analyser(
    host: str,
    model: str,
    api_key: str,
    thinking_mode: str | None = None,
):
    """Create a temporary LLM analyser instance for health checking.

    Uses a minimal Settings-like object to avoid polluting the global
    settings with temporary credentials.

    Args:
        host: Provider host ID.
        model: Model identifier.
        api_key: API key (may be empty for CLI-auth providers).
        thinking_mode: Thinking depth for anthropic-cli.

    Returns:
        LLMAnalyser instance, or None if host is unsupported.
    """
    from config.settings import Settings

    if host == "groq":
        from analysis.groq_analyser import GroqAnalyser

        temp = Settings(groq_api_key=api_key, groq_model=model)
        return GroqAnalyser(temp)

    if host == "gemini":
        from analysis.gemini_analyser import GeminiAnalyser

        temp = Settings(gemini_api_key=api_key, gemini_model=model)
        return GeminiAnalyser(temp)

    if host == "anthropic-cli":
        from analysis.claude_analyser import ClaudeAnalyser

        temp = Settings(
            anthropic_api_key=api_key,
            claude_model=model,
            claude_cli_thinking_mode=thinking_mode or "low",
        )
        return ClaudeAnalyser(temp)

    if host == "openrouter":
        from analysis.openrouter_analyser import OpenRouterAnalyser

        temp = Settings(openrouter_api_key=api_key, openrouter_model=model)
        return OpenRouterAnalyser(temp)

    return None


# ── LLM analysis settings endpoints ──────────────────────────────────────────


@router.get("/llm-settings")
async def get_llm_settings() -> dict:
    """Return current LLM analysis mode and model assignments.

    Returns:
        Dict with mode, model IDs for each role, and user context.
    """
    settings = get_settings()
    return {
        "mode": settings.llm_mode.value,
        "announcement_model_id": settings.llm_announcement_model_id,
        "sentiment_model_id": settings.llm_sentiment_model_id,
        "consensus_leader_model_id": settings.llm_consensus_leader_model_id,
        "user_context": settings.llm_user_context,
    }


@router.put("/llm-settings")
async def update_llm_settings(payload: LLMSettingsUpdate) -> dict:
    """Update LLM analysis mode and model assignments.

    Validates that referenced model IDs exist and are enabled.
    Persists changes to the settings DB table and updates the live
    Settings object. Triggers analyser refresh.

    Args:
        payload: Fields to update.

    Returns:
        Confirmation with list of updated keys.

    Raises:
        HTTPException 400: If mode is invalid or a model ID doesn't exist.
    """
    db = get_db()
    settings = get_settings()
    updated_keys: list[str] = []

    # Validate mode
    if payload.mode is not None and payload.mode not in ("single", "consensus"):
        raise HTTPException(
            status_code=400,
            detail="mode must be 'single' or 'consensus'",
        )

    # Validate model IDs exist and are enabled
    model_id_fields = {
        "announcement_model_id": payload.announcement_model_id,
        "sentiment_model_id": payload.sentiment_model_id,
        "consensus_leader_model_id": payload.consensus_leader_model_id,
    }

    for field_name, model_id in model_id_fields.items():
        if model_id is not None and model_id != "":
            async with db.session() as session:
                orm = await session.get(LLMModelORM, model_id)
                if not orm:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Model ID '{model_id}' for {field_name} not found",
                    )
                if not orm.enabled:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Model '{orm.display_name}' for {field_name} is disabled",
                    )

    # Persist changes to DB settings table
    settings_map: dict[str, str] = {}

    if payload.mode is not None:
        settings_map["llm_mode"] = payload.mode
    if payload.announcement_model_id is not None:
        settings_map["llm_announcement_model_id"] = payload.announcement_model_id
    if payload.sentiment_model_id is not None:
        settings_map["llm_sentiment_model_id"] = payload.sentiment_model_id
    if payload.consensus_leader_model_id is not None:
        settings_map["llm_consensus_leader_model_id"] = payload.consensus_leader_model_id
    if payload.user_context is not None:
        settings_map["llm_user_context"] = payload.user_context

    async with db.session() as session:
        for key, value in settings_map.items():
            existing = await session.get(SettingORM, key)
            if existing:
                existing.value = value
            else:
                session.add(SettingORM(key=key, value=value))

            # Update live Settings object
            _apply_setting(settings, key, value)
            updated_keys.append(key)

        await session.commit()

    if updated_keys:
        await _trigger_refresh()

    return {"updated": updated_keys}


def _apply_setting(settings, key: str, value: str) -> None:
    """Apply a setting value to the live Settings object.

    Handles type coercion for int, float, enum, and string fields.

    Args:
        settings: The live Settings instance.
        key: Setting key name.
        value: New value as string.
    """
    current = getattr(settings, key, None)
    if current is None and not hasattr(settings, key):
        return

    if isinstance(current, int):
        setattr(settings, key, int(value))
    elif isinstance(current, float):
        setattr(settings, key, float(value))
    elif current is not None and hasattr(current, "value"):
        # Enum
        enum_cls = type(current)
        with contextlib.suppress(ValueError):
            setattr(settings, key, enum_cls(value))
    else:
        setattr(settings, key, value)
