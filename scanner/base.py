"""
Abstract interface for stock scanners.

Implementations: MomentumScanner (detects >X% moves)
Future: VolumeScanner, GapScanner, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.events import EventBus
from core.models import AlertSignal


class Scanner(ABC):
    """
    Interface for any stock scanning strategy.
    
    A scanner monitors market data and emits AlertSignal events
    when its criteria are met.
    """

    @abstractmethod
    async def run(self, event_bus: EventBus) -> None:
        """
        Start the scanner loop. Runs indefinitely.
        Publishes MOMENTUM_ALERT events to the event bus.
        """
        ...

    @abstractmethod
    async def scan_once(self) -> list[AlertSignal]:
        """
        Perform a single scan pass. Returns any triggered alerts.
        Useful for testing without the event bus.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the scanner."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the scanner loop is currently active."""
        ...
