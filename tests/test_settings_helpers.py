"""Tests for dashboard settings route helper functions."""

from config.settings import LLMMode, LLMProvider, Settings
from dashboard.routes.settings import _apply_setting, _mask, _needs_restart


class TestMask:
    def test_non_secret_returned_as_is(self):
        assert _mask("log_level", "INFO") == "INFO"

    def test_empty_secret_returned_as_is(self):
        assert _mask("groq_api_key", "") == ""

    def test_short_secret_fully_masked(self):
        assert _mask("groq_api_key", "abc") == "••••••"
        assert _mask("groq_api_key", "abcdef") == "••••••"

    def test_long_secret_partially_masked(self):
        result = _mask("groq_api_key", "abcdefghij")
        assert result.startswith("abc")
        assert result.endswith("hij")
        assert "•" in result
        assert len(result) == 10

    def test_non_secret_key_not_masked(self):
        assert _mask("ollama_model", "llama3.2:8b") == "llama3.2:8b"


class TestApplySetting:
    def test_apply_int(self):
        s = Settings(scan_interval_seconds=120)
        _apply_setting(s, "scan_interval_seconds", "60")
        assert s.scan_interval_seconds == 60

    def test_apply_float(self):
        s = Settings(scan_price_max=5.0)
        _apply_setting(s, "scan_price_max", "3.5")
        assert s.scan_price_max == 3.5

    def test_apply_string(self):
        s = Settings(ollama_model="old")
        _apply_setting(s, "ollama_model", "new_model")
        assert s.ollama_model == "new_model"

    def test_apply_enum(self):
        s = Settings(llm_mode=LLMMode.SINGLE)
        _apply_setting(s, "llm_mode", "consensus")
        assert s.llm_mode == LLMMode.CONSENSUS

    def test_apply_nonexistent_key_ignored(self):
        s = Settings()
        _apply_setting(s, "totally_fake_key", "value")
        # Should not raise


class TestNeedsRestart:
    def test_restart_for_broker_key(self):
        assert _needs_restart(["t212_api_key"]) is True

    def test_restart_for_alpaca_key(self):
        assert _needs_restart(["alpaca_api_key"]) is True

    def test_restart_for_telegram(self):
        assert _needs_restart(["telegram_bot_token"]) is True

    def test_restart_for_dashboard_port(self):
        assert _needs_restart(["dashboard_port"]) is True

    def test_no_restart_for_scanner_settings(self):
        assert _needs_restart(["scan_interval_seconds"]) is False

    def test_no_restart_for_llm_model(self):
        assert _needs_restart(["ollama_model", "groq_model"]) is False

    def test_mixed_keys(self):
        assert _needs_restart(["scan_interval_seconds", "t212_api_key"]) is True
