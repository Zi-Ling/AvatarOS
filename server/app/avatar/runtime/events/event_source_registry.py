from __future__ import annotations

"""EventSourceRegistry — source registration, health checking, and reconnection.

Manages EventSource adapters. Disconnected sources are marked degraded and
reconnected with exponential backoff (max interval 5 minutes).

Requirements: 4.4, 4.9
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict

from .types import EventSource

logger = logging.getLogger(__name__)

_MAX_BACKOFF_S = 300.0  # 5 minutes
_INITIAL_BACKOFF_S = 1.0


@dataclass
class _SourceEntry:
    """Internal bookkeeping for a registered EventSource."""

    source: Any  # EventSource instance
    degraded: bool = False
    backoff_s: float = _INITIAL_BACKOFF_S
    last_reconnect_attempt: float = 0.0


class EventSourceRegistry:
    """Source registration + health checking + exponential backoff reconnection."""

    def __init__(self) -> None:
        self._sources: Dict[str, _SourceEntry] = {}

    # ── public API ──

    def register(self, source: EventSource) -> None:
        """Register an EventSource adapter."""
        sid = source.source_id
        self._sources[sid] = _SourceEntry(source=source)
        logger.info("[EventSourceRegistry] registered source: %s", sid)

    def unregister(self, source_id: str) -> None:
        """Unregister an EventSource adapter."""
        entry = self._sources.pop(source_id, None)
        if entry is not None:
            logger.info("[EventSourceRegistry] unregistered source: %s", source_id)

    def get_health(self) -> Dict[str, bool]:
        """Return a mapping of source_id → is_healthy for all sources."""
        return {
            sid: (not entry.degraded and entry.source.is_healthy)
            for sid, entry in self._sources.items()
        }

    async def reconnect_degraded(self) -> None:
        """Attempt to reconnect all degraded sources with exponential backoff."""
        now = time.time()
        for sid, entry in self._sources.items():
            if not entry.degraded:
                continue

            # Check backoff
            if now - entry.last_reconnect_attempt < entry.backoff_s:
                continue

            entry.last_reconnect_attempt = now
            try:
                await entry.source.stop()
                await entry.source.start()
                if entry.source.is_healthy:
                    entry.degraded = False
                    entry.backoff_s = _INITIAL_BACKOFF_S
                    logger.info(
                        "[EventSourceRegistry] reconnected source: %s", sid
                    )
                else:
                    self._increase_backoff(entry)
            except Exception as exc:
                logger.warning(
                    "[EventSourceRegistry] reconnect failed for %s: %s", sid, exc
                )
                self._increase_backoff(entry)

    def mark_degraded(self, source_id: str) -> None:
        """Mark a source as degraded (e.g. after connection failure)."""
        entry = self._sources.get(source_id)
        if entry is not None:
            entry.degraded = True
            logger.warning(
                "[EventSourceRegistry] source marked degraded: %s", source_id
            )

    # ── internals ──

    @staticmethod
    def _increase_backoff(entry: _SourceEntry) -> None:
        entry.backoff_s = min(entry.backoff_s * 2, _MAX_BACKOFF_S)
