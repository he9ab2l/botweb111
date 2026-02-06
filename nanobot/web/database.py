"""SQLite persistence layer for nanobot web sessions, messages, events, and memory."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe SQLite DAO for web chat persistence."""

    def __init__(self, db_path: str | Path = "/opt/nanobot/data/nanobot.db"):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._ensure_tables()

    # ── Connection ────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT 'New Chat',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                ts          TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, ts);

            CREATE TABLE IF NOT EXISTS events (
                id           TEXT PRIMARY KEY,
                session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                run_id       TEXT,
                type         TEXT NOT NULL,
                ts           TEXT NOT NULL,
                step         INTEGER DEFAULT 0,
                payload_json TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, ts);

            CREATE TABLE IF NOT EXISTS global_memory (
                id          TEXT PRIMARY KEY,
                key         TEXT UNIQUE NOT NULL,
                value       TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL
            );
            """
        )
        conn.commit()

    # ── Sessions ──────────────────────────────────────────────────

    def create_session(self, session_id: str, title: str = "New Chat") -> dict[str, Any]:
        now = _now_iso()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
        conn.commit()
        return {"id": session_id, "title": title, "created_at": now, "updated_at": now, "status": "idle"}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        return {**dict(row), "status": "idle"}

    def list_sessions(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        return [{**dict(r), "status": "idle"} for r in rows]

    def update_session_title(self, session_id: str, title: str) -> bool:
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now_iso(), session_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def touch_session(self, session_id: str) -> None:
        conn = self._get_conn()
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now_iso(), session_id))
        conn.commit()

    def delete_session(self, session_id: str) -> bool:
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0

    def session_exists(self, session_id: str) -> bool:
        conn = self._get_conn()
        row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row is not None

    # ── Messages ──────────────────────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str) -> str:
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, ts) VALUES (?, ?, ?, ?, ?)",
            (msg_id, session_id, role, content, now),
        )
        conn.commit()
        return msg_id

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY ts ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Events ────────────────────────────────────────────────────

    def add_event(self, event: dict[str, Any]) -> None:
        conn = self._get_conn()
        evt_id = event.get("id", f"evt_{uuid.uuid4().hex[:12]}")
        session_id = event.get("session_id", "")
        run_id = event.get("run_id", "")
        evt_type = event.get("type", "")
        ts = event.get("ts") or event.get("timestamp") or _now_iso()
        step = event.get("step", 0)
        payload = event.get("payload", {})
        conn.execute(
            "INSERT OR IGNORE INTO events (id, session_id, run_id, type, ts, step, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(evt_id), session_id, run_id, evt_type, str(ts), step, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY ts ASC",
            (session_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.pop("payload_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
            result.append(d)
        return result

    # ── Global Memory ─────────────────────────────────────────────

    def get_memory(self) -> dict[str, str]:
        conn = self._get_conn()
        rows = conn.execute("SELECT key, value FROM global_memory ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def put_memory(self, key: str, value: str) -> None:
        now = _now_iso()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO global_memory (id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (f"mem_{uuid.uuid4().hex[:8]}", key, value, now),
        )
        conn.commit()

    def delete_memory(self, key: str) -> bool:
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM global_memory WHERE key = ?", (key,))
        conn.commit()
        return cur.rowcount > 0
