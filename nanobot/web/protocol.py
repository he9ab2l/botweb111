"""Structured event protocol for web streaming.

Defines the canonical event types emitted over SSE to the frontend.
All events follow a unified JSON envelope:
  { type, run_id, ts, step, payload }
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """All event types the frontend must handle."""
    STATUS = "status"
    CONTENT_BLOCK_START = "content_block_start"
    CONTENT_BLOCK_DELTA = "content_block_delta"
    CONTENT_BLOCK_STOP = "content_block_stop"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    PATCH = "patch"
    MESSAGE_DELTA = "message_delta"
    FINAL_DONE = "final_done"
    ERROR = "error"


class BlockType(str, Enum):
    TEXT = "text"
    TOOL_JSON = "tool_json"
    THINKING = "thinking"


class ToolStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class StreamEvent:
    """Canonical event envelope sent over SSE."""
    type: str
    run_id: str
    ts: float = field(default_factory=time.time)
    step: int = 0
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"evt_{self.run_id}_{self.type}_{int(self.ts * 1000)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "run_id": self.run_id,
            "ts": self.ts,
            "step": self.step,
            "payload": self.payload,
        }


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def new_block_id() -> str:
    return f"blk_{uuid.uuid4().hex[:8]}"


def new_tool_call_id() -> str:
    return f"tc_{uuid.uuid4().hex[:8]}"


# ── Factory helpers ──────────────────────────────────────────────

def evt_status(run_id: str, status: str, session_id: str = "", step: int = 0) -> StreamEvent:
    return StreamEvent(
        type=EventType.STATUS,
        run_id=run_id,
        step=step,
        payload={"status": status, "session_id": session_id},
    )


def evt_content_block_start(
    run_id: str, block_id: str, block_type: str, step: int = 0
) -> StreamEvent:
    return StreamEvent(
        type=EventType.CONTENT_BLOCK_START,
        run_id=run_id,
        step=step,
        payload={"block_id": block_id, "block_type": block_type},
    )


def evt_content_block_delta(
    run_id: str, block_id: str, delta: str, step: int = 0
) -> StreamEvent:
    return StreamEvent(
        type=EventType.CONTENT_BLOCK_DELTA,
        run_id=run_id,
        step=step,
        payload={"block_id": block_id, "delta": delta},
    )


def evt_content_block_stop(
    run_id: str, block_id: str, step: int = 0
) -> StreamEvent:
    return StreamEvent(
        type=EventType.CONTENT_BLOCK_STOP,
        run_id=run_id,
        step=step,
        payload={"block_id": block_id},
    )


def evt_thinking(
    run_id: str, status: str, text: str = "", duration_ms: int = 0, step: int = 0
) -> StreamEvent:
    payload: dict[str, Any] = {"status": status}
    if text:
        payload["text"] = text
    if duration_ms:
        payload["duration_ms"] = duration_ms
    return StreamEvent(
        type=EventType.THINKING, run_id=run_id, step=step, payload=payload,
    )


def evt_tool_use(
    run_id: str,
    tool_call_id: str,
    tool_name: str,
    input_data: dict[str, Any],
    status: str = ToolStatus.RUNNING,
    step: int = 0,
) -> StreamEvent:
    return StreamEvent(
        type=EventType.TOOL_USE,
        run_id=run_id,
        step=step,
        payload={
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "input": input_data,
            "status": status,
        },
    )


def evt_tool_result(
    run_id: str,
    tool_call_id: str,
    tool_name: str,
    output: str,
    duration_ms: int = 0,
    step: int = 0,
) -> StreamEvent:
    return StreamEvent(
        type=EventType.TOOL_RESULT,
        run_id=run_id,
        step=step,
        payload={
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "output": output,
            "status": ToolStatus.COMPLETED,
            "duration_ms": duration_ms,
        },
    )


def evt_tool_error(
    run_id: str,
    tool_call_id: str,
    tool_name: str,
    error: str,
    duration_ms: int = 0,
    step: int = 0,
) -> StreamEvent:
    return StreamEvent(
        type=EventType.TOOL_ERROR,
        run_id=run_id,
        step=step,
        payload={
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "error": error,
            "status": ToolStatus.ERROR,
            "duration_ms": duration_ms,
        },
    )


def evt_patch(
    run_id: str,
    tool_call_id: str,
    files: list[dict[str, Any]],
    step: int = 0,
) -> StreamEvent:
    return StreamEvent(
        type=EventType.PATCH,
        run_id=run_id,
        step=step,
        payload={"tool_call_id": tool_call_id, "files": files},
    )


def evt_message_delta(
    run_id: str,
    stop_reason: str = "end_turn",
    usage: dict[str, int] | None = None,
    step: int = 0,
) -> StreamEvent:
    payload: dict[str, Any] = {"stop_reason": stop_reason}
    if usage:
        payload["usage"] = usage
    return StreamEvent(
        type=EventType.MESSAGE_DELTA, run_id=run_id, step=step, payload=payload,
    )


def evt_final_done(run_id: str, session_id: str = "", step: int = 0) -> StreamEvent:
    return StreamEvent(
        type=EventType.FINAL_DONE,
        run_id=run_id,
        step=step,
        payload={"session_id": session_id},
    )


def evt_error(
    run_id: str, code: str, message: str, step: int = 0
) -> StreamEvent:
    return StreamEvent(
        type=EventType.ERROR,
        run_id=run_id,
        step=step,
        payload={"code": code, "message": message},
    )
