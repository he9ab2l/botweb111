"""In-memory event hub for web chat streaming."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventHub:
    """Session-scoped event store + pub/sub for SSE streaming."""

    def __init__(self, max_events_per_session: int = 5000):
        self._events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self._lock = asyncio.Lock()
        self._max_events_per_session = max_events_per_session

    async def publish(self, event: dict[str, Any]) -> None:
        """Publish an event and notify waiting subscribers."""
        session_id = str(event.get("session_id", ""))
        if not session_id:
            return

        async with self._lock:
            bucket = self._events[session_id]
            bucket.append(event)
            if len(bucket) > self._max_events_per_session:
                del bucket[: len(bucket) - self._max_events_per_session]
            cond = self._conditions[session_id]

        async with cond:
            cond.notify_all()

    async def get_since(
        self,
        session_id: str,
        last_event_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get session events after `last_event_id` (exclusive)."""
        async with self._lock:
            events = list(self._events.get(session_id, []))

        if not last_event_id:
            return events

        index = -1
        for i, event in enumerate(events):
            if event.get("id") == last_event_id:
                index = i
                break

        if index < 0:
            return events

        return events[index + 1 :]

    async def wait_for_new(self, session_id: str, timeout_s: float = 15.0) -> bool:
        """Wait until new events are published for the session."""
        cond = self._conditions[session_id]
        try:
            async with cond:
                await asyncio.wait_for(cond.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False
