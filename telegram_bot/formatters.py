"""
Telegram message formatting utilities.

All messages use Markdown V2 formatting as required by aiogram.
"""

from __future__ import annotations

from core.models import (
    AccountSummary,
    AnalysisReport,
    FraudRisk,
    LLMAnalysis,
    Position,
    Recommendation,
)


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    result = []
    for ch in str(text):
        if ch in special:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def format_alert_message(report: AnalysisReport) -> str:
    """Format an analysis report as a Telegram alert message."""
    alert = report.alert
    analysis = report.get_best_analysis()

    # Header with emoji based on recommendation
    rec = report.final_recommendation
    rec_emoji = _recommendation_emoji(rec)

    ticker = escape_md(alert.ticker)
    price = escape_md(f"${alert.price:.4f}")
    change = escape_md(f"{alert.change_pct:+.2f}%")
    volume = escape_md(f"{alert.volume:,}")

    lines = [
        f"{rec_emoji} *ALERT: ${ticker}* {change} \\| {price}",
        escape_md("━" * 25),
    ]

    # Sentiment summary
    score_str = escape_md(f"{report.final_score:.1f}/10")
    conf_str = escape_md(f"{report.final_confidence:.0%}")
    lines.append(f"📊 *Sentiment:* {score_str} \\({conf_str} confidence\\)")

    # Source counts
    s = report.sentiment
    sources = []
    if s.reddit_mention_count > 0:
        sources.append(f"Reddit\\({escape_md(str(s.reddit_mention_count))}\\)")
    st_total = s.stocktwits_bullish_count + s.stocktwits_bearish_count
    if st_total > 0:
        sources.append(f"StockTwits\\({escape_md(str(st_total))}\\)")
    if s.sec_filings:
        sources.append(f"SEC\\({escape_md(str(len(s.sec_filings)))}\\)")
    if s.news_articles:
        sources.append(f"News\\({escape_md(str(len(s.news_articles)))}\\)")
    lines.append(f"🔍 *Sources:* {', '.join(sources) if sources else 'None'}")

    # Fraud risk
    fraud = report.fraud_risk
    fraud_emoji = _fraud_emoji(fraud.risk_level)
    fraud_str = escape_md(f"{fraud.risk_level.value} ({fraud.score:.1f}/10)")
    lines.append(f"{fraud_emoji} *Fraud Risk:* {fraud_str}")

    # Recommendation
    rec_str = escape_md(rec.value.replace("_", " "))
    lines.append(f"🤖 *Recommendation:* {rec_str}")

    # Key signals
    if analysis:
        lines.append("")
        lines.append("*Key Signals:*")
        for signal in (analysis.bullish_signals or [])[:3]:
            lines.append(f"  • ✅ {escape_md(signal)}")
        for signal in (analysis.bearish_signals or [])[:3]:
            lines.append(f"  • ⚠️ {escape_md(signal)}")

    # Mode indicator
    if report.mode == "consensus":
        n = len([a for a in report.individual_analyses if not a.error])
        lines.append(f"\n_Consensus from {escape_md(str(n))} LLMs_")

    return "\n".join(lines)


def format_position_message(pos: Position) -> str:
    """Format a single position for display."""
    ticker = escape_md(pos.ticker)
    qty = escape_md(f"{pos.quantity:.4f}")
    avg = escape_md(f"${pos.avg_price:.4f}")
    cur = escape_md(f"${pos.current_price:.4f}")
    pnl = pos.unrealised_pnl
    pnl_pct = pos.unrealised_pnl_pct
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    pnl_str = escape_md(f"${pnl:+.2f} ({pnl_pct:+.1f}%)")

    return (
        f"*{ticker}* {pnl_emoji}\n"
        f"  Qty: {qty} @ {avg}\n"
        f"  Now: {cur}\n"
        f"  P&L: {pnl_str}"
    )


def format_positions_list(positions: list[Position]) -> str:
    """Format all open positions."""
    if not positions:
        return "📭 No open positions"

    total_pnl = sum(p.unrealised_pnl for p in positions)
    total_value = sum(p.market_value for p in positions)

    lines = [
        f"📊 *Open Positions* \\({escape_md(str(len(positions)))}\\)",
        escape_md("━" * 25),
    ]

    for pos in positions:
        lines.append(format_position_message(pos))
        lines.append("")

    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    lines.append(escape_md("━" * 25))
    lines.append(
        f"{pnl_emoji} *Total P&L:* {escape_md(f'${total_pnl:+.2f}')}"
    )
    lines.append(
        f"💰 *Market Value:* {escape_md(f'${total_value:.2f}')}"
    )

    return "\n".join(lines)


def format_account_summary(acc: AccountSummary) -> str:
    """Format account summary."""
    return "\n".join([
        "💳 *Account Summary*",
        escape_md("━" * 25),
        f"💵 Cash: {escape_md(f'{acc.currency} {acc.cash_available:.2f}')}",
        f"📈 Invested: {escape_md(f'{acc.currency} {acc.invested_value:.2f}')}",
        f"💰 Total: {escape_md(f'{acc.currency} {acc.total_value:.2f}')}",
        f"📊 Unrealised P&L: {escape_md(f'{acc.currency} {acc.unrealised_pnl:+.2f}')}",
        f"✅ Realised P&L: {escape_md(f'{acc.currency} {acc.realised_pnl:+.2f}')}",
    ])


def format_trade_confirmation(
    ticker: str, side: str, quantity: float, price: float,
) -> str:
    """Format trade confirmation message."""
    emoji = "🟢" if side == "BUY" else "🔴"
    total = quantity * price
    return "\n".join([
        f"{emoji} *Trade Executed*",
        f"  {escape_md(side)} {escape_md(ticker)}",
        f"  Qty: {escape_md(f'{quantity:.4f}')}",
        f"  Price: {escape_md(f'${price:.4f}')}",
        f"  Total: {escape_md(f'${total:.2f}')}",
    ])


def _recommendation_emoji(rec: Recommendation) -> str:
    return {
        Recommendation.STRONG_BUY: "🚀",
        Recommendation.BUY: "📈",
        Recommendation.HOLD: "⏸",
        Recommendation.AVOID: "⚠️",
        Recommendation.STRONG_AVOID: "🛑",
    }.get(rec, "❓")


def _fraud_emoji(risk: FraudRisk) -> str:
    return {
        FraudRisk.LOW: "✅",
        FraudRisk.MEDIUM: "⚠️",
        FraudRisk.HIGH: "🔴",
        FraudRisk.CRITICAL: "🚨",
    }.get(risk, "❓")
