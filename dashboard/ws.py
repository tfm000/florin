"""
WebSocket manager for real-time dashboard updates.

Clients connect to /ws and receive JSON messages for:
  - price updates
  - new alerts
  - position changes
  - trade executions
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from core.events import EventBus, EventType

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, channel: str, data: Any) -> None:
        """Send a message to all connected clients."""
        if not self._connections:
            return

        message = json.dumps({"channel": channel, "data": data}, default=str)
        stale: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                logger.debug("WebSocket send failed, marking connection as stale")
                stale.append(ws)

        for ws in stale:
            self._connections.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle a single WebSocket client connection."""
    from dashboard.deps import get_ws_manager

    manager = get_ws_manager()
    await manager.connect(websocket)

    try:
        while True:
            # Keep connection alive — client can send pings or subscribe messages
            data = await websocket.receive_text()
            # For now, we don't process incoming messages
            logger.debug("WebSocket received: %s", data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def event_bridge(event_bus: EventBus, ws_manager: ConnectionManager) -> None:
    """
    Bridge between the event bus and WebSocket clients.

    Subscribes to all events and forwards relevant ones to connected clients.
    Run this as a background task from main.py.
    """
    event_channel_map = {
        EventType.MOMENTUM_ALERT: "alerts",
        EventType.REPORT_READY: "alerts",
        EventType.POSITION_UPDATE: "positions",
        EventType.TRADE_EXECUTED: "trades",
        EventType.TRADE_FAILED: "trades",
        EventType.ACCOUNT_UPDATE: "account",
        EventType.SCANNER_STATUS: "status",
        EventType.PRICE_UPDATE: "prices",
        EventType.MONITOR_UPDATE: "monitor",
        EventType.WATCHLIST_UPDATE: "watchlist",
    }

    async for event in event_bus.subscribe_all():
        channel = event_channel_map.get(event.type)
        if channel and ws_manager.connection_count > 0:
            try:
                payload = event.data
                if hasattr(payload, "model_dump"):
                    payload = payload.model_dump()
                elif hasattr(payload, "__dict__"):
                    payload = payload.__dict__

                await ws_manager.broadcast(
                    channel,
                    {
                        "event_type": event.type.value,
                        "event_id": event.id,
                        "timestamp": str(event.timestamp),
                        "payload": payload,
                    },
                )
            except Exception as e:
                logger.error("Failed to broadcast event %s: %s", event.id, e)
