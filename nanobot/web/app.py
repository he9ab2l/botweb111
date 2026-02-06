"""FastAPI web application for nanobot chat with structured streaming and SQLite persistence."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pathlib import Path
import mimetypes

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse
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

    # Keep the web server running even when LLM access is not configured.
    # The UI will show a setup page and API endpoints that require the LLM will return 503.
    missing_llm_config = (not api_key and not is_bedrock)

    bus = MessageBus()
    events = EventHub()
    db = Database()

    provider: LiteLLMProvider | None = None
    agent: AgentLoop | None = None
    if not missing_llm_config:
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
    if agent is not None:
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
        if provider is None:
            return
        assert provider is not None
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
        return {
            "ok": True,
            "time": _now_iso(),
            "version": "0.3.0",
            "llm_configured": not missing_llm_config,
        }

    def _setup_page() -> HTMLResponse:
        html = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0, viewport-fit=cover\" />
    <meta name=\"theme-color\" content=\"#f7f7f6\" />
    <title>nanobot - Setup</title>
    <style>
      :root { color-scheme: light; }
      body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #f7f7f6; color: #0f172a; }
      .wrap { min-height: 100dvh; display: flex; align-items: center; justify-content: center; padding: 24px; }
      .card { width: min(760px, 100%); background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; box-shadow: 0 18px 50px rgba(15,23,42,0.08); overflow: hidden; }
      header { padding: 18px 20px; background: linear-gradient(135deg, rgba(37,99,235,0.10), rgba(14,165,233,0.08)); border-bottom: 1px solid #e2e8f0; }
      h1 { margin: 0; font-size: 16px; letter-spacing: 0.2px; }
      p { margin: 10px 0; color: #334155; line-height: 1.6; font-size: 13px; }
      .body { padding: 16px 20px 20px; }
      pre { margin: 10px 0; background: #0b1220; color: #e2e8f0; padding: 12px 12px; border-radius: 10px; overflow: auto; font-size: 12px; line-height: 1.55; }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
      .hint { font-size: 12px; color: #64748b; }
      .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 8px; }
      a { color: #2563eb; text-decoration: none; }
      a:hover { text-decoration: underline; }
      .pill { display: inline-block; padding: 2px 8px; border: 1px solid #e2e8f0; border-radius: 999px; font-size: 11px; color: #334155; background: #f8fafc; }
    </style>
  </head>
  <body>
    <div class=\"wrap\">
      <div class=\"card\">
        <header>
          <h1>nanobot needs an API key</h1>
          <p class=\"hint\">The server is running, but LLM access is not configured yet.</p>
        </header>
        <div class=\"body\">
          <p>Create <span class=\"pill\">~/.nanobot/config.json</span> and set at least one provider key (for example <code>providers.openrouter.apiKey</code>).</p>
          <pre><code>mkdir -p ~/.nanobot

# From the project root:
cp ./config.example.json ~/.nanobot/config.json

# Then edit ~/.nanobot/config.json and set your apiKey
</code></pre>
          <p class=\"hint\">After updating the config, restart the web service and refresh this page.</p>
          <div class=\"row\">
            <a href=\"/api/v1/health\">Check health</a>
            <span class=\"hint\">Health includes <code>llm_configured</code>.</span>
          </div>
        </div>
      </div>
    </div>
  </body>
</html>"""
        return HTMLResponse(content=html, status_code=200)

    def _require_agent() -> AgentLoop:
        if missing_llm_config or agent is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "LLM API key not configured. Create ~/.nanobot/config.json (see config.example.json) and restart the service."
                ),
            )
        return agent

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
        agent_: AgentLoop = _require_agent()
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

                result = await agent_.process_direct(
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

    # Ensure correct content-types for PWA assets.
    mimetypes.add_type("application/manifest+json", ".webmanifest")

    # New React frontend (built output)
    dist_dir = Path(__file__).parent / "static" / "dist"
    static_dir = Path(__file__).parent / "static"

    # Serve built React app assets if available
    if dist_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")
        if (dist_dir / "icons").exists():
            app.mount("/icons", StaticFiles(directory=str(dist_dir / "icons")), name="icons")

        @app.get("/manifest.webmanifest")
        async def serve_webmanifest():
            p = dist_dir / "manifest.webmanifest"
            if p.exists():
                return FileResponse(str(p), media_type="application/manifest+json")
            raise HTTPException(status_code=404)

        @app.get("/sw.js")
        async def serve_service_worker():
            p = dist_dir / "sw.js"
            if p.exists():
                return FileResponse(
                    str(p),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"},
                )
            raise HTTPException(status_code=404)

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
        if missing_llm_config:
            return _setup_page()
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
        if missing_llm_config:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            return _setup_page()
        # Skip API routes
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)

        # If this path is a real file in dist/, serve it (PWA assets like workbox-*.js).
        try:
            dist_root = dist_dir.resolve()
            candidate = (dist_dir / full_path).resolve()
            if dist_root == candidate or dist_root not in candidate.parents:
                candidate = None
        except Exception:
            candidate = None

        if candidate and candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))

        # Skip legacy/static mounts (avoid returning index.html for missing static assets)
        if full_path.startswith(("static/", "assets/", "icons/", "old")):
            raise HTTPException(status_code=404)
        new_index = dist_dir / "index.html"
        if new_index.exists():
            return FileResponse(str(new_index))
        raise HTTPException(status_code=404)

    return app
