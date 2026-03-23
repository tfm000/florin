"""
Centralised configuration loaded from database settings table.

All settings are typed, validated, and documented. Access via:
    from config.settings import get_settings
    settings = get_settings()
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LLMMode(str, Enum):
    SINGLE = "single"
    CONSENSUS = "consensus"


class LLMProvider(str, Enum):
    GROQ = "groq"
    GEMINI = "gemini"
    CLAUDE = "claude"


class T212Environment(str, Enum):
    DEMO = "demo"
    LIVE = "live"
    READONLY = "readonly"


class AlpacaFeed(str, Enum):
    IEX = "iex"
    SIP = "sip"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

    # --- General ---
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./florin.db"

    # --- Trading 212 ---
    t212_api_key: str = ""
    t212_api_secret: str = ""
    t212_environment: T212Environment = T212Environment.DEMO

    @property
    def t212_base_url(self) -> str:
        if self.t212_environment in (T212Environment.LIVE, T212Environment.READONLY):
            return "https://live.trading212.com/api/v0"
        return "https://demo.trading212.com/api/v0"

    @property
    def t212_readonly(self) -> bool:
        return self.t212_environment == T212Environment.READONLY

    # --- Alpaca ---
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_feed: AlpacaFeed = AlpacaFeed.IEX

    @property
    def alpaca_data_ws_url(self) -> str:
        return f"wss://stream.data.alpaca.markets/v2/{self.alpaca_feed.value}"

    @property
    def alpaca_data_rest_url(self) -> str:
        return "https://data.alpaca.markets"

    # --- OpenFIGI ---
    openfigi_api_key: str = ""

    # --- Reddit ---
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "florin-terminal/0.2"

    # --- LLM: Groq ---
    groq_api_key: str = ""
    groq_model: str = "llama-4-scout-17b-16e-instruct"

    # --- LLM: Gemini ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"

    # --- LLM: Claude ---
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- Scanner ---
    scan_price_min: float = Field(default=0.01, ge=0.001, le=100.0)
    scan_price_max: float = Field(default=5.0, ge=0.01, le=100.0)
    scan_market_cap_min: float = Field(default=0.0, ge=0.0)
    scan_market_cap_max: float = Field(default=0.0, ge=0.0)
    scan_momentum_threshold: float = Field(default=5.0, ge=1.0, le=100.0)
    scan_interval_seconds: int = Field(default=120, ge=10, le=3600)
    scan_cooldown_minutes: int = Field(default=30, ge=1, le=1440)
    scan_min_volume: int = Field(default=10_000, ge=0)
    market_cap_source: str = "yfinance"  # "yfinance" or "inferred"

    # --- Trading ---
    paper_trading: bool = True  # DEFAULT TRUE — must explicitly set False for live trading
    default_position_size: float = Field(default=100.0, ge=1.0)
    position_size_unit: str = "gbp"
    default_stop_loss_pct: float = Field(default=10.0, ge=0.5, le=50.0)
    max_open_positions: int = Field(default=10, ge=1, le=100)
    max_daily_trades: int = Field(default=20, ge=1, le=200)

    # --- LLM Mode ---
    llm_mode: LLMMode = LLMMode.SINGLE
    llm_default_provider: LLMProvider = LLMProvider.GROQ
    llm_consensus_meta_provider: LLMProvider = LLMProvider.CLAUDE
    llm_user_context: str = ""

    # --- Dashboard ---
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = Field(default=8000, ge=1024, le=65535)

    # --- Derived helpers ---

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION

    @property
    def t212_configured(self) -> bool:
        return bool(self.t212_api_key and self.t212_api_secret)

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_api_secret)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def get_enabled_llm_providers(self) -> list[LLMProvider]:
        """Return list of LLM providers that have valid credentials configured."""
        providers = []
        if self.groq_api_key:
            providers.append(LLMProvider.GROQ)
        if self.gemini_api_key:
            providers.append(LLMProvider.GEMINI)
        if self.anthropic_api_key:
            providers.append(LLMProvider.CLAUDE)
        return providers

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper


_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Singleton settings instance."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


async def load_db_overrides(db: object) -> None:
    """Load setting overrides from the database."""
    from sqlalchemy import select
    from db.models import SettingORM

    settings = get_settings()

    async with db.session() as session:  # type: ignore[union-attr]
        result = await session.execute(select(SettingORM))
        for row in result.scalars():
            key, value = row.key, row.value
            if not hasattr(settings, key):
                continue

            current = getattr(settings, key)
            try:
                if isinstance(current, int):
                    setattr(settings, key, int(value))
                elif isinstance(current, float):
                    setattr(settings, key, float(value))
                elif hasattr(current, "value"):
                    setattr(settings, key, type(current)(value))
                else:
                    setattr(settings, key, value)
            except (ValueError, KeyError):
                logger.warning(
                    "Failed to apply DB override for setting %s=%r", key, value
                )
