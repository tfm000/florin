"""Market hours API — which global markets are currently open or closed."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["market_hours"])


class MarketStatus(BaseModel):
    name: str
    region: str
    is_open: bool
    local_time: str
    opens: str
    closes: str
    timezone: str


class MarketHoursResponse(BaseModel):
    utc_now: str
    markets: list[MarketStatus]


# (name, region, timezone, open_hour, open_min, close_hour, close_min, weekdays_only)
_MARKETS = [
    ("NYSE / NASDAQ", "US", "America/New_York", 9, 30, 16, 0, True),
    ("London (LSE)", "Europe", "Europe/London", 8, 0, 16, 30, True),
    ("Frankfurt (XETRA)", "Europe", "Europe/Berlin", 9, 0, 17, 30, True),
    ("Tokyo (TSE)", "Asia", "Asia/Tokyo", 9, 0, 15, 0, True),
    ("Hong Kong (HKEX)", "Asia", "Asia/Hong_Kong", 9, 30, 16, 0, True),
    ("Shanghai (SSE)", "Asia", "Asia/Shanghai", 9, 30, 15, 0, True),
    ("Sydney (ASX)", "Asia-Pacific", "Australia/Sydney", 10, 0, 16, 0, True),
    ("Toronto (TSX)", "Americas", "America/Toronto", 9, 30, 16, 0, True),
    ("Crypto", "Global", "UTC", 0, 0, 0, 0, False),  # 24/7
    ("Forex", "Global", "UTC", 0, 0, 0, 0, False),  # ~24/5
]


def _is_forex_open(now_utc: datetime) -> bool:
    """Forex trades Sun 5 PM ET – Fri 5 PM ET."""
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    wd = et.weekday()  # 0=Mon..6=Sun
    t = et.time()
    if wd == 4 and t >= time(17, 0):  # Fri after 5 PM
        return False
    if wd == 5:  # Saturday
        return False
    if wd == 6 and t < time(17, 0):  # Sun before 5 PM
        return False
    return True


def _check_open(
    tz_name: str, oh: int, om: int, ch: int, cm: int,
    weekdays_only: bool, now_utc: datetime,
) -> bool:
    local = now_utc.astimezone(ZoneInfo(tz_name))
    if weekdays_only and local.weekday() >= 5:
        return False
    t = local.time()
    return time(oh, om) <= t < time(ch, cm)


@router.get("/market/hours", response_model=MarketHoursResponse)
async def get_market_hours():
    """Return open/closed status for major global markets."""
    now = datetime.now(UTC)
    markets: list[MarketStatus] = []

    for name, region, tz, oh, om, ch, cm, wd_only in _MARKETS:
        tz_obj = ZoneInfo(tz)
        local = now.astimezone(tz_obj)

        if name == "Crypto":
            is_open = True
            opens_str = "24/7"
            closes_str = "24/7"
        elif name == "Forex":
            is_open = _is_forex_open(now)
            opens_str = "Sun 5:00 PM ET"
            closes_str = "Fri 5:00 PM ET"
        else:
            is_open = _check_open(tz, oh, om, ch, cm, wd_only, now)
            opens_str = f"{oh}:{om:02d}"
            closes_str = f"{ch}:{cm:02d}"

        markets.append(MarketStatus(
            name=name,
            region=region,
            is_open=is_open,
            local_time=local.strftime("%H:%M"),
            opens=opens_str,
            closes=closes_str,
            timezone=tz,
        ))

    return MarketHoursResponse(
        utc_now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        markets=markets,
    )


# Exchange → market name mapping for per-asset lookups
_EXCHANGE_TO_MARKET: dict[str, str] = {
    # US
    "NMS": "NYSE / NASDAQ", "NGM": "NYSE / NASDAQ", "NCM": "NYSE / NASDAQ",
    "NYQ": "NYSE / NASDAQ", "ASE": "NYSE / NASDAQ", "PCX": "NYSE / NASDAQ",
    "BTS": "NYSE / NASDAQ", "NASDAQ": "NYSE / NASDAQ", "NYSE": "NYSE / NASDAQ",
    # London
    "LSE": "London (LSE)", "LON": "London (LSE)", "IOB": "London (LSE)",
    # Frankfurt
    "GER": "Frankfurt (XETRA)", "FRA": "Frankfurt (XETRA)",
    # Tokyo
    "JPX": "Tokyo (TSE)", "TYO": "Tokyo (TSE)",
    # Hong Kong
    "HKG": "Hong Kong (HKEX)",
    # Shanghai
    "SHH": "Shanghai (SSE)", "SHZ": "Shanghai (SSE)",
    # Sydney
    "ASX": "Sydney (ASX)", "AX": "Sydney (ASX)",
    # Toronto
    "TOR": "Toronto (TSX)", "TSX": "Toronto (TSX)", "CNQ": "Toronto (TSX)",
}


class AssetMarketStatus(BaseModel):
    market_name: str
    is_open: bool
    local_time: str
    opens: str
    closes: str


@router.get("/market/status/{exchange}", response_model=AssetMarketStatus)
async def get_exchange_status(exchange: str):
    """Return open/closed status for a specific exchange."""
    now = datetime.now(UTC)
    exchange_upper = exchange.upper()

    market_name = _EXCHANGE_TO_MARKET.get(exchange_upper)

    if not market_name:
        # Check if it's a crypto or forex ticker pattern
        if exchange_upper in ("CCC", "CCY"):
            market_name = "Crypto"
        else:
            market_name = "NYSE / NASDAQ"  # default fallback

    for name, _region, tz, oh, om, ch, cm, wd_only in _MARKETS:
        if name != market_name:
            continue

        tz_obj = ZoneInfo(tz)
        local = now.astimezone(tz_obj)

        if name == "Crypto":
            return AssetMarketStatus(
                market_name=name, is_open=True,
                local_time=local.strftime("%H:%M"),
                opens="24/7", closes="24/7",
            )
        if name == "Forex":
            return AssetMarketStatus(
                market_name=name, is_open=_is_forex_open(now),
                local_time=local.strftime("%H:%M"),
                opens="Sun 5:00 PM ET", closes="Fri 5:00 PM ET",
            )

        is_open = _check_open(tz, oh, om, ch, cm, wd_only, now)
        return AssetMarketStatus(
            market_name=name, is_open=is_open,
            local_time=local.strftime("%H:%M"),
            opens=f"{oh}:{om:02d}", closes=f"{ch}:{cm:02d}",
        )

    # Fallback
    return AssetMarketStatus(
        market_name="Unknown", is_open=False,
        local_time="", opens="", closes="",
    )
