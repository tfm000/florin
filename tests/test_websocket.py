"""Tests for the WebSocket ConnectionManager."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from dashboard.ws import ConnectionManager


def _make_ws(*, fail_send=False):
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    if fail_send:
        ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))
    else:
        ws.send_text = AsyncMock()
    return ws


class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_connect_adds_client(self):
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)
        assert mgr.connection_count == 1
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self):
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        await mgr.broadcast("alerts", {"ticker": "AAPL"})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

        sent = json.loads(ws1.send_text.call_args[0][0])
        assert sent["channel"] == "alerts"
        assert sent["data"]["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_broadcast_no_connections_is_noop(self):
        mgr = ConnectionManager()
        await mgr.broadcast("alerts", {"data": 1})
        # Should not raise

    @pytest.mark.asyncio
    async def test_broadcast_removes_stale_connections(self):
        mgr = ConnectionManager()
        good_ws = _make_ws()
        stale_ws = _make_ws(fail_send=True)
        await mgr.connect(good_ws)
        await mgr.connect(stale_ws)
        assert mgr.connection_count == 2

        await mgr.broadcast("status", {"ok": True})

        assert mgr.connection_count == 1
        good_ws.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_count_property(self):
        mgr = ConnectionManager()
        assert mgr.connection_count == 0
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect(ws1)
        assert mgr.connection_count == 1
        await mgr.connect(ws2)
        assert mgr.connection_count == 2
        mgr.disconnect(ws1)
        assert mgr.connection_count == 1
