"""
Simple async event bus using asyncio.Queue.

Provides decoupled pub/sub communication between modules:
  - Scanner publishes MOMENTUM_ALERT
  - Alert pipeline subscribes and processes
  - Report generator publishes REPORT_READY
  - Telegram bot and dashboard subscribe and display

Usage:
    bus = EventBus()

    # Subscribe
    async for event in bus.subscribe("REPORT_READY"):
        handle_report(event.data)

    # Publish
    await bus.publish("REPORT_READY", report)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """All event types in the system."""

    MOMENTUM_ALERT = "MOMENTUM_ALERT"
    SENTIMENT_COLLECTED = "SENTIMENT_COLLECTED"
    REPORT_READY = "REPORT_READY"
    TRADE_EXECUTED = "TRADE_EXECUTED"
    TRADE_FAILED = "TRADE_FAILED"
    POSITION_UPDATE = "POSITION_UPDATE"
    POSITION_STOP_LOSS = "POSITION_STOP_LOSS"
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    SCANNER_STATUS = "SCANNER_STATUS"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    PRICE_UPDATE = "PRICE_UPDATE"
    MONITOR_UPDATE = "MONITOR_UPDATE"
    WATCHLIST_UPDATE = "WATCHLIST_UPDATE"
    SCREENER_ALERT = "SCREENER_ALERT"


@dataclass
class Event:
    """Single event on the bus."""

    type: EventType
    data: Any
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str = ""


class EventBus:
    """
    Async pub/sub event bus.

    Multiple subscribers can listen to the same event type.
    Each subscriber gets its own queue so no messages are lost.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._subscribers: dict[EventType, list[asyncio.Queue[Event]]] = {}
        self._maxsize = maxsize
        self._global_subscribers: list[asyncio.Queue[Event]] = []
        self._event_count: int = 0

    async def publish(self, event_type: EventType, data: Any, source: str = "") -> Event:
        """Publish an event to all subscribers of this type."""
        event = Event(type=event_type, data=data, source=source)
        self._event_count += 1

        logger.debug("Event published: %s (id=%s, source=%s)", event_type.value, event.id, source)

        # Type-specific subscribers
        if event_type in self._subscribers:
            for queue in self._subscribers[event_type]:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "Subscriber queue full for %s — dropping event %s",
                        event_type.value,
                        event.id,
                    )

        # Global subscribers (receive everything)
        for queue in self._global_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Global subscriber queue full — dropping event %s", event.id)

        return event

    def subscribe(self, event_type: EventType) -> _Subscription:
        """
        Subscribe to a specific event type. Returns an async iterator.

        Usage:
            async for event in bus.subscribe(EventType.REPORT_READY):
                process(event.data)
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers[event_type].append(queue)
        return _Subscription(queue, self._subscribers[event_type])

    def subscribe_all(self) -> _Subscription:
        """Subscribe to ALL events. Useful for logging/debugging."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        self._global_subscribers.append(queue)
        return _Subscription(queue, self._global_subscribers)

    async def get(self, event_type: EventType, timeout: float | None = None) -> Event:
        """
        Wait for a single event of the given type.
        Convenience method for one-shot consumption.
        """
        sub = self.subscribe(event_type)
        try:
            return await asyncio.wait_for(sub.queue.get(), timeout=timeout)
        finally:
            sub.unsubscribe()

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def subscriber_counts(self) -> dict[str, int]:
        return {et.value: len(queues) for et, queues in self._subscribers.items()}


class _Subscription:
    """
    Async iterator over events from a subscription.
    Call .unsubscribe() to clean up, or use as context manager.
    """

    def __init__(
        self,
        queue: asyncio.Queue[Event],
        queue_list: list[asyncio.Queue[Event]],
    ) -> None:
        self.queue = queue
        self._queue_list = queue_list

    def unsubscribe(self) -> None:
        """Remove this subscription's queue from the bus."""
        with contextlib.suppress(ValueError):
            self._queue_list.remove(self.queue)

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        return await self.queue.get()

    async def __aenter__(self) -> _Subscription:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.unsubscribe()
