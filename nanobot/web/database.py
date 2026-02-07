"""SQLite persistence layer for fanfan web sessions, turns, steps, events, and artifacts.

This file intentionally keeps legacy tables (v1) while introducing a new v2 schema.
The v2 web UI uses:
- turns/steps for execution structure
- events (INTEGER id + per-session seq) for SSE replay
- file_changes / terminal_chunks / permissions / context_items for inspector tabs
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe SQLite DAO for web chat persistence."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._ensure_schema()

    # ── Connection ────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            # Avoid transient "database is locked" errors when multiple tasks/workers write events.
            self._conn.execute("PRAGMA busy_timeout=30000")
        return self._conn

    def _table_columns(self, name: str) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(f"PRAGMA table_info({name})").fetchall()
        return [str(r["name"]) for r in rows]

    def _ensure_schema(self) -> None:
        """Create/migrate schema (legacy v1 + new v2)."""
        with self._lock:
            conn = self._get_conn()

            # Legacy base tables (keep)
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

                CREATE TABLE IF NOT EXISTS global_memory (
                    id          TEXT PRIMARY KEY,
                    key         TEXT UNIQUE NOT NULL,
                    value       TEXT NOT NULL DEFAULT '',
                    updated_at  TEXT NOT NULL
                );
                """
            )

            # If an old "events" table exists (TEXT primary key), rename to events_v1.
            # New v2 uses "events" with INTEGER primary key for replay ordering.
            if "events" in [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
                cols = self._table_columns("events")
                if "run_id" in cols and "payload_json" in cols and "seq" not in cols:
                    # legacy v1 schema detected
                    if "events_v1" not in [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
                        conn.execute("ALTER TABLE events RENAME TO events_v1")

            # Ensure v1 events table exists for backward compatibility
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events_v1 (
                    id           TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    run_id       TEXT,
                    type         TEXT NOT NULL,
                    ts           TEXT NOT NULL,
                    step         INTEGER DEFAULT 0,
                    payload_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_events_v1_session ON events_v1(session_id, ts);
                """
            )

            # v2 schema
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    user_text   TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, created_at);

                CREATE TABLE IF NOT EXISTS steps (
                    id          TEXT PRIMARY KEY,
                    turn_id     TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    idx         INTEGER NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'running',
                    started_at  TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_steps_turn ON steps(turn_id, idx);

                CREATE TABLE IF NOT EXISTS events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    turn_id     TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    step_id     TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
                    seq         INTEGER NOT NULL,
                    ts          REAL NOT NULL,
                    type        TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
                CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_events_turn ON events(turn_id, id);

                CREATE TABLE IF NOT EXISTS file_changes (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    turn_id     TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    step_id     TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
                    path        TEXT NOT NULL,
                    diff        TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_file_changes_session ON file_changes(session_id, created_at);

                CREATE TABLE IF NOT EXISTS file_versions (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    turn_id     TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    step_id     TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
                    path        TEXT NOT NULL,
                    idx         INTEGER NOT NULL,
                    sha256      TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    note        TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_file_versions_unique ON file_versions(session_id, path, idx);
                CREATE INDEX IF NOT EXISTS idx_file_versions_session_path ON file_versions(session_id, path, idx);

                CREATE TABLE IF NOT EXISTS tool_permissions (
                    tool_name   TEXT PRIMARY KEY,
                    policy      TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS permission_requests (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    turn_id     TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    step_id     TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
                    tool_name   TEXT NOT NULL,
                    input_json  TEXT NOT NULL DEFAULT '{}',
                    status      TEXT NOT NULL DEFAULT 'pending',
                    scope       TEXT NOT NULL DEFAULT 'once',
                    created_at  TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_permission_requests_session ON permission_requests(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_permission_requests_status ON permission_requests(status, created_at);

                CREATE TABLE IF NOT EXISTS context_items (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    kind        TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    content_ref TEXT NOT NULL DEFAULT '',
                    pinned      INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_context_items_session ON context_items(session_id, created_at);

                CREATE TABLE IF NOT EXISTS terminal_chunks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    turn_id     TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    step_id     TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
                    tool_call_id TEXT NOT NULL,
                    stream      TEXT NOT NULL,
                    text        TEXT NOT NULL,
                    ts          REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_terminal_chunks_session ON terminal_chunks(session_id, id);
                """
            )

            conn.commit()

    # ── Sessions ──────────────────────────────────────────────────

    def create_session(self, session_id: str, title: str = "New Chat") -> dict[str, Any]:
        with self._lock:
            now = _now_iso()
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
            conn.commit()
            return {
                "id": session_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "status": "idle",
            }

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            return {**dict(row), "status": "idle"}

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
            return [{**dict(r), "status": "idle"} for r in rows]

    def update_session_title(self, session_id: str, title: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now_iso(), session_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def touch_session(self, session_id: str) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now_iso(), session_id))
            conn.commit()

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cur.rowcount > 0

    def session_exists(self, session_id: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return row is not None

    # ── Messages ──────────────────────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str) -> str:
        with self._lock:
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
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY ts ASC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Events (legacy v1) ────────────────────────────────────────

    def add_event(self, event: dict[str, Any]) -> None:
        """Insert a v1 event into the legacy `events_v1` table."""
        with self._lock:
            conn = self._get_conn()
            evt_id = event.get("id", f"evt_{uuid.uuid4().hex[:12]}")
            session_id = event.get("session_id", "")
            run_id = event.get("run_id", "")
            evt_type = event.get("type", "")
            ts = event.get("ts") or event.get("timestamp") or _now_iso()
            step = event.get("step", 0)
            payload = event.get("payload", {})
            conn.execute(
                "INSERT OR IGNORE INTO events_v1 (id, session_id, run_id, type, ts, step, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(evt_id),
                    session_id,
                    run_id,
                    evt_type,
                    str(ts),
                    int(step or 0),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        """Fetch legacy v1 events."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM events_v1 WHERE session_id = ? ORDER BY ts ASC",
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

    # ── Turns / Steps (v2) ────────────────────────────────────────

    def create_turn(self, session_id: str, user_text: str) -> dict[str, Any]:
        with self._lock:
            turn_id = f"turn_{uuid.uuid4().hex[:12]}"
            now = _now_iso()
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO turns (id, session_id, user_text, created_at) VALUES (?, ?, ?, ?)",
                (turn_id, session_id, user_text, now),
            )
            conn.commit()
            return {"id": turn_id, "session_id": session_id, "user_text": user_text, "created_at": now}

    def list_turns(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            return dict(row) if row else None

    def create_step(self, turn_id: str, idx: int) -> dict[str, Any]:
        with self._lock:
            step_id = f"step_{uuid.uuid4().hex[:12]}"
            now = _now_iso()
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO steps (id, turn_id, idx, status, started_at) VALUES (?, ?, ?, ?, ?)",
                (step_id, turn_id, int(idx), "running", now),
            )
            conn.commit()
            return {"id": step_id, "turn_id": turn_id, "idx": int(idx), "status": "running", "started_at": now}

    def finish_step(self, step_id: str, status: str = "completed") -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE steps SET status = ?, finished_at = ? WHERE id = ?",
                (status, _now_iso(), step_id),
            )
            conn.commit()

    def list_steps(self, turn_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM steps WHERE turn_id = ? ORDER BY idx ASC",
                (turn_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Events (v2) ───────────────────────────────────────────────

    def _next_session_seq(self, conn: sqlite3.Connection, session_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        m = int(row["m"] if row else 0)
        return m + 1

    def insert_event_v2(
        self,
        session_id: str,
        turn_id: str,
        step_id: str,
        evt_type: str,
        ts: float,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a v2 event and return the persisted envelope (with id + seq)."""
        with self._lock:
            conn = self._get_conn()
            payload_json = json.dumps(payload or {}, ensure_ascii=False)

            # NOTE: seq is per-session and must be monotonic.
            # In WAL mode, multiple processes can race if we compute MAX(seq) in deferred transactions.
            # Use BEGIN IMMEDIATE to serialize writers during seq allocation.
            for _attempt in range(3):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    seq = self._next_session_seq(conn, session_id)
                    cur = conn.execute(
                        "INSERT INTO events (session_id, turn_id, step_id, seq, ts, type, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (session_id, turn_id, step_id, int(seq), float(ts), str(evt_type), payload_json),
                    )
                    conn.commit()
                    evt_id = int(cur.lastrowid)
                    return {
                        "id": evt_id,
                        "seq": seq,
                        "ts": float(ts),
                        "type": str(evt_type),
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "step_id": step_id,
                        "payload": payload or {},
                    }
                except sqlite3.IntegrityError:
                    # Retry in case of a rare seq uniqueness race.
                    conn.rollback()
                    continue
                except Exception:
                    conn.rollback()
                    raise

            raise sqlite3.IntegrityError("failed to allocate per-session event seq")

    def get_events_v2(
        self,
        session_id: str | None = None,
        since_id: int | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Fetch v2 events since global id (exclusive)."""
        with self._lock:
            conn = self._get_conn()
            params: list[Any] = []
            where = []
            if session_id:
                where.append("session_id = ?")
                params.append(session_id)
            if since_id is not None:
                where.append("id > ?")
                params.append(int(since_id))
            where_sql = "WHERE " + " AND ".join(where) if where else ""
            rows = conn.execute(
                f"SELECT * FROM events {where_sql} ORDER BY id ASC LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["payload"] = json.loads(d.pop("payload_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    d["payload"] = {}
                out.append(d)
            return out

    def get_session_events_v2(
        self,
        session_id: str,
        since_id: int | None = None,
        since_seq: int | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Fetch v2 events for a session since global id or per-session seq (exclusive)."""
        with self._lock:
            conn = self._get_conn()
            if since_id is not None:
                rows = conn.execute(
                    "SELECT * FROM events WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                    (session_id, int(since_id), int(limit)),
                ).fetchall()
            elif since_seq is not None:
                rows = conn.execute(
                    "SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY id ASC LIMIT ?",
                    (session_id, int(since_seq), int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                    (session_id, int(limit)),
                ).fetchall()

            out: list[dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["payload"] = json.loads(d.pop("payload_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    d["payload"] = {}
                out.append(d)
            return out

    # ── File changes / Terminal / Context / Permissions ───────────

    def add_file_change(self, session_id: str, turn_id: str, step_id: str, path: str, diff: str) -> str:
        with self._lock:
            fc_id = f"fc_{uuid.uuid4().hex[:12]}"
            now = _now_iso()
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO file_changes (id, session_id, turn_id, step_id, path, diff, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fc_id, session_id, turn_id, step_id, path, diff, now),
            )
            conn.commit()
            return fc_id

    def list_file_changes(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM file_changes WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]


    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    def list_file_versions(self, session_id: str, path: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT id, session_id, turn_id, step_id, path, idx, sha256, note, created_at "
                "FROM file_versions WHERE session_id = ? AND path = ? ORDER BY idx DESC LIMIT ?",
                (session_id, path, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_file_version(self, version_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT * FROM file_versions WHERE id = ?", (version_id,)).fetchone()
            return dict(row) if row else None

    def _has_any_file_versions(self, conn: sqlite3.Connection, session_id: str, path: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM file_versions WHERE session_id = ? AND path = ? LIMIT 1",
            (session_id, path),
        ).fetchone()
        return row is not None

    def _last_file_version_sha(self, conn: sqlite3.Connection, session_id: str, path: str) -> str | None:
        row = conn.execute(
            "SELECT sha256 FROM file_versions WHERE session_id = ? AND path = ? ORDER BY idx DESC LIMIT 1",
            (session_id, path),
        ).fetchone()
        return str(row["sha256"]) if row and row["sha256"] is not None else None

    def _next_file_version_idx(self, conn: sqlite3.Connection, session_id: str, path: str) -> int:
        row = conn.execute(
            "SELECT MAX(idx) AS m FROM file_versions WHERE session_id = ? AND path = ?",
            (session_id, path),
        ).fetchone()
        m = row["m"] if row and row["m"] is not None else None
        return int(m) + 1 if m is not None else 0

    def ensure_file_base_version(
        self,
        session_id: str,
        turn_id: str,
        step_id: str,
        path: str,
        content: str,
    ) -> str | None:
        # Persist the pre-change file content as idx=0 for the first change in a session.
        with self._lock:
            if content is None:
                return None
            if len(content) > 1_000_000:
                return None

            conn = self._get_conn()
            if self._has_any_file_versions(conn, session_id, path):
                return None

            return self.add_file_version(
                session_id=session_id,
                turn_id=turn_id,
                step_id=step_id,
                path=path,
                content=content,
                note="base",
            )

    def add_file_version(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        path: str,
        content: str,
        note: str = "",
    ) -> str | None:
        # Add a new file version snapshot for rollback/history.
        # Returns the new version id, or None if skipped (duplicate/too large).
        with self._lock:
            if content is None:
                return None
            if len(content) > 1_000_000:
                return None

            conn = self._get_conn()
            sha = self._hash_text(content)
            last_sha = self._last_file_version_sha(conn, session_id, path)
            if last_sha == sha:
                return None

            fv_id = f"fv_{uuid.uuid4().hex[:12]}"
            now = _now_iso()
            idx = self._next_file_version_idx(conn, session_id, path)
            conn.execute(
                "INSERT INTO file_versions (id, session_id, turn_id, step_id, path, idx, sha256, content, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fv_id, session_id, turn_id, step_id, path, int(idx), sha, content, note, now),
            )
            conn.commit()
            return fv_id

    def record_file_change_versions(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        path: str,
        before: str | None,
        after: str | None,
        note: str = "",
    ) -> None:
        # Record version snapshots for a file mutation.
        if before is not None:
            self.ensure_file_base_version(session_id, turn_id, step_id, path, before)
        if after is not None:
            self.add_file_version(
                session_id=session_id,
                turn_id=turn_id,
                step_id=step_id,
                path=path,
                content=after,
                note=note,
            )

    def add_terminal_chunk(
        self,
        session_id: str,
        turn_id: str,
        step_id: str,
        tool_call_id: str,
        stream: str,
        text: str,
        ts: float,
    ) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO terminal_chunks (session_id, turn_id, step_id, tool_call_id, stream, text, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, turn_id, step_id, tool_call_id, stream, text, float(ts)),
            )
            conn.commit()

    def list_terminal_chunks(self, session_id: str, limit: int = 2000) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM terminal_chunks WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_tool_permission(self, tool_name: str, policy: str) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO tool_permissions (tool_name, policy, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(tool_name) DO UPDATE SET policy = excluded.policy, updated_at = excluded.updated_at",
                (tool_name, policy, _now_iso()),
            )
            conn.commit()

    def get_tool_permissions(self) -> dict[str, str]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT tool_name, policy FROM tool_permissions").fetchall()
            return {str(r["tool_name"]): str(r["policy"]) for r in rows}

    def create_permission_request(
        self,
        session_id: str,
        turn_id: str,
        step_id: str,
        tool_name: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            pr_id = f"pr_{uuid.uuid4().hex[:12]}"
            now = _now_iso()
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO permission_requests (id, session_id, turn_id, step_id, tool_name, input_json, status, scope, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', 'once', ?)",
                (pr_id, session_id, turn_id, step_id, tool_name, json.dumps(input_data, ensure_ascii=False), now),
            )
            conn.commit()
            return {"id": pr_id, "status": "pending", "scope": "once", "created_at": now}

    def resolve_permission_request(self, request_id: str, status: str, scope: str = "once") -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE permission_requests SET status = ?, scope = ?, resolved_at = ? WHERE id = ?",
                (status, scope, _now_iso(), request_id),
            )
            conn.commit()

    def list_pending_permission_requests(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM permission_requests WHERE session_id = ? AND status = 'pending' ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["input"] = json.loads(d.pop("input_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    d["input"] = {}
                out.append(d)
            return out

    def list_permission_requests(self, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
        """List all tool permission requests for a session (pending + resolved)."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM permission_requests WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["input"] = json.loads(d.pop("input_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    d["input"] = {}
                out.append(d)
            return out

    def add_context_item(self, session_id: str, kind: str, title: str, content_ref: str = "", pinned: bool = False) -> str:
        with self._lock:
            cid = f"ctx_{uuid.uuid4().hex[:12]}"
            now = _now_iso()
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO context_items (id, session_id, kind, title, content_ref, pinned, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, session_id, kind, title, content_ref, 1 if pinned else 0, now),
            )
            conn.commit()
            return cid

    def list_context_items(self, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM context_items WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_context_pinned(self, context_id: str, pinned: bool) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE context_items SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, context_id),
            )
            conn.commit()

    # ── Global Memory ─────────────────────────────────────────────

    def get_memory(self) -> dict[str, str]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT key, value FROM global_memory ORDER BY key").fetchall()
            return {r["key"]: r["value"] for r in rows}

    def put_memory(self, key: str, value: str) -> None:
        with self._lock:
            now = _now_iso()
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO global_memory (id, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (f"mem_{uuid.uuid4().hex[:8]}", key, value, now),
            )
            conn.commit()

    def delete_memory(self, key: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute("DELETE FROM global_memory WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0
