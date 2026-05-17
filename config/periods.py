"""Shared period vocabulary, loaded from config/periods.json at module-import time.

Source of truth: config/periods.json. Both this Python wrapper and
dashboard_ui/src/utils/periods.js import that file directly so the frontend
period buttons and the backend FastAPI route validators cannot drift.

The Literal aliases enable FastAPI to auto-generate OpenAPI enum schemas and
mypy to narrow `period` arguments inside route handlers. The
`# type: ignore[valid-type]` is required because mypy 2.x does not yet
implement PEP 646 variadic-Literal unpacking; Pydantic and FastAPI both
accept it at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

_PERIODS_PATH = Path(__file__).resolve().parent / "periods.json"

_P = json.loads(_PERIODS_PATH.read_text())

HISTORICAL_PERIODS: tuple[str, ...] = tuple(_P["historical"])
INTRADAY_PERIODS: tuple[str, ...] = tuple(_P["intraday"])
INTRADAY_TO_HISTORY: dict[str, dict[str, str]] = dict(_P["intraday_to_history"])

# FastAPI route handlers use these as query-param annotations.
HistoricalPeriod = Literal[*HISTORICAL_PERIODS]  # type: ignore[valid-type]
IntradayPeriod = Literal[*INTRADAY_PERIODS]  # type: ignore[valid-type]

# Per-endpoint subsets — each is a strict subset of the canonical vocabulary
# that some backend routes legitimately need to accept (e.g. yfinance does
# not serve yield-curve data beyond 5y; sectors keeps shorthand support
# for the current SectorPerformanceChart consumer). New code should reach
# for HistoricalPeriod unless a narrower contract is explicitly required.

YIELD_CURVE_PERIODS: tuple[str, ...] = ("1mo", "3mo", "6mo", "1y", "2y", "5y")
YieldCurvePeriod = Literal[*YIELD_CURVE_PERIODS]  # type: ignore[valid-type]

# Sectors accept both canonical (1mo/3mo/6mo) and legacy shorthand
# (1m/3m/6m) — the route normalises shorthand to yfinance form in-handler.
# Shorthand support is kept for now; AUDIT-01 confirms whether
# SectorPerformanceChart still sends it before any cleanup.
SECTOR_PERIODS: tuple[str, ...] = ("1mo", "3mo", "6mo", "1y", "1m", "3m", "6m")
SectorPeriod = Literal[*SECTOR_PERIODS]  # type: ignore[valid-type]
