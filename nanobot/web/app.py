"""FastAPI web application for nanobot chat with structured streaming and SQLite persistence."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.web.database import Database
from nanobot.web.events import EventHub


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionPatchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    sender_id: str = "web_user"


class MemoryPutRequest(BaseModel):
    key: str = Field(min_length=1)
    value: str = ""


def create_app() -> FastAPI:
    """Create a configured FastAPI app for web chat."""
    config = load_config()
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        raise RuntimeError("No API key configured. Set one in ~/.nanobot/config.json")

    bus = MessageBus()
    events = EventHub()
    db = Database()

    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=model,
    )
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        event_callback=events.publish,
        stream_final_events=True,
        final_event_chunk_size=20,
    )

    running_tasks: dict[str, asyncio.Task[None]] = {}
    sessions_lock = asyncio.Lock()

    # Wrap event publishing to also persist to DB
    _original_publish = events.publish

    async def _dual_publish(event: dict[str, Any]) -> None:
        """Publish to in-memory hub AND persist to SQLite."""
        await _original_publish(event)
        try:
            db.add_event(event)
        except Exception:
            pass  # Don't break SSE if DB write fails

    events.publish = _dual_publish  # type: ignore[assignment]
    agent._event_callback = _dual_publish

    app = FastAPI(title="nanobot web api", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Auto-naming helper ────────────────────────────────────────

    async def _auto_name_session(session_id: str, user_text: str) -> None:
        """Generate a short title for the session from the first user message."""
        try:
            # Try LLM-based naming
            naming_messages = [
                {
                    "role": "system",
                    "content": (
                        "Generate a short chat title (4-12 characters) for the following user message. "
                        "Reply with ONLY the title, no quotes, no explanation. "
                        "If the message is in Chinese, reply in Chinese. "
                        "If the message is in English, reply in English."
                    ),
                },
                {"role": "user", "content": user_text[:200]},
            ]
            response = await provider.chat(
                messages=naming_messages,
                tools=[],
                model=model,
            )
            title = (response.content or "").strip().strip('"').strip("'")[:30]
            if not title:
                title = user_text[:20].strip()
        except Exception:
            title = user_text[:20].strip()

        if title:
            db.update_session_title(session_id, title)

    # ── Health ────────────────────────────────────────────────────

    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "time": _now_iso(), "version": "0.3.0"}

    # ── Sessions ──────────────────────────────────────────────────

    @app.post("/api/v1/sessions")
    async def create_session(payload: SessionCreateRequest) -> dict[str, Any]:
        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        title = payload.title or "New Chat"
        record = db.create_session(session_id, title)
        return record

    @app.get("/api/v1/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        items = db.list_sessions()
        # Merge runtime status from running_tasks
        async with sessions_lock:
            for item in items:
                if item["id"] in running_tasks:
                    task = running_tasks[item["id"]]
                    if not task.done():
                        item["status"] = "running"
        return items

    @app.get("/api/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        record = db.get_session(session_id)
        if not record:
            raise HTTPException(status_code=404, detail="session not found")
        messages = db.get_messages(session_id)
        record["messages"] = messages
        return record

    @app.patch("/api/v1/sessions/{session_id}")
    async def patch_session(session_id: str, payload: SessionPatchRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        db.update_session_title(session_id, payload.title)
        record = db.get_session(session_id)
        return record or {"id": session_id, "title": payload.title}

    @app.delete("/api/v1/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        async with sessions_lock:
            task = running_tasks.pop(session_id, None)
            if task and not task.done():
                task.cancel()
        db.delete_session(session_id)
        return {"deleted": True}

    # ── Messages ──────────────────────────────────────────────────

    @app.post("/api/v1/sessions/{session_id}/messages")
    async def post_message(session_id: str, payload: MessageCreateRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        async with sessions_lock:
            existing = running_tasks.get(session_id)
            if existing and not existing.done():
                raise HTTPException(status_code=409, detail="session is busy")

        # Persist user message
        db.add_message(session_id, "user", payload.content)
        db.touch_session(session_id)

        # Check if this is the first user message (for auto-naming)
        messages = db.get_messages(session_id)
        user_messages = [m for m in messages if m["role"] == "user"]
        is_first = len(user_messages) == 1

        async def run_message() -> None:
            try:
                # Auto-name on first message
                if is_first:
                    asyncio.create_task(_auto_name_session(session_id, payload.content))

                result = await agent.process_direct(
                    content=payload.content,
                    channel="web",
                    chat_id=session_id,
                )
                # Persist assistant response
                if result:
                    db.add_message(session_id, "assistant", result)
            except Exception as exc:
                await events.publish(
                    {
                        "id": f"evt_{uuid.uuid4().hex}",
                        "session_id": session_id,
                        "type": "error",
                        "status": "error",
                        "payload": {
                            "code": "WEB_AGENT_TASK_ERROR",
                            "message": str(exc),
                        },
                        "timestamp": _now_iso(),
                    }
                )
            finally:
                async with sessions_lock:
                    running_tasks.pop(session_id, None)
                db.touch_session(session_id)

        task = asyncio.create_task(run_message())
        async with sessions_lock:
            running_tasks[session_id] = task

        return {"accepted": True, "session_id": session_id}

    # ── Cancel ────────────────────────────────────────────────────

    @app.post("/api/v1/sessions/{session_id}/cancel")
    async def cancel_run(session_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        async with sessions_lock:
            task = running_tasks.get(session_id)
            if task and not task.done():
                task.cancel()
                running_tasks.pop(session_id, None)
                return {"cancelled": True}
        return {"cancelled": False, "reason": "no active run"}

    # ── Memory ────────────────────────────────────────────────────

    @app.get("/api/v1/memory")
    async def get_memory() -> dict[str, str]:
        return db.get_memory()

    @app.put("/api/v1/memory")
    async def put_memory(payload: MemoryPutRequest) -> dict[str, Any]:
        db.put_memory(payload.key, payload.value)
        return {"ok": True, "key": payload.key}

    @app.delete("/api/v1/memory/{key}")
    async def delete_memory(key: str) -> dict[str, Any]:
        deleted = db.delete_memory(key)
        if not deleted:
            raise HTTPException(status_code=404, detail="key not found")
        return {"deleted": True}

    # ── SSE Event Stream ──────────────────────────────────────────

    @app.get("/api/v1/sessions/{session_id}/events")
    async def stream_events(session_id: str, request: Request):
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        header_last_id = request.headers.get("last-event-id")
        query_last_id = request.query_params.get("last_event_id")
        initial_last_id = query_last_id or header_last_id

        async def event_stream():
            last_id = initial_last_id
            pending = await events.get_since(session_id, last_id)
            for item in pending:
                last_id = str(item.get("id", last_id or "")) or last_id
                payload = json.dumps(item, ensure_ascii=False)
                yield f"id: {item.get('id', '')}\nevent: chat_event\ndata: {payload}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                has_new = await events.wait_for_new(session_id, timeout_s=15.0)
                if not has_new:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue

                new_items = await events.get_since(session_id, last_id)
                for item in new_items:
                    last_id = str(item.get("id", last_id or "")) or last_id
                    payload = json.dumps(item, ensure_ascii=False)
                    yield f"id: {item.get('id', '')}\nevent: chat_event\ndata: {payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Static files / SPA ────────────────────────────────────────

    # New React frontend (built output)
    dist_dir = Path(__file__).parent / "static" / "dist"
    static_dir = Path(__file__).parent / "static"

    # Serve built React app assets if available
    if dist_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")

    # Legacy static files
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/old")
    async def serve_old_index():
        old_path = static_dir / "old" / "index.html"
        if old_path.exists():
            return FileResponse(str(old_path))
        raise HTTPException(status_code=404, detail="old UI not available")

    @app.get("/")
    async def serve_index():
        # Prefer new React build
        new_index = dist_dir / "index.html"
        if new_index.exists():
            return FileResponse(str(new_index))
        # Fall back to old index
        old_index = static_dir / "index.html"
        if old_index.exists():
            return FileResponse(str(old_index))
        return {"message": "nanobot web api", "docs": "/docs"}

    # SPA catch-all: serve index.html for client-side routing
    @app.get("/{full_path:path}")
    async def spa_catchall(full_path: str):
        # Skip API and static routes
        if full_path.startswith(("api/", "static/", "assets/", "old")):
            raise HTTPException(status_code=404)
        new_index = dist_dir / "index.html"
        if new_index.exists():
            return FileResponse(str(new_index))
        raise HTTPException(status_code=404)

    return app
