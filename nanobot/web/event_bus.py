"""Event bus for fanfan web UI (v2).

The bus is:
- persistent: every published event is stored in SQLite (Database.insert_event_v2)
- realtime: subscribers wait on an asyncio.Condition and poll the DB on wakeups
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from nanobot.web.database import Database


class EventBus:
    def __init__(self, db: Database):
        self._db = db
        self._cond = asyncio.Condition()

    async def publish(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        type: str,
        payload: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> dict[str, Any]:
        evt = self._db.insert_event_v2(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step_id,
            evt_type=type,
            ts=float(ts if ts is not None else time.time()),
            payload=payload or {},
        )
        async with self._cond:
            self._cond.notify_all()
        return evt

    async def wait_for_new(self, timeout_s: float) -> bool:
        try:
            async with self._cond:
                await asyncio.wait_for(self._cond.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    def get_events_since(
        self,
        *,
        session_id: str | None,
        since_id: int | None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        return self._db.get_events_v2(session_id=session_id, since_id=since_id, limit=limit)

    def get_session_events_since(
        self,
        *,
        session_id: str,
        since_id: int | None,
        since_seq: int | None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        return self._db.get_session_events_v2(
            session_id=session_id, since_id=since_id, since_seq=since_seq, limit=limit
        )

