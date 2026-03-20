"""Settings CRUD API — read/write runtime-configurable settings.

Settings are layered:
  1. Defaults (hardcoded in Settings class)
  2. Database (SettingORM table — what this API reads/writes)

API keys are masked when returned to the frontend.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from dashboard.deps import get_db, get_settings
from db.models import SettingORM

router = APIRouter(tags=["settings"])

# Keys that contain secrets — mask when returning to frontend
_SECRET_KEYS = frozenset({
    "t212_api_key", "t212_api_secret",
    "alpaca_api_key", "alpaca_api_secret",
    "polygon_api_key",
    "reddit_client_id", "reddit_client_secret",
    "groq_api_key", "gemini_api_key", "anthropic_api_key",
    "telegram_bot_token",
})

# Settings grouped by section for the UI
_SECTIONS = [
    {
        "id": "broker",
        "label": "Broker (Trading 212)",
        "keys": [
            "t212_api_key", "t212_api_secret", "t212_environment",
        ],
    },
    {
        "id": "market_data",
        "label": "Market Data",
        "keys": [
            "alpaca_api_key", "alpaca_api_secret", "alpaca_feed",
            "polygon_api_key",
        ],
    },
    {
        "id": "sentiment",
        "label": "Sentiment Sources",
        "keys": [
            "reddit_client_id", "reddit_client_secret", "reddit_user_agent",
        ],
    },
    {
        "id": "llm",
        "label": "LLM Providers",
        "keys": [
            "ollama_base_url", "ollama_model",
            "groq_api_key", "groq_model",
            "gemini_api_key", "gemini_model",
            "anthropic_api_key", "claude_model",
        ],
    },
    {
        "id": "analysis",
        "label": "Analysis Mode",
        "keys": [
            "llm_mode", "llm_default_provider", "llm_consensus_meta_provider",
            "llm_user_context",
        ],
    },
    {
        "id": "telegram",
        "label": "Telegram",
        "keys": [
            "telegram_bot_token", "telegram_chat_id",
        ],
    },
    {
        "id": "scanner",
        "label": "Scanner",
        "keys": [
            "scan_price_min", "scan_price_max",
            "scan_market_cap_min", "scan_market_cap_max",
            "scan_momentum_threshold",
            "scan_interval_seconds", "scan_cooldown_minutes", "scan_min_volume",
            "market_cap_source",
        ],
    },
    {
        "id": "trading",
        "label": "Trading",
        "keys": [
            "default_position_size", "position_size_unit",
            "default_stop_loss_pct",
            "max_open_positions", "max_daily_trades",
        ],
    },
    {
        "id": "general",
        "label": "General",
        "keys": [
            "app_env", "log_level", "dashboard_host", "dashboard_port",
        ],
    },
]

# Enum choices for select dropdowns
_CHOICES: dict[str, list[str]] = {
    "app_env": ["development", "production"],
    "log_level": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "t212_environment": ["demo", "live", "readonly"],
    "alpaca_feed": ["iex", "sip"],
    "llm_mode": ["single", "consensus"],
    "llm_default_provider": ["ollama", "groq", "gemini", "claude", "finbert"],
    "llm_consensus_meta_provider": ["ollama", "groq", "gemini", "claude"],
    "position_size_unit": ["gbp", "usd", "shares"],
    "market_cap_source": ["yfinance", "inferred"],
}

# Type hints for the frontend
_FIELD_TYPES: dict[str, str] = {
    "scan_price_min": "number",
    "scan_price_max": "number",
    "scan_market_cap_min": "number",
    "scan_market_cap_max": "number",
    "scan_momentum_threshold": "number",
    "scan_interval_seconds": "number",
    "scan_cooldown_minutes": "number",
    "scan_min_volume": "number",
    "default_position_size": "number",
    "default_stop_loss_pct": "number",
    "max_open_positions": "number",
    "max_daily_trades": "number",
    "dashboard_port": "number",
    "llm_user_context": "textarea",
}


def _mask(key: str, value: str) -> str:
    """Mask secret values for display."""
    if key not in _SECRET_KEYS or not value:
        return value
    if len(value) <= 6:
        return "••••••"
    return value[:3] + "•" * (len(value) - 6) + value[-3:]


def _get_current_value(key: str) -> str:
    """Get the current effective value for a setting key."""
    settings = get_settings()
    val = getattr(settings, key, "")
    # Enum values → string
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)


@router.get("/settings")
async def get_all_settings() -> dict:
    """Return all settings grouped by section, with DB overrides and metadata."""
    db = get_db()

    # Load DB overrides
    db_overrides: dict[str, str] = {}
    async with db.session() as session:
        result = await session.execute(select(SettingORM))
        for row in result.scalars():
            db_overrides[row.key] = row.value

    sections = []
    for section in _SECTIONS:
        fields = []
        for key in section["keys"]:
            current = _get_current_value(key)
            is_secret = key in _SECRET_KEYS
            has_db_override = key in db_overrides

            fields.append({
                "key": key,
                "value": _mask(key, current) if is_secret else current,
                "is_secret": is_secret,
                "is_set": bool(current) if is_secret else True,
                "has_db_override": has_db_override,
                "type": _FIELD_TYPES.get(key, "select" if key in _CHOICES else "text"),
                "choices": _CHOICES.get(key),
            })

        sections.append({
            "id": section["id"],
            "label": section["label"],
            "fields": fields,
        })

    return {"sections": sections}


class SettingUpdate(BaseModel):
    key: str
    value: str


class SettingsBulkUpdate(BaseModel):
    settings: list[SettingUpdate]


@router.put("/settings")
async def update_settings(payload: SettingsBulkUpdate) -> dict:
    """Update one or more settings. Persists to database."""
    db = get_db()
    settings = get_settings()
    updated = []

    async with db.session() as session:
        for item in payload.settings:
            key = item.key
            value = item.value

            # Validate key exists in settings
            if not hasattr(settings, key):
                continue

            # Skip masked/unchanged secrets
            if key in _SECRET_KEYS and "•" in value:
                continue

            # Upsert into DB
            existing = await session.get(SettingORM, key)
            if existing:
                existing.value = value
            else:
                session.add(SettingORM(key=key, value=value))

            # Update the live settings object
            _apply_setting(settings, key, value)
            updated.append(key)

        await session.commit()

    return {"updated": updated, "restart_required": _needs_restart(updated)}


@router.delete("/settings/{key}")
async def delete_setting(key: str) -> dict:
    """Remove a DB override, reverting to the default value."""
    db = get_db()

    async with db.session() as session:
        existing = await session.get(SettingORM, key)
        if existing:
            await session.delete(existing)
            await session.commit()
            return {"deleted": key}

    return {"deleted": None}


def _apply_setting(settings: Any, key: str, value: str) -> None:
    """Apply a setting value to the live Settings object."""
    current = getattr(settings, key, None)
    if current is None:
        return

    # Type coercion
    if isinstance(current, (int,)):
        setattr(settings, key, int(value))
    elif isinstance(current, (float,)):
        setattr(settings, key, float(value))
    elif hasattr(current, "value"):
        # Enum — find matching member
        enum_cls = type(current)
        try:
            setattr(settings, key, enum_cls(value))
        except ValueError:
            pass
    else:
        setattr(settings, key, value)


def _needs_restart(keys: list[str]) -> bool:
    """Check if any updated keys require an app restart to take effect."""
    restart_keys = {
        "database_url", "dashboard_host", "dashboard_port",
        "t212_api_key", "t212_api_secret", "t212_environment",
        "alpaca_api_key", "alpaca_api_secret",
        "telegram_bot_token", "telegram_chat_id",
    }
    return bool(set(keys) & restart_keys)
