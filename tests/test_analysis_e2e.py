"""End-to-end analysis flow tests and no-API-keys integration tests.

Covers:
- Full pipeline: alert → sentiment/8-K fetch → LLM analysis → report
- Report serialisation to DB and back
- Report API endpoint structure
- Graceful handling when no LLM models are configured
- Consensus mode with 0 models
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from analysis.consensus_generator import ConsensusGenerator
from analysis.report_generator import ReportGenerator
from config.settings import Settings
from core.events import EventBus
from core.models import (
    AlertSignal,
    AnalysisReport,
    AnalysisResult,
    AnalysisType,
    Form8KFiling,
    Recommendation,
    SentimentData,
)
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database
from db.models import ReportORM

# =============================================================================
# Fixtures
# =============================================================================


def _make_alert(**kwargs) -> AlertSignal:
    defaults = {
        "ticker": "TEST",
        "price": 2.50,
        "change_pct": 7.5,
        "volume": 100_000,
        "avg_volume": 10_000,
    }
    defaults.update(kwargs)
    return AlertSignal(**defaults)


def _make_sentiment(**kwargs) -> SentimentData:
    defaults = {"ticker": "TEST"}
    defaults.update(kwargs)
    return SentimentData(**defaults)


def _make_filings() -> list[Form8KFiling]:
    return [
        Form8KFiling(
            ticker="TEST",
            filed_date=datetime(2026, 1, 15, tzinfo=UTC),
            form_type="8-K",
            description="Current report",
            items=["Item 2.02"],
            text_content="Quarterly earnings of $0.50 per share.",
        )
    ]


def _make_mock_analyser(
    provider: str = "test",
    recommendation: Recommendation = Recommendation.BUY,
    score: float = 6.0,
    error: str | None = None,
) -> AsyncMock:
    """Create a mock LLMAnalyser with predictable results."""
    analyser = AsyncMock()
    analyser.provider_name = provider
    analyser.model_name = "test-model"

    announcement_result = AnalysisResult(
        provider=provider,
        model="test-model",
        analysis_type=AnalysisType.ANNOUNCEMENT,
        score=score,
        confidence=0.8,
        recommendation=recommendation,
        summary=f"Test announcement from {provider}",
        key_points=["Test point"],
        bullish_signals=["Test bullish"],
        bearish_signals=["Test bearish"],
        error=error,
    )
    sentiment_result = AnalysisResult(
        provider=provider,
        model="test-model",
        analysis_type=AnalysisType.SENTIMENT,
        score=score,
        confidence=0.8,
        recommendation=recommendation,
        summary=f"Test sentiment from {provider}",
        key_points=["Test point"],
        bullish_signals=["Test bullish"],
        bearish_signals=["Test bearish"],
        error=error,
    )

    analyser.analyse_announcements.return_value = announcement_result
    analyser.analyse_sentiment.return_value = sentiment_result
    return analyser


@pytest.fixture
async def app():
    """Test app with in-memory database."""
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


# =============================================================================
# E2E: Single-mode report generation
# =============================================================================


class TestE2ESingleMode:
    """End-to-end: alert → analyse → AnalysisReport."""

    @pytest.mark.asyncio
    async def test_full_single_mode_both_types(self):
        """Single mode with both analysis types produces complete report."""
        analyser = _make_mock_analyser("groq", Recommendation.BUY, 7.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"groq": analyser}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            filings=_make_filings(),
        )

        assert report.mode == "single"
        assert report.announcement_analysis is not None
        assert report.sentiment_analysis is not None
        assert report.announcement_score == 7.0
        assert report.sentiment_score == 7.0
        assert report.final_recommendation == Recommendation.BUY

    @pytest.mark.asyncio
    async def test_single_mode_announcement_only(self):
        """Single mode with announcement type only."""
        analyser = _make_mock_analyser("groq", Recommendation.HOLD, 5.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"groq": analyser}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            filings=_make_filings(),
            analysis_types=["announcement"],
        )

        assert report.announcement_analysis is not None
        assert report.sentiment_analysis is None
        assert report.announcement_score == 5.0

    @pytest.mark.asyncio
    async def test_single_mode_sentiment_only(self):
        """Single mode with sentiment type only."""
        analyser = _make_mock_analyser("groq", Recommendation.BUY, 8.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"groq": analyser}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert report.sentiment_analysis is not None
        assert report.announcement_analysis is None
        assert report.sentiment_score == 8.0


# =============================================================================
# E2E: Consensus-mode report generation
# =============================================================================


class TestE2EConsensusMode:
    """End-to-end: multiple models → consensus → AnalysisReport."""

    @pytest.mark.asyncio
    async def test_consensus_produces_individual_and_consensus(self):
        """Consensus mode produces individual results + consensus leader."""
        analysers = {
            "a": _make_mock_analyser("a", Recommendation.BUY, 7.0),
            "b": _make_mock_analyser("b", Recommendation.HOLD, 5.0),
            "c": _make_mock_analyser("c", Recommendation.BUY, 6.0),
        }
        settings = Settings(llm_consensus_meta_provider="claude-cli")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert report.mode == "consensus"
        assert len(report.sentiment_analyses) == 3
        assert report.sentiment_consensus is not None

    @pytest.mark.asyncio
    async def test_consensus_both_types(self):
        """Consensus mode with both analysis types."""
        analysers = {
            "a": _make_mock_analyser("a", Recommendation.BUY, 7.0),
            "b": _make_mock_analyser("b", Recommendation.BUY, 6.0),
        }
        settings = Settings(llm_consensus_meta_provider="groq")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            filings=_make_filings(),
        )

        assert len(report.announcement_analyses) == 2
        assert len(report.sentiment_analyses) == 2
        assert report.announcement_consensus is not None
        assert report.sentiment_consensus is not None


# =============================================================================
# Report serialisation
# =============================================================================


class TestReportSerialisation:
    """Test report round-trip to DB and back."""

    @pytest.mark.asyncio
    async def test_report_to_db_and_back(self, app):
        """Report can be serialised to ReportORM and deserialised."""
        analyser = _make_mock_analyser("test", Recommendation.BUY, 7.5)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"test": analyser}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            filings=_make_filings(),
        )

        # Serialise to ORM
        final_score = report.sentiment_score or report.announcement_score or 0.0
        orm = ReportORM(
            id=report.id or "test123",
            ticker=report.ticker,
            mode=report.mode,
            alert_price=report.alert.price,
            alert_change_pct=report.alert.change_pct,
            alert_volume=report.alert.volume,
            final_recommendation=report.final_recommendation.value,
            final_score=final_score,
            final_confidence=report.final_confidence,
            report_json=report.model_dump_json(),
        )

        # Save to DB
        from dashboard.deps import get_db

        db = get_db()
        async with db.session() as session:
            session.add(orm)
            await session.commit()

        # Read back
        from sqlalchemy import select

        async with db.session() as session:
            result = await session.execute(select(ReportORM).where(ReportORM.ticker == "TEST"))
            loaded = result.scalar()

        assert loaded is not None
        assert loaded.ticker == "TEST"
        assert loaded.final_recommendation == "BUY"
        assert loaded.final_score == 7.5

        # Deserialise JSON back to model
        restored = AnalysisReport.model_validate_json(loaded.report_json)
        assert restored.ticker == "TEST"
        assert restored.sentiment_score == 7.5


# =============================================================================
# Report API endpoint
# =============================================================================


class TestReportAPI:
    """Test the reports API endpoint returns correct structure."""

    @pytest.mark.asyncio
    async def test_get_reports_list(self, client):
        """GET /api/reports should return a list."""
        resp = await client.get("/api/reports")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_report_not_found(self, client):
        """GET /api/reports/nonexistent should return 404."""
        resp = await client.get("/api/reports/nonexistent")
        assert resp.status_code == 404


# =============================================================================
# No-API-keys integration tests
# =============================================================================


class TestNoAPIKeys:
    """Tests for graceful handling when no LLM models are configured."""

    @pytest.mark.asyncio
    async def test_no_analysers_single_mode(self):
        """Single mode with 0 analysers returns empty report."""
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            analysis_types=["sentiment"],
        )

        # No crash — returns report with no analysis
        assert report.ticker == "TEST"
        assert report.sentiment_analysis is None
        assert report.announcement_analysis is None

    @pytest.mark.asyncio
    async def test_no_analysers_consensus_mode(self):
        """Consensus mode with 0 analysers returns empty report."""
        settings = Settings(llm_consensus_meta_provider="claude-cli")
        gen = ConsensusGenerator({}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert report.mode == "consensus"
        assert len(report.sentiment_analyses) == 0
        # No consensus possible with 0 models
        assert report.sentiment_consensus is None

    @pytest.mark.asyncio
    async def test_research_endpoint_no_analysers(self, client):
        """Research analyse endpoint with no analysers returns error in body."""
        # Need a mock yfinance so the endpoint can get past info lookup
        mock_yf = AsyncMock()
        mock_yf.get_info.return_value = {"name": "Test Corp", "current_price": 10.0}
        mock_yf.get_performance_metrics.return_value = {}
        set_state("yfinance_provider", mock_yf)
        set_state("analysers", {})
        set_state("sentiment_aggregator", None)

        resp = await client.post("/api/research/asset/AAPL/analyse")
        assert resp.status_code == 200
        data = resp.json()
        # Should have an error — no analysers available
        assert data.get("error") is not None or (
            data.get("sentiment") and data["sentiment"].get("error")
        )

    @pytest.mark.asyncio
    async def test_model_returns_error(self):
        """When the analyser returns an error result, report captures it."""
        analyser = _make_mock_analyser("broken", error="API key invalid")
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"broken": analyser}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            analysis_types=["sentiment"],
        )

        # The sentiment analysis should have the error
        assert report.sentiment_analysis is not None
        assert report.sentiment_analysis.error == "API key invalid"
        # Final recommendation should be HOLD (error fallback)
        assert report.final_recommendation == Recommendation.HOLD

    @pytest.mark.asyncio
    async def test_analyser_raises_exception(self):
        """When the analyser raises, report captures it as error."""
        analyser = AsyncMock()
        analyser.provider_name = "crashing"
        analyser.model_name = "crash-model"
        analyser.analyse_sentiment.side_effect = ConnectionError("Network down")

        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"crashing": analyser}, settings)

        report = await gen.generate(
            _make_alert(),
            _make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert report.sentiment_analysis is not None
        assert "Network down" in report.sentiment_analysis.error
