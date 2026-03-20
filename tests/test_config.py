"""Tests for config/settings.py — properties, helpers, and DB overrides."""

import pytest

from config.settings import (
    LLMProvider,
    Settings,
    T212Environment,
    load_db_overrides,
)
from db.database import Database
from db.models import SettingORM


class TestSettingsProperties:
    def test_t212_readonly_false_for_demo(self):
        s = Settings(t212_environment=T212Environment.DEMO)
        assert s.t212_readonly is False

    def test_t212_readonly_false_for_live(self):
        s = Settings(t212_environment=T212Environment.LIVE)
        assert s.t212_readonly is False

    def test_t212_readonly_true(self):
        s = Settings(t212_environment=T212Environment.READONLY)
        assert s.t212_readonly is True

    def test_t212_base_url_readonly_uses_live(self):
        s = Settings(t212_environment=T212Environment.READONLY)
        assert "live.trading212.com" in s.t212_base_url

    def test_t212_base_url_demo(self):
        s = Settings(t212_environment=T212Environment.DEMO)
        assert "demo.trading212.com" in s.t212_base_url

    def test_t212_configured_needs_both_keys(self):
        assert Settings(t212_api_key="", t212_api_secret="x").t212_configured is False
        assert Settings(t212_api_key="x", t212_api_secret="").t212_configured is False
        assert Settings(t212_api_key="x", t212_api_secret="x").t212_configured is True

    def test_alpaca_configured(self):
        assert Settings(alpaca_api_key="", alpaca_api_secret="").alpaca_configured is False
        assert Settings(alpaca_api_key="k", alpaca_api_secret="s").alpaca_configured is True

    def test_telegram_configured(self):
        assert Settings(telegram_bot_token="", telegram_chat_id="").telegram_configured is False
        assert Settings(telegram_bot_token="t", telegram_chat_id="c").telegram_configured is True


class TestGetEnabledLLMProviders:
    def test_always_includes_ollama_and_finbert(self):
        s = Settings()
        providers = s.get_enabled_llm_providers()
        assert LLMProvider.OLLAMA in providers
        assert LLMProvider.FINBERT in providers

    def test_includes_groq_when_configured(self):
        s = Settings(groq_api_key="test")
        providers = s.get_enabled_llm_providers()
        assert LLMProvider.GROQ in providers

    def test_includes_gemini_when_configured(self):
        s = Settings(gemini_api_key="test")
        providers = s.get_enabled_llm_providers()
        assert LLMProvider.GEMINI in providers

    def test_includes_claude_when_configured(self):
        s = Settings(anthropic_api_key="test")
        providers = s.get_enabled_llm_providers()
        assert LLMProvider.CLAUDE in providers

    def test_excludes_unconfigured_cloud_providers(self):
        s = Settings()
        providers = s.get_enabled_llm_providers()
        assert LLMProvider.GROQ not in providers
        assert LLMProvider.GEMINI not in providers
        assert LLMProvider.CLAUDE not in providers


class TestLoadDbOverrides:
    @pytest.mark.asyncio
    async def test_applies_int_override(self):
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init()

        async with db.session() as session:
            session.add(SettingORM(key="scan_interval_seconds", value="60"))
            await session.commit()

        s = Settings(scan_interval_seconds=120)
        # Monkey-patch the global singleton for this test
        import config.settings as mod
        old = mod._settings_instance
        mod._settings_instance = s
        try:
            await load_db_overrides(db)
            assert s.scan_interval_seconds == 60
        finally:
            mod._settings_instance = old
            await db.close()

    @pytest.mark.asyncio
    async def test_applies_float_override(self):
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init()

        async with db.session() as session:
            session.add(SettingORM(key="scan_price_threshold", value="3.5"))
            await session.commit()

        s = Settings(scan_price_threshold=5.0)
        import config.settings as mod
        old = mod._settings_instance
        mod._settings_instance = s
        try:
            await load_db_overrides(db)
            assert s.scan_price_threshold == 3.5
        finally:
            mod._settings_instance = old
            await db.close()

    @pytest.mark.asyncio
    async def test_skips_unknown_keys(self):
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init()

        async with db.session() as session:
            session.add(SettingORM(key="nonexistent_key", value="whatever"))
            await session.commit()

        s = Settings()
        import config.settings as mod
        old = mod._settings_instance
        mod._settings_instance = s
        try:
            await load_db_overrides(db)
            assert not hasattr(s, "nonexistent_key")
        finally:
            mod._settings_instance = old
            await db.close()

    @pytest.mark.asyncio
    async def test_applies_enum_override(self):
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init()

        async with db.session() as session:
            session.add(SettingORM(key="llm_default_provider", value="gemini"))
            await session.commit()

        s = Settings(llm_default_provider=LLMProvider.GROQ)
        import config.settings as mod
        old = mod._settings_instance
        mod._settings_instance = s
        try:
            await load_db_overrides(db)
            assert s.llm_default_provider == LLMProvider.GEMINI
        finally:
            mod._settings_instance = old
            await db.close()
