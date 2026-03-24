"""
Florin Terminal — Main Entry Point

Starts all services:
  1. Database initialisation
  2. Market data connection
  3. Screener alert service (periodic screener execution + alerts)
  4. Alert processing pipeline
  5. Position monitoring
  6. Telegram bot
  7. Web dashboard
  8. Market breadth scanner

All services run concurrently via asyncio.gather().
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from typing import Any

from config.settings import LLMProvider, get_settings
from core.events import EventBus, EventType
from core.logging import get_logger, setup_logging
from core.models import AlertSignal, AnalysisReport
from db.database import Database
from db.models import ReportORM

logger = get_logger(__name__)


class Florin:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.event_bus = EventBus()
        self.db: Database | None = None
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        # Mutable references for hot-reload
        self._analysers: dict[str, Any] = {}
        self._report_gen: Any = None
        self._consensus_gen: Any = None

    async def start(self) -> None:
        """Initialise and start all services."""
        setup_logging(self.settings.log_level, self.settings.app_env)
        logger.info(
            "Starting Florin Terminal",
            env=self.settings.app_env.value,
            llm_mode=self.settings.llm_mode.value,
            paper_trading=self.settings.paper_trading,
        )

        # --- Database ---
        # Backward compatibility: rename sentinel.db → florin.db if needed
        if "florin.db" in self.settings.database_url:
            if not os.path.exists("florin.db") and os.path.exists("sentinel.db"):
                logger.info("Migrating database: sentinel.db → florin.db")
                os.rename("sentinel.db", "florin.db")

        self.db = Database(self.settings.database_url)
        await self.db.init()
        await self.db.run_migrations()
        logger.info("Database ready")

        # Load settings overrides from DB (set via dashboard)
        from config.settings import load_db_overrides
        await load_db_overrides(self.db)

        # --- Validate required config ---
        warnings = []
        if not self.settings.alpaca_configured:
            warnings.append("Alpaca API not configured — market data unavailable")
        if not self.settings.t212_configured:
            warnings.append("Trading 212 API not configured — using paper broker")
        if not self.settings.telegram_configured:
            warnings.append("Telegram not configured — mobile alerts disabled")
        for w in warnings:
            logger.warning(w)

        # --- Log enabled LLM providers ---
        providers = self.settings.get_enabled_llm_providers()
        logger.info("Enabled LLM providers", providers=[p.value for p in providers])

        # --- Initialise components ---

        # Broker — wrapped in SafeBroker for paper trading safety
        raw_broker = await self._init_broker()
        broker = await self._wrap_broker(raw_broker)

        # Market data provider
        data_provider = None
        if self.settings.alpaca_configured:
            from data.alpaca_provider import AlpacaProvider
            data_provider = AlpacaProvider(self.settings)
            await data_provider.connect()
            logger.info("Alpaca data provider connected")

        # Policy rate fetcher (BIS API)
        from data.policy_rates import PolicyRateFetcher
        policy_rate_fetcher = PolicyRateFetcher(self.db)

        # yfinance provider (always available, no API key needed)
        from data.yfinance_provider import YFinanceProvider
        yfinance_provider = YFinanceProvider(policy_rate_fetcher=policy_rate_fetcher)

        # Screener alert service (replaces old MomentumScanner + UniverseManager)
        from scanner.screener_alert_service import ScreenerAlertService
        screener_alert_svc = ScreenerAlertService(
            self.db, self.event_bus, yfinance_provider,
        )

        # Sentiment aggregator
        sentiment_agg = self._init_sentiment()

        # SEC 8-K filing source (standalone, not a sentiment source)
        from sentiment.sec_8k_source import SEC8KSource
        sec_8k_source = SEC8KSource()

        # Migrate legacy LLM settings → model registry (first boot only)
        await self._migrate_legacy_llm_settings()

        # LLM analysers (from DB model registry, with flat-settings fallback)
        self._analysers = await self._init_analysers_from_db()

        # Report generators (hold mutable references for hot-reload)
        from analysis.report_generator import ReportGenerator
        from analysis.consensus_generator import ConsensusGenerator
        self._report_gen = ReportGenerator(self._analysers, self.settings)
        self._consensus_gen = ConsensusGenerator(self._analysers, self.settings)

        # Telegram bot
        telegram_bot = None
        if self.settings.telegram_configured:
            from telegram_bot.bot import FlorinBot
            telegram_bot = FlorinBot(self.settings, self.event_bus, broker)
            await telegram_bot.setup()
            logger.info("Telegram bot initialised")

        # Dashboard
        from dashboard.app import create_app, serve as dashboard_serve
        from dashboard.deps import set_state
        set_state("shutdown_callback", self.shutdown)
        set_state("screener_alert_service", screener_alert_svc)
        set_state("data_provider", data_provider)
        set_state("yfinance_provider", yfinance_provider)
        set_state("analysers", self._analysers)
        set_state("report_generator", self._report_gen)
        set_state("consensus_generator", self._consensus_gen)
        set_state("sentiment_aggregator", sentiment_agg)
        set_state("analyser_refresh_callback", self._refresh_analysers)
        from stats.risk_free import RiskFreeRateFetcher
        rf_fetcher = RiskFreeRateFetcher(self.db)
        set_state("rf_fetcher", rf_fetcher)
        set_state("policy_rate_fetcher", policy_rate_fetcher)

        # Load persisted CUSIP→ticker mappings for 13F filings
        from data.sec_13f_provider import load_cusip_cache
        await load_cusip_cache(self.db)

        dashboard_app = create_app(self.settings, self.db, self.event_bus, broker)

        # --- Build service list ---
        services: list[asyncio.Task] = []

        # Heartbeat
        services.append(asyncio.create_task(self._heartbeat(), name="heartbeat"))

        # Risk-free rate daily refresh
        services.append(asyncio.create_task(
            self._rf_refresh_loop(rf_fetcher), name="rf-refresh"
        ))

        # Screener alert service (background, periodic screener execution)
        services.append(asyncio.create_task(
            screener_alert_svc.run(), name="screener-alerts"
        ))
        logger.info("Screener alert service started")

        # Alert pipeline (uses self._report_gen / self._consensus_gen for hot-reload)
        services.append(asyncio.create_task(
            self._alert_pipeline(sentiment_agg, sec_8k_source),
            name="alert-pipeline",
        ))

        # Position monitor
        if broker:
            services.append(asyncio.create_task(
                self._position_monitor(broker), name="position-monitor"
            ))

        # Telegram
        if telegram_bot:
            services.append(asyncio.create_task(
                telegram_bot.start_polling(), name="telegram-bot"
            ))
            # Alert listener — sends enriched alerts to Telegram with account context
            from telegram_bot.handlers.alerts import alert_listener, screener_alert_listener
            services.append(asyncio.create_task(
                alert_listener(self.event_bus, telegram_bot, broker, self.settings),
                name="telegram-alerts",
            ))
            # Screener alert listener — sends screener alerts to Telegram
            services.append(asyncio.create_task(
                screener_alert_listener(
                    self.event_bus, telegram_bot, broker, self.settings,
                ),
                name="telegram-screener-alerts",
            ))

        # Dashboard
        services.append(asyncio.create_task(
            dashboard_serve(dashboard_app, self.settings), name="dashboard"
        ))

        # Market breadth scanner (hourly during market hours)
        from scanner.breadth_scanner import breadth_scan_loop
        services.append(asyncio.create_task(
            breadth_scan_loop(self.db, alpaca=data_provider),
            name="breadth-scanner",
        ))

        # WebSocket event bridge
        from dashboard.ws import event_bridge
        from dashboard.deps import get_ws_manager
        services.append(asyncio.create_task(
            event_bridge(self.event_bus, get_ws_manager()), name="ws-bridge"
        ))

        self._tasks = services
        logger.info("Florin started — %d service(s) running", len(services))

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        # Clean up
        if data_provider:
            await data_provider.disconnect()
        if broker:
            await broker.disconnect()
        if self.db:
            await self.db.close()

        logger.info("Florin shut down cleanly")

    # --- Component initialisation ---

    async def _init_broker(self) -> Any:
        """Initialise the appropriate broker."""
        if self.settings.t212_configured and self.db:
            from broker.trading212 import Trading212Broker
            broker = Trading212Broker(self.settings, self.db)
            await broker.connect()
            logger.info("Trading 212 broker connected (live=%s)", broker.is_live)
            return broker

        from broker.paper_broker import PaperBroker
        broker = PaperBroker(initial_cash=10_000.0, currency="GBP")
        await broker.connect()
        logger.info("Paper broker active")
        return broker

    async def _wrap_broker(self, inner_broker: Any) -> Any:
        """Wrap the broker in SafeBroker to enforce paper_trading mode."""
        from broker.paper_broker import PaperBroker
        from broker.safe_broker import SafeBroker

        paper_broker = PaperBroker(initial_cash=10_000.0, currency="GBP")
        await paper_broker.connect()

        safe = SafeBroker(
            inner=inner_broker,
            paper_broker=paper_broker,
            paper_mode=self.settings.paper_trading,
        )

        if self.settings.paper_trading:
            logger.info("PAPER TRADING MODE — orders will NOT reach live broker")
        else:
            logger.warning("LIVE TRADING ENABLED — orders will reach %s", inner_broker.name)

        return safe

    def _init_sentiment(self) -> Any:
        """Initialise sentiment aggregator with all sources."""
        from sentiment.aggregator import SentimentAggregator
        from sentiment.reddit_source import RedditSource
        from sentiment.stocktwits_source import StockTwitsSource
        from sentiment.sec_edgar_source import SECEdgarSource
        from sentiment.news_source import NewsSource

        sources = [
            StockTwitsSource(access_token=self.settings.stocktwits_access_token),
            SECEdgarSource(),
            NewsSource(self.settings),
        ]

        # Reddit: use OAuth (PRAW) if credentials available, else public .json fallback
        if self.settings.reddit_client_id:
            sources.append(RedditSource(self.settings))
            logger.info("Reddit: using OAuth (PRAW)")
        else:
            from sentiment.reddit_json_source import RedditJsonSource
            sources.append(RedditJsonSource())
            logger.info("Reddit: using public .json fallback (no API key)")

        # Google Custom Search: only add if API key is configured
        if self.settings.google_search_api_key:
            from sentiment.google_search_source import GoogleSearchSource
            sources.append(GoogleSearchSource(self.settings))
            logger.info("Google Search: enabled (API key configured)")
        else:
            logger.info("Google Search: disabled (no API key)")

        return SentimentAggregator(sources)

    def _init_analysers_from_settings(self) -> dict[str, Any]:
        """Initialise LLM analysers from flat Settings fields (legacy fallback).

        Used when no models are registered in the llm_models table.
        """
        analysers: dict[str, Any] = {}
        enabled = self.settings.get_enabled_llm_providers()

        if LLMProvider.GROQ in enabled:
            from analysis.groq_analyser import GroqAnalyser
            analysers["groq"] = GroqAnalyser(self.settings)

        if LLMProvider.GEMINI in enabled:
            from analysis.gemini_analyser import GeminiAnalyser
            analysers["gemini"] = GeminiAnalyser(self.settings)

        if LLMProvider.CLAUDE in enabled:
            from analysis.claude_analyser import ClaudeAnalyser
            analysers["claude"] = ClaudeAnalyser(self.settings)

        if LLMProvider.OPENAI in enabled:
            from analysis.openai_analyser import OpenAIAnalyser
            analysers["openai"] = OpenAIAnalyser(self.settings)

        if LLMProvider.OPENROUTER in enabled:
            from analysis.openrouter_analyser import OpenRouterAnalyser
            analysers["openrouter"] = OpenRouterAnalyser(self.settings)

        logger.info("LLM analysers initialised (legacy)", analysers=list(analysers.keys()))
        return analysers

    async def _init_analysers_from_db(self) -> dict[str, Any]:
        """Initialise LLM analysers from the llm_models DB table.

        Each enabled model in the registry gets its own analyser instance,
        keyed by model ID. This replaces the flat provider-keyed approach.

        Returns:
            Dict mapping model_id → LLMAnalyser instance.
        """
        from config.settings import Settings
        from db.models import LLMModelORM
        from sqlalchemy import select

        analysers: dict[str, Any] = {}

        async with self.db.session() as session:
            result = await session.execute(
                select(LLMModelORM).where(LLMModelORM.enabled == True)  # noqa: E712
            )
            models = result.scalars().all()

        if not models:
            logger.info("No LLM models in registry, falling back to flat settings")
            return self._init_analysers_from_settings()

        for m in models:
            try:
                analyser = self._create_analyser(m.host, m.model, m.api_key)
                if analyser:
                    analysers[m.id] = analyser
                    logger.debug("Loaded analyser: %s (%s)", m.display_name, m.id)
            except Exception as e:
                logger.error("Failed to create analyser for %s: %s", m.display_name, e)

        logger.info(
            "LLM analysers initialised from DB registry",
            count=len(analysers),
            models=[m.display_name for m in models if m.id in analysers],
        )
        return analysers

    def _create_analyser(self, host: str, model: str, api_key: str) -> Any:
        """Create a single LLM analyser from host/model/key.

        Args:
            host: Provider host ID (openai, groq, etc.).
            model: Model identifier string.
            api_key: API key for the provider.

        Returns:
            LLMAnalyser instance, or None if host is unsupported.
        """
        from config.settings import Settings

        if host == "groq":
            from analysis.groq_analyser import GroqAnalyser
            return GroqAnalyser(Settings(groq_api_key=api_key, groq_model=model))

        if host == "gemini":
            from analysis.gemini_analyser import GeminiAnalyser
            return GeminiAnalyser(Settings(gemini_api_key=api_key, gemini_model=model))

        if host == "anthropic":
            from analysis.claude_analyser import ClaudeAnalyser
            return ClaudeAnalyser(Settings(anthropic_api_key=api_key, claude_model=model))

        if host == "openai":
            from analysis.openai_analyser import OpenAIAnalyser
            return OpenAIAnalyser(Settings(openai_api_key=api_key, openai_model=model))

        if host == "openrouter":
            from analysis.openrouter_analyser import OpenRouterAnalyser
            return OpenRouterAnalyser(Settings(openrouter_api_key=api_key, openrouter_model=model))

        logger.warning("Unsupported LLM host: %s", host)
        return None

    async def _refresh_analysers(self) -> None:
        """Re-initialise analysers from the DB model registry.

        Called when LLM models are added/removed/updated via the API.
        Updates the analyser dict, report generator, and consensus
        generator in place so running services pick up the changes.
        """
        from dashboard.deps import set_state

        new_analysers = await self._init_analysers_from_db()

        # Update the shared analyser dict in-place
        self._analysers.clear()
        self._analysers.update(new_analysers)

        # Re-create generators with updated analysers
        from analysis.report_generator import ReportGenerator
        from analysis.consensus_generator import ConsensusGenerator
        new_report_gen = ReportGenerator(self._analysers, self.settings)
        new_consensus_gen = ConsensusGenerator(self._analysers, self.settings)

        # Update dashboard deps
        set_state("analysers", self._analysers)
        set_state("report_generator", new_report_gen)
        set_state("consensus_generator", new_consensus_gen)

        # Update the pipeline references
        self._report_gen = new_report_gen
        self._consensus_gen = new_consensus_gen

        logger.info("LLM analysers refreshed", count=len(self._analysers))

    async def _migrate_legacy_llm_settings(self) -> None:
        """Auto-migrate old flat LLM settings to the new model registry.

        On first boot after the upgrade, if the llm_models table is empty
        but old-style API keys exist in Settings (from env vars or DB),
        create model entries automatically so the user doesn't lose their
        configuration.
        """
        from db.models import LLMModelORM, generate_id
        from sqlalchemy import select, func

        async with self.db.session() as session:
            count = await session.scalar(
                select(func.count()).select_from(LLMModelORM)
            )
            if count and count > 0:
                return  # Models already exist, skip migration

        # Map old settings to (host, model_field, key_field)
        legacy_providers = [
            ("groq", self.settings.groq_model, self.settings.groq_api_key),
            ("gemini", self.settings.gemini_model, self.settings.gemini_api_key),
            ("anthropic", self.settings.claude_model, self.settings.anthropic_api_key),
            ("openai", self.settings.openai_model, self.settings.openai_api_key),
            ("openrouter", self.settings.openrouter_model, self.settings.openrouter_api_key),
        ]

        host_labels = {
            "openai": "OpenAI",
            "openrouter": "OpenRouter",
            "gemini": "Gemini",
            "groq": "Groq",
            "anthropic": "Anthropic",
        }

        migrated = []
        first_model_id = ""

        async with self.db.session() as session:
            for host, model, api_key in legacy_providers:
                if not api_key:
                    continue  # No key configured for this provider

                model_id = generate_id()
                label = host_labels.get(host, host.title())
                display_name = f"{label} / {model}" if model else f"{label} / (default)"

                orm = LLMModelORM(
                    id=model_id,
                    host=host,
                    model=model or "",
                    api_key=api_key,
                    display_name=display_name,
                    enabled=True,
                )
                session.add(orm)
                migrated.append(display_name)

                if not first_model_id:
                    first_model_id = model_id

            if migrated:
                await session.commit()
                logger.info(
                    "Migrated %d legacy LLM provider(s) to model registry: %s",
                    len(migrated), migrated,
                )

                # Set the first model as default for all roles if not already set
                if first_model_id and not self.settings.llm_announcement_model_id:
                    self.settings.llm_announcement_model_id = first_model_id
                    self.settings.llm_sentiment_model_id = first_model_id
                    self.settings.llm_consensus_leader_model_id = first_model_id

                    # Persist all role assignments in a single session
                    from db.models import SettingORM
                    async with self.db.session() as s2:
                        for key in (
                            "llm_announcement_model_id",
                            "llm_sentiment_model_id",
                            "llm_consensus_leader_model_id",
                        ):
                            existing = await s2.get(SettingORM, key)
                            if existing:
                                existing.value = first_model_id
                            else:
                                s2.add(SettingORM(key=key, value=first_model_id))
                        await s2.commit()

    # --- Service loops ---

    async def _heartbeat(self) -> None:
        """Periodic health check log."""
        while not self._shutdown_event.is_set():
            logger.debug(
                "Heartbeat",
                events_published=self.event_bus.event_count,
                subscribers=self.event_bus.subscriber_counts,
            )
            await asyncio.sleep(60)

    async def _rf_refresh_loop(self, rf_fetcher: Any) -> None:
        """Refresh G10 risk-free rates daily from central bank APIs."""
        while not self._shutdown_event.is_set():
            try:
                await rf_fetcher.refresh_today()
                logger.info("Risk-free rates refreshed")
            except Exception as e:
                logger.error("Risk-free rate refresh failed: %s", e)
            await asyncio.sleep(86_400)

    async def _alert_pipeline(
        self,
        sentiment_agg: Any,
        sec_8k_source: Any,
    ) -> None:
        """React to momentum alerts.

        Flow: MOMENTUM_ALERT → fetch sentiment + 8-K filings concurrently
              → generate report (single or consensus) → save to DB
              → publish REPORT_READY

        Uses self._report_gen and self._consensus_gen so that hot-reloaded
        analysers are picked up without restarting the pipeline.
        """
        async for event in self.event_bus.subscribe(EventType.MOMENTUM_ALERT):
            alert: AlertSignal = event.data
            logger.info("Processing alert", ticker=alert.ticker, change=alert.change_pct)

            try:
                # 1. Fetch sentiment and 8-K filings concurrently
                sentiment_task = sentiment_agg.fetch(alert.ticker)
                filings_task = sec_8k_source.fetch(alert.ticker)
                sentiment, filings = await asyncio.gather(
                    sentiment_task, filings_task, return_exceptions=False,
                )

                # 2. Generate report (both analysis types)
                if self.settings.llm_mode.value == "consensus":
                    report = await self._consensus_gen.generate(
                        alert, sentiment, filings=filings,
                    )
                else:
                    report = await self._report_gen.generate(
                        alert, sentiment, filings=filings,
                    )

                # 3. Save to database
                await self._save_report(report)

                # 4. Push to Telegram + Dashboard via event bus
                await self.event_bus.publish(
                    EventType.REPORT_READY, report, source="alert_pipeline"
                )

                logger.info(
                    "Report generated",
                    ticker=alert.ticker,
                    recommendation=report.final_recommendation.value,
                    announcement_score=report.announcement_score,
                    sentiment_score=report.sentiment_score,
                )
            except Exception as e:
                logger.error("Alert pipeline failed for %s: %s", alert.ticker, e)
                await self.event_bus.publish(
                    EventType.SYSTEM_ERROR,
                    {"ticker": alert.ticker, "error": str(e)},
                    source="alert_pipeline",
                )

    async def _position_monitor(self, broker: Any) -> None:
        """Poll broker positions and publish updates."""
        while not self._shutdown_event.is_set():
            try:
                positions = await broker.get_positions()
                if positions:
                    await self.event_bus.publish(
                        EventType.POSITION_UPDATE,
                        [p.model_dump() for p in positions],
                        source="position_monitor",
                    )

                    # Check stop-loss thresholds
                    for pos in positions:
                        if pos.unrealised_pnl_pct <= -self.settings.default_stop_loss_pct:
                            await self.event_bus.publish(
                                EventType.POSITION_STOP_LOSS,
                                pos.model_dump(),
                                source="position_monitor",
                            )
                            logger.warning(
                                "Stop-loss threshold hit",
                                ticker=pos.ticker,
                                pnl_pct=pos.unrealised_pnl_pct,
                            )
            except Exception as e:
                logger.error("Position monitor error: %s", e)

            await asyncio.sleep(30)

    async def _save_report(self, report: AnalysisReport) -> None:
        """Persist a report to the database."""
        if not self.db:
            return

        # Use sentiment_score as final_score for DB, fallback to announcement
        final_score = report.sentiment_score or report.announcement_score or 0.0

        orm = ReportORM(
            id=report.id,
            ticker=report.ticker,
            mode=report.mode,
            alert_price=report.alert.price,
            alert_change_pct=report.alert.change_pct,
            alert_volume=report.alert.volume,
            final_recommendation=report.final_recommendation.value,
            final_score=final_score,
            final_confidence=report.final_confidence,
            # Legacy fraud columns — hardcoded for DB compat
            fraud_risk_level="LOW",
            fraud_risk_score=0.0,
            fraud_flags="[]",
            reddit_mentions=report.sentiment.reddit_mention_count,
            stocktwits_bullish=report.sentiment.stocktwits_bullish_count,
            stocktwits_bearish=report.sentiment.stocktwits_bearish_count,
            insider_buys=report.sentiment.insider_buy_count,
            insider_sells=report.sentiment.insider_sell_count,
            news_count=len(report.sentiment.news_articles),
            report_json=report.model_dump_json(),
        )

        async with self.db.session() as session:
            session.add(orm)
            await session.commit()

    def shutdown(self) -> None:
        """Trigger graceful shutdown."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()


def cli_entry() -> None:
    """CLI entry point (called by `florin` command)."""
    app = Florin()

    # Handle Ctrl+C and SIGTERM gracefully
    loop = asyncio.new_event_loop()

    def _signal_handler() -> None:
        app.shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        loop.run_until_complete(app.start())
    except KeyboardInterrupt:
        app.shutdown()
        loop.run_until_complete(asyncio.sleep(0.5))
    finally:
        loop.close()


if __name__ == "__main__":
    cli_entry()
