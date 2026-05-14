"""Tests for the async event bus."""

import asyncio

import pytest

from core.events import EventBus, EventType


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_get(self):
        """Single event publish + one-shot get."""
        bus = EventBus()
        await bus.publish(EventType.SCANNER_STATUS, {"status": "ok"})
        # get() subscribes *after* publish, so we need to publish after subscribing
        bus2 = EventBus()

        async def publisher():
            await asyncio.sleep(0.01)
            await bus2.publish(EventType.SCANNER_STATUS, {"status": "ok"})

        asyncio.create_task(publisher())
        event = await bus2.get(EventType.SCANNER_STATUS, timeout=1.0)
        assert event.data == {"status": "ok"}
        assert event.type == EventType.SCANNER_STATUS

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        """Subscriber receives published events."""
        bus = EventBus()
        sub = bus.subscribe(EventType.MOMENTUM_ALERT)

        await bus.publish(EventType.MOMENTUM_ALERT, "alert1")
        await bus.publish(EventType.MOMENTUM_ALERT, "alert2")

        e1 = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        e2 = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        assert e1.data == "alert1"
        assert e2.data == "alert2"
        sub.unsubscribe()

    @pytest.mark.asyncio
    async def test_subscribe_only_receives_matching_type(self):
        """Subscriber only gets events of the subscribed type."""
        bus = EventBus()
        sub = bus.subscribe(EventType.REPORT_READY)

        await bus.publish(EventType.MOMENTUM_ALERT, "wrong type")
        await bus.publish(EventType.REPORT_READY, "correct")

        event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        assert event.data == "correct"
        assert sub.queue.empty()
        sub.unsubscribe()

    @pytest.mark.asyncio
    async def test_subscribe_all_receives_everything(self):
        """Global subscriber gets all event types."""
        bus = EventBus()
        sub = bus.subscribe_all()

        await bus.publish(EventType.MOMENTUM_ALERT, "a")
        await bus.publish(EventType.REPORT_READY, "b")
        await bus.publish(EventType.SYSTEM_ERROR, "c")

        events = []
        for _ in range(3):
            e = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
            events.append(e.type)

        assert EventType.MOMENTUM_ALERT in events
        assert EventType.REPORT_READY in events
        assert EventType.SYSTEM_ERROR in events
        sub.unsubscribe()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Multiple subscribers each get a copy of the event."""
        bus = EventBus()
        sub1 = bus.subscribe(EventType.TRADE_EXECUTED)
        sub2 = bus.subscribe(EventType.TRADE_EXECUTED)

        await bus.publish(EventType.TRADE_EXECUTED, "trade")

        e1 = await asyncio.wait_for(sub1.queue.get(), timeout=1.0)
        e2 = await asyncio.wait_for(sub2.queue.get(), timeout=1.0)
        assert e1.data == "trade"
        assert e2.data == "trade"
        sub1.unsubscribe()
        sub2.unsubscribe()

    @pytest.mark.asyncio
    async def test_queue_overflow_drops_event(self):
        """When queue is full, event is dropped (not blocking)."""
        bus = EventBus(maxsize=2)
        sub = bus.subscribe(EventType.SCANNER_STATUS)

        await bus.publish(EventType.SCANNER_STATUS, "1")
        await bus.publish(EventType.SCANNER_STATUS, "2")
        # This should be dropped (queue full), not raise
        await bus.publish(EventType.SCANNER_STATUS, "3")

        assert sub.queue.qsize() == 2
        sub.unsubscribe()

    @pytest.mark.asyncio
    async def test_event_count(self):
        """Event count tracks total published events."""
        bus = EventBus()
        assert bus.event_count == 0

        await bus.publish(EventType.SCANNER_STATUS, "a")
        await bus.publish(EventType.MOMENTUM_ALERT, "b")
        assert bus.event_count == 2

    @pytest.mark.asyncio
    async def test_subscriber_counts(self):
        """Subscriber counts reflect active subscriptions."""
        bus = EventBus()
        sub1 = bus.subscribe(EventType.REPORT_READY)
        sub2 = bus.subscribe(EventType.REPORT_READY)

        counts = bus.subscriber_counts
        assert counts["REPORT_READY"] == 2

        sub1.unsubscribe()
        assert bus.subscriber_counts["REPORT_READY"] == 1
        sub2.unsubscribe()

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        """After unsubscribe, events are no longer delivered."""
        bus = EventBus()
        sub = bus.subscribe(EventType.SCANNER_STATUS)
        sub.unsubscribe()

        await bus.publish(EventType.SCANNER_STATUS, "should not arrive")
        assert sub.queue.empty()

    @pytest.mark.asyncio
    async def test_event_has_source(self):
        """Events carry the source string."""
        bus = EventBus()
        event = await bus.publish(EventType.SCANNER_STATUS, "data", source="test_source")
        assert event.source == "test_source"

    @pytest.mark.asyncio
    async def test_subscription_as_context_manager(self):
        """Subscription cleans up when used as context manager."""
        bus = EventBus()
        async with bus.subscribe(EventType.SCANNER_STATUS) as sub:
            await bus.publish(EventType.SCANNER_STATUS, "inside")
            e = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
            assert e.data == "inside"

        # After exit, subscription should be removed
        assert bus.subscriber_counts.get("SCANNER_STATUS", 0) == 0
