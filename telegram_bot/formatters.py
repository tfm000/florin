"""
Telegram message formatting utilities.

All messages use Markdown V2 formatting as required by aiogram.
"""

from __future__ import annotations

from core.models import (
    AccountSummary,
    AnalysisReport,
    AnalysisResult,
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


def format_alert_message(
    report: AnalysisReport,
    broker_summary: AccountSummary | None = None,
    open_position_count: int = 0,
    default_order_size: str = "",
) -> str:
    """Format an analysis report as a Telegram alert message with account context."""
    alert = report.alert

    # Header with emoji based on recommendation
    rec = report.final_recommendation
    rec_emoji = _recommendation_emoji(rec)

    ticker = escape_md(alert.ticker)
    price = escape_md(f"${alert.price:.4f}")
    change = escape_md(f"{alert.change_pct:+.2f}%")

    lines = [
        f"{rec_emoji} *ALERT: ${ticker}* {change} \\| {price}",
        escape_md("━" * 25),
    ]

    # Announcement analysis score
    ann = report.get_best_announcement()
    if ann and not ann.error:
        ann_score = escape_md(f"{ann.score:.1f}/10")
        ann_conf = escape_md(f"{ann.confidence:.0%}")
        lines.append(f"📄 *Announcement:* {ann_score} \\({ann_conf} confidence\\)")

    # Sentiment analysis score
    sent = report.get_best_sentiment()
    if sent and not sent.error:
        sent_score = escape_md(f"{sent.score:.1f}/10")
        sent_conf = escape_md(f"{sent.confidence:.0%}")
        lines.append(f"📱 *Sentiment:* {sent_score} \\({sent_conf} confidence\\)")

    # Source counts
    s = report.sentiment
    sources = []
    if s.reddit_mention_count > 0:
        sources.append(f"Reddit\\({escape_md(str(s.reddit_mention_count))}\\)")
    if s.apewisdom_mentions > 0:
        sources.append(f"ApeWisdom\\({escape_md(str(s.apewisdom_mentions))}\\)")
    if s.alphavantage_articles:
        sources.append(f"AlphaVantage\\({escape_md(str(len(s.alphavantage_articles)))}\\)")
    if s.sec_filings:
        sources.append(f"SEC\\({escape_md(str(len(s.sec_filings)))}\\)")
    if s.news_articles:
        sources.append(f"News\\({escape_md(str(len(s.news_articles)))}\\)")
    lines.append(f"🔍 *Sources:* {', '.join(sources) if sources else 'None'}")

    # Recommendation
    rec_str = escape_md(rec.value.replace("_", " "))
    lines.append(f"🤖 *Recommendation:* {rec_str}")

    # Key signals from best available analysis
    best_analysis = sent or ann
    if best_analysis and not best_analysis.error:
        lines.append("")
        lines.append("*Key Signals:*")
        for signal in (best_analysis.bullish_signals or [])[:3]:
            lines.append(f"  • ✅ {escape_md(signal)}")
        for signal in (best_analysis.bearish_signals or [])[:3]:
            lines.append(f"  • ⚠️ {escape_md(signal)}")

    # Account context (if provided)
    if broker_summary or open_position_count or default_order_size:
        lines.append("")
        if broker_summary:
            acc_val = escape_md(f"{broker_summary.currency} {broker_summary.total_value:,.2f}")
            cash = escape_md(f"{broker_summary.currency} {broker_summary.cash_available:,.2f}")
            lines.append(f"💰 *Account:* {acc_val} \\({cash} cash\\)")
        if open_position_count > 0:
            lines.append(f"📦 *Positions:* {escape_md(str(open_position_count))} open")
        if default_order_size:
            lines.append(f"💷 *Default Order:* {escape_md(default_order_size)}")

    # Mode indicator
    if report.mode == "consensus":
        n_ann = len([a for a in report.announcement_analyses if not a.error])
        n_sent = len([a for a in report.sentiment_analyses if not a.error])
        total = max(n_ann, n_sent)
        lines.append(f"\n_Consensus from {escape_md(str(total))} LLMs_")

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


def format_screener_alert_message(alert_data: dict) -> str:
    """
    Format a screener alert as a Telegram message.

    Args:
        alert_data: Dict from SCREENER_ALERT event containing:
            screener_name, ticker, name, price, change_pct,
            market_cap, volume, sector, exchange, filters_summary.
    """
    ticker = escape_md(alert_data.get("ticker", ""))
    name = escape_md(alert_data.get("name", ""))
    screener_name = escape_md(alert_data.get("screener_name", ""))
    price = alert_data.get("price")
    change_pct = alert_data.get("change_pct")
    market_cap = alert_data.get("market_cap")
    volume = alert_data.get("volume")
    sector = alert_data.get("sector", "")
    exchange = alert_data.get("exchange", "")
    filters_summary = escape_md(alert_data.get("filters_summary", ""))

    # Header
    change_str = ""
    if change_pct is not None:
        emoji = "\U0001f4c8" if change_pct >= 0 else "\U0001f4c9"
        change_str = f" {emoji} {escape_md(f'{change_pct:+.2f}%')}"

    lines = [
        f"\U0001f50d *Screener Alert: ${ticker}*{change_str}",
        f"_{screener_name}_",
        escape_md("\u2501" * 25),
    ]

    # Details
    if name:
        lines.append(f"\U0001f3f7 *Name:* {name}")
    if price is not None:
        lines.append(f"\U0001f4b5 *Price:* {escape_md(f'${price:.2f}')}")
    if market_cap is not None:
        lines.append(f"\U0001f3e6 *Mkt Cap:* {escape_md(_format_mcap(market_cap))}")
    if volume is not None:
        lines.append(f"\U0001f4ca *Volume:* {escape_md(_format_volume(volume))}")
    if sector:
        lines.append(f"\U0001f3ed *Sector:* {escape_md(sector)}")
    if exchange:
        lines.append(f"\U0001f3e2 *Exchange:* {escape_md(exchange)}")

    # Filter summary
    if filters_summary:
        lines.append(f"\n\U0001f50e *Matched:* {filters_summary}")

    return "\n".join(lines)


def _format_mcap(val: float) -> str:
    """Format market cap with T/B/M suffix."""
    if val >= 1e12:
        return f"${val / 1e12:.1f}T"
    if val >= 1e9:
        return f"${val / 1e9:.1f}B"
    if val >= 1e6:
        return f"${val / 1e6:.0f}M"
    return f"${val:,.0f}"


def _format_volume(val: int) -> str:
    """Format volume with B/M/K suffix."""
    if val >= 1e9:
        return f"{val / 1e9:.1f}B"
    if val >= 1e6:
        return f"{val / 1e6:.1f}M"
    if val >= 1e3:
        return f"{val / 1e3:.0f}K"
    return f"{val:,}"


def _recommendation_emoji(rec: Recommendation) -> str:
    return {
        Recommendation.STRONG_BUY: "🚀",
        Recommendation.BUY: "📈",
        Recommendation.HOLD: "⏸",
        Recommendation.AVOID: "⚠️",
        Recommendation.STRONG_AVOID: "🛑",
    }.get(rec, "❓")


