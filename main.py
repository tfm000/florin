"""
Sentinel Terminal — Main Entry Point

Starts all services:
  1. Database initialisation
  2. Market data connection
  3. Penny stock scanner
  4. Alert processing pipeline
  5. Position monitoring
  6. Telegram bot
  7. Web dashboard

All services run concurrently via asyncio.gather().
"""

from __future__ import annotations

import asyncio
import json
import signal
from typing import Any

from config.settings import LLMProvider, get_settings
from core.events import EventBus, EventType
from core.logging import get_logger, setup_logging
from core.models import AlertSignal, AnalysisReport
from db.database import Database
from db.models import ReportORM

logger = get_logger(__name__)


class Sentinel:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.event_bus = EventBus()
        self.db: Database | None = None
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Initialise and start all services."""
        setup_logging(self.settings.log_level, self.settings.app_env)
        logger.info(
            "Starting Sentinel Terminal",
            env=self.settings.app_env.value,
            llm_mode=self.settings.llm_mode.value,
            price_range=f"${self.settings.scan_price_min:.2f}-${self.settings.scan_price_max:.2f}",
            momentum_threshold=self.settings.scan_momentum_threshold,
            paper_trading=self.settings.paper_trading,
        )

        # --- Database ---
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

        # yfinance provider (always available, no API key needed)
        from data.yfinance_provider import YFinanceProvider
        yfinance_provider = YFinanceProvider()

        # Universe manager
        from scanner.universe import UniverseManager
        universe = UniverseManager(self.settings, self.db, data_provider, yfinance_provider)

        # Scanner
        scanner = None
        if data_provider:
            from scanner.momentum_scanner import MomentumScanner
            scanner = MomentumScanner(self.settings, data_provider, universe)

        # Sentiment aggregator
        sentiment_agg = self._init_sentiment()

        # LLM analysers
        analysers = self._init_analysers()

        # Report generators
        from analysis.report_generator import ReportGenerator
        from analysis.consensus_generator import ConsensusGenerator
        report_gen = ReportGenerator(analysers, self.settings)
        consensus_gen = ConsensusGenerator(analysers, self.settings)

        # Fraud detector
        from analysis.fraud_detector import FraudDetector
        fraud_detector = FraudDetector()

        # Telegram bot
        telegram_bot = None
        if self.settings.telegram_configured:
            from telegram_bot.bot import SentinelBot
            telegram_bot = SentinelBot(self.settings, self.event_bus, broker)
            await telegram_bot.setup()
            logger.info("Telegram bot initialised")

        # Dashboard
        from dashboard.app import create_app, serve as dashboard_serve
        from dashboard.deps import set_state
        set_state("shutdown_callback", self.shutdown)
        set_state("universe", universe)
        set_state("scanner", scanner)
        set_state("data_provider", data_provider)
        set_state("yfinance_provider", yfinance_provider)
        set_state("analysers", analysers)
        set_state("report_generator", report_gen)
        set_state("consensus_generator", consensus_gen)
        set_state("fraud_detector", fraud_detector)
        set_state("sentiment_aggregator", sentiment_agg)
        from stats.risk_free import RiskFreeRateFetcher
        rf_fetcher = RiskFreeRateFetcher(self.db)
        set_state("rf_fetcher", rf_fetcher)
        dashboard_app = create_app(self.settings, self.db, self.event_bus, broker)

        # --- Build service list ---
        services: list[asyncio.Task] = []

        # Heartbeat
        services.append(asyncio.create_task(self._heartbeat(), name="heartbeat"))

        # Universe refresh
        services.append(asyncio.create_task(
            self._universe_refresh_loop(universe), name="universe-refresh"
        ))

        # Risk-free rate daily refresh
        services.append(asyncio.create_task(
            self._rf_refresh_loop(rf_fetcher), name="rf-refresh"
        ))

        # Scanner
        if scanner:
            services.append(asyncio.create_task(
                scanner.run(self.event_bus), name="scanner"
            ))
            logger.info("Scanner started")

        # Alert pipeline
        services.append(asyncio.create_task(
            self._alert_pipeline(
                sentiment_agg, report_gen, consensus_gen, fraud_detector
            ),
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
            from telegram_bot.handlers.alerts import alert_listener
            services.append(asyncio.create_task(
                alert_listener(self.event_bus, telegram_bot, broker, self.settings),
                name="telegram-alerts",
            ))

        # Dashboard
        services.append(asyncio.create_task(
            dashboard_serve(dashboard_app, self.settings), name="dashboard"
        ))

        # Market breadth scanner (hourly during market hours)
        from scanner.breadth_scanner import breadth_scan_loop
        services.append(asyncio.create_task(
            breadth_scan_loop(self.db, yfinance_provider, data_provider),
            name="breadth-scanner",
        ))

        # WebSocket event bridge
        from dashboard.ws import event_bridge
        from dashboard.deps import get_ws_manager
        services.append(asyncio.create_task(
            event_bridge(self.event_bus, get_ws_manager()), name="ws-bridge"
        ))

        self._tasks = services
        logger.info("Sentinel started — %d service(s) running", len(services))

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

        logger.info("Sentinel shut down cleanly")

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
            StockTwitsSource(),
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

        return SentimentAggregator(sources)

    def _init_analysers(self) -> dict[str, Any]:
        """Initialise available LLM analysers."""
        analysers: dict[str, Any] = {}
        enabled = self.settings.get_enabled_llm_providers()

        if LLMProvider.FINBERT in enabled:
            from analysis.finbert_analyser import FinBERTAnalyser
            analysers["finbert"] = FinBERTAnalyser()

        if LLMProvider.OLLAMA in enabled:
            from analysis.ollama_analyser import OllamaAnalyser
            analysers["ollama"] = OllamaAnalyser(self.settings)

        if LLMProvider.GROQ in enabled:
            from analysis.groq_analyser import GroqAnalyser
            analysers["groq"] = GroqAnalyser(self.settings)

        if LLMProvider.GEMINI in enabled:
            from analysis.gemini_analyser import GeminiAnalyser
            analysers["gemini"] = GeminiAnalyser(self.settings)

        if LLMProvider.CLAUDE in enabled:
            from analysis.claude_analyser import ClaudeAnalyser
            analysers["claude"] = ClaudeAnalyser(self.settings)

        logger.info("LLM analysers initialised", analysers=list(analysers.keys()))
        return analysers

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

    async def _universe_refresh_loop(self, universe: Any) -> None:
        """Refresh the penny stock universe periodically."""
        while not self._shutdown_event.is_set():
            try:
                await universe.refresh()
                logger.info("Universe refreshed", count=universe.size)
            except Exception as e:
                logger.error("Universe refresh failed: %s", e)
            # Refresh daily
            await asyncio.sleep(86_400)

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
        report_gen: Any,
        consensus_gen: Any,
        fraud_detector: Any,
    ) -> None:
        """
        React to momentum alerts.

        Flow: MOMENTUM_ALERT → scrape sentiment → assess fraud
              → generate report (single or consensus) → save to DB
              → publish REPORT_READY
        """
        async for event in self.event_bus.subscribe(EventType.MOMENTUM_ALERT):
            alert: AlertSignal = event.data
            logger.info("Processing alert", ticker=alert.ticker, change=alert.change_pct)

            try:
                # 1. Scrape sentiment
                sentiment = await sentiment_agg.fetch(alert.ticker)

                # 2. Assess fraud risk
                fraud_risk = await fraud_detector.assess(alert, sentiment)

                # 3. Generate report
                if self.settings.llm_mode.value == "consensus":
                    report = await consensus_gen.generate(alert, sentiment, fraud_risk)
                else:
                    report = await report_gen.generate(alert, sentiment, fraud_risk)

                # 4. Save to database
                await self._save_report(report)

                # 5. Push to Telegram + Dashboard via event bus
                await self.event_bus.publish(
                    EventType.REPORT_READY, report, source="alert_pipeline"
                )

                logger.info(
                    "Report generated",
                    ticker=alert.ticker,
                    recommendation=report.final_recommendation.value,
                    score=report.final_score,
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

        orm = ReportORM(
            id=report.id,
            ticker=report.ticker,
            mode=report.mode,
            alert_price=report.alert.price,
            alert_change_pct=report.alert.change_pct,
            alert_volume=report.alert.volume,
            final_recommendation=report.final_recommendation.value,
            final_score=report.final_score,
            final_confidence=report.final_confidence,
            fraud_risk_level=report.fraud_risk.risk_level.value,
            fraud_risk_score=report.fraud_risk.score,
            fraud_flags=json.dumps(report.fraud_risk.flags),
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
    """CLI entry point (called by `sentinel` command)."""
    app = Sentinel()

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
