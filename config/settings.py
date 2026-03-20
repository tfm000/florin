"""
Centralised configuration loaded from environment variables / .env file.

All settings are typed, validated, and documented. Access via:
    from config.settings import get_settings
    settings = get_settings()
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LLMMode(str, Enum):
    SINGLE = "single"
    CONSENSUS = "consensus"


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    GROQ = "groq"
    GEMINI = "gemini"
    CLAUDE = "claude"
    FINBERT = "finbert"


class T212Environment(str, Enum):
    DEMO = "demo"
    LIVE = "live"


class AlpacaFeed(str, Enum):
    IEX = "iex"
    SIP = "sip"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General ---
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./sentinel.db"

    # --- Trading 212 ---
    t212_api_key: str = ""
    t212_api_secret: str = ""
    t212_environment: T212Environment = T212Environment.DEMO

    @property
    def t212_base_url(self) -> str:
        if self.t212_environment == T212Environment.LIVE:
            return "https://live.trading212.com/api/v0"
        return "https://demo.trading212.com/api/v0"

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

    # --- Polygon ---
    polygon_api_key: str = ""

    # --- FMP ---
    fmp_api_key: str = ""

    # --- Reddit ---
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "penny-stock-sentinel/0.1"

    # --- LLM: Ollama ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:8b"

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
    scan_price_threshold: float = Field(default=5.0, ge=0.01, le=100.0)
    scan_momentum_threshold: float = Field(default=5.0, ge=1.0, le=100.0)
    scan_interval_seconds: int = Field(default=120, ge=10, le=3600)
    scan_cooldown_minutes: int = Field(default=30, ge=1, le=1440)
    scan_min_volume: int = Field(default=10_000, ge=0)

    # --- Trading ---
    default_position_size: float = Field(default=100.0, ge=1.0)
    default_stop_loss_pct: float = Field(default=10.0, ge=0.5, le=50.0)
    max_open_positions: int = Field(default=10, ge=1, le=100)
    max_daily_trades: int = Field(default=20, ge=1, le=200)

    # --- LLM Mode ---
    llm_mode: LLMMode = LLMMode.SINGLE
    llm_default_provider: LLMProvider = LLMProvider.GROQ
    llm_consensus_meta_provider: LLMProvider = LLMProvider.CLAUDE

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
        # Ollama is always available if the server is running (no API key needed)
        providers.append(LLMProvider.OLLAMA)
        # FinBERT is always available (local model)
        providers.append(LLMProvider.FINBERT)
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance — cached after first call."""
    return Settings()
