"""FastAPI web application for fanfan (OpenCode-style WebUI).

Key properties:
- Two-stage WebUI: UI is served or reverse-proxied at `/` (same-origin)
- Global SSE bus: `GET /event` (reconnect + replay)
- SQLite persistence: sessions/messages + v2 turns/steps/events + artifacts
- Agent runner: OpenCode-style tool loop with streaming parts
"""

from __future__ import annotations

import asyncio
import difflib
import json
import mimetypes
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.web.database import Database
from nanobot.web.event_bus import EventBus
from nanobot.web.permissions import PermissionManager
from nanobot.web.runner import FanfanWebRunner
from nanobot.web.settings import WebSettings, repo_root


APP_VERSION = "0.4.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.time()


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionPatchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    sender_id: str = "web_user"


class TurnCreateRequest(BaseModel):
    content: str = Field(min_length=1)


class MemoryPutRequest(BaseModel):
    key: str = Field(min_length=1)
    value: str = ""


class PermissionResolveRequest(BaseModel):
    status: str = Field(pattern="^(approved|denied)$")
    scope: str = Field(pattern="^(once|session|always)$")


class ContextPinRequest(BaseModel):
    context_id: str = Field(min_length=1)


def create_app() -> FastAPI:
    settings = WebSettings()

    config = load_config()
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    missing_llm_config = (not api_key and not is_bedrock)

    # DB + event bus (v2)
    data_dir = settings.resolved_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = settings.resolved_db_path()
    legacy_global = Path("/opt/nanobot/data/nanobot.db")
    if settings.db_copy_from_legacy and not settings.db_path and not db_path.exists() and legacy_global.exists():
        # Copy legacy DB into the instance-local DB path to preserve history without
        # mutating the shared legacy file (safer for multi-instance deployments).
        try:
            import sqlite3

            src = sqlite3.connect(str(legacy_global))
            dst = sqlite3.connect(str(db_path))
            src.backup(dst)
            dst.close()
            src.close()
        except Exception:
            pass

    db = Database(db_path)
    bus = EventBus(db)
    permissions = PermissionManager(db=db, settings=settings)

    provider: LiteLLMProvider | None = None
    runner: FanfanWebRunner | None = None
    if not missing_llm_config:
        provider = LiteLLMProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model,
        )
        runner = FanfanWebRunner(
            db=db,
            bus=bus,
            permissions=permissions,
            provider=provider,
            settings=settings,
            model=model,
            max_iterations=config.agents.defaults.max_tool_iterations,
            brave_api_key=config.tools.web.search.api_key or None,
        )

    running_tasks: dict[str, asyncio.Task[None]] = {}
    sessions_lock = asyncio.Lock()

    app = FastAPI(title="fanfan web api", version=APP_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        resp = await call_next(request)
        csp_value = settings.csp_dev if settings.ui_mode == "dev" else settings.csp
        resp.headers.setdefault("Content-Security-Policy", csp_value)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    # ── Demo session (startup) ───────────────────────────────────

    @app.on_event("startup")
    async def _ensure_demo_session() -> None:
        """Create a demo session on first boot (no existing sessions)."""
        try:
            if db.list_sessions():
                return

            demo_session_id = f"ses_demo_{uuid.uuid4().hex[:8]}"
            demo_user = "Demo: show a tool call, terminal streaming, and a diff."
            demo_assistant = "Demo completed. You should see tool cards, terminal output, and a diff in the inspector."

            db.create_session(demo_session_id, "Demo")
            db.add_message(demo_session_id, "user", demo_user)
            turn = db.create_turn(demo_session_id, demo_user)

            # Step 0 (user)
            s0 = db.create_step(turn["id"], idx=0)
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=s0["id"],
                type="message_delta",
                payload={"role": "user", "message_id": f"msg_{uuid.uuid4().hex[:8]}", "delta": demo_user},
            )
            db.finish_step(s0["id"], status="completed")

            # Step 1 (agent/tool trace)
            s1 = db.create_step(turn["id"], idx=1)
            step_id = s1["id"]

            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="thinking",
                payload={"status": "start"},
            )
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="thinking",
                payload={"status": "delta", "text": "Planning a demo run..."},
            )
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="thinking",
                payload={"status": "end", "duration_ms": 120},
            )

            # Tool: run_command (simulated terminal chunks)
            tc1 = f"tc_{uuid.uuid4().hex[:8]}"
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="tool_call",
                payload={
                    "tool_call_id": tc1,
                    "tool_name": "run_command",
                    "input": {"command": "echo hello"},
                    "status": "running",
                },
            )
            ts = _now_ts()
            db.add_terminal_chunk(demo_session_id, turn["id"], step_id, tc1, "stdout", "hello\n", ts)
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="terminal_chunk",
                payload={"tool_call_id": tc1, "stream": "stdout", "text": "hello\n"},
                ts=ts,
            )
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="tool_result",
                payload={
                    "tool_call_id": tc1,
                    "tool_name": "run_command",
                    "ok": True,
                    "output": "hello\n",
                    "error": "",
                    "duration_ms": 50,
                },
            )

            # Tool: apply_patch (simulated diff)
            tc2 = f"tc_{uuid.uuid4().hex[:8]}"
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="tool_call",
                payload={
                    "tool_call_id": tc2,
                    "tool_name": "apply_patch",
                    "input": {"patch": "(demo patch)"},
                    "status": "running",
                },
            )

            demo_path = "data/demo.txt"
            before = ""
            after = "hello from fanfan demo\n"
            diff = "\n".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile="a/" + demo_path,
                    tofile="b/" + demo_path,
                    lineterm="",
                )
            ) + "\n"

            db.add_file_change(demo_session_id, turn["id"], step_id, demo_path, diff)
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="diff",
                payload={"tool_call_id": tc2, "path": demo_path, "diff": diff},
            )

            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="tool_result",
                payload={
                    "tool_call_id": tc2,
                    "tool_name": "apply_patch",
                    "ok": True,
                    "output": "applied (demo)",
                    "error": "",
                    "duration_ms": 30,
                },
            )

            # Final
            await bus.publish(
                session_id=demo_session_id,
                turn_id=turn["id"],
                step_id=step_id,
                type="final",
                payload={
                    "role": "assistant",
                    "message_id": f"msg_{uuid.uuid4().hex[:8]}",
                    "text": demo_assistant,
                    "finish_reason": "stop",
                    "usage": {},
                },
            )
            db.finish_step(step_id, status="completed")
            db.add_message(demo_session_id, "assistant", demo_assistant)
        except Exception:
            # Demo should never block server startup.
            return

    # ── Setup / Guard ────────────────────────────────────────────

    def _setup_page() -> HTMLResponse:
        html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#f7f7f6" />
    <title>fanfan - Setup</title>
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
    <div class="wrap">
      <div class="card">
        <header>
          <h1>fanfan needs an API key</h1>
          <p class="hint">The server is running, but LLM access is not configured yet.</p>
        </header>
        <div class="body">
          <p>Create <span class="pill">~/.fanfan/config.json</span> and set at least one provider key (for example <code>providers.openrouter.apiKey</code>).</p>
          <pre><code>mkdir -p ~/.fanfan

# From the project root:
cp ./config.example.json ~/.fanfan/config.json

# Then edit ~/.fanfan/config.json and set your apiKey
</code></pre>
          <p class="hint">After updating the config, restart the web service and refresh this page.</p>
          <div class="row">
            <a href="/healthz">Check health</a>
            <span class="hint">Health includes <code>llm_configured</code>.</span>
          </div>
        </div>
      </div>
    </div>
  </body>
</html>"""
        return HTMLResponse(content=html, status_code=200)

    def _require_runner() -> FanfanWebRunner:
        if missing_llm_config or runner is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "LLM API key not configured. Create ~/.fanfan/config.json (see config.example.json) and restart the service."
                ),
            )
        return runner

    # ── Health ───────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "time": _now_iso(),
            "version": APP_VERSION,
            "llm_configured": not missing_llm_config,
            "ui_mode": settings.ui_mode,
        }

    @app.get("/api/v2/health")
    async def health_v2() -> dict[str, Any]:
        return {
            "ok": True,
            "time": _now_iso(),
            "version": APP_VERSION,
            "llm_configured": not missing_llm_config,
            "db_path": str(settings.resolved_db_path()),
        }

    # Legacy health path
    @app.get("/api/v1/health")
    async def health_v1() -> dict[str, Any]:
        return await health_v2()

    # ── Sessions (v1 + v2) ───────────────────────────────────────

    def _session_status(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Merge runtime status from running_tasks
        out = []
        for item in items:
            d = dict(item)
            t = running_tasks.get(d["id"])
            if t and not t.done():
                d["status"] = "running"
            out.append(d)
        return out

    @app.post("/api/v2/sessions")
    async def create_session_v2(payload: SessionCreateRequest) -> dict[str, Any]:
        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        title = payload.title or "New Chat"
        return db.create_session(session_id, title)

    @app.get("/api/v2/sessions")
    async def list_sessions_v2() -> list[dict[str, Any]]:
        return _session_status(db.list_sessions())

    @app.get("/api/v2/sessions/{session_id}")
    async def get_session_v2(session_id: str) -> dict[str, Any]:
        record = db.get_session(session_id)
        if not record:
            raise HTTPException(status_code=404, detail="session not found")
        record["messages"] = db.get_messages(session_id)
        return record

    def _collect_session_export(session_id: str) -> dict[str, Any]:
        record = db.get_session(session_id)
        if not record:
            raise HTTPException(status_code=404, detail="session not found")

        messages = db.get_messages(session_id)
        turns = db.list_turns(session_id, limit=500)
        steps_by_turn = {t["id"]: db.list_steps(t["id"]) for t in turns}
        events = db.get_session_events_v2(session_id, limit=20000)
        file_changes = db.list_file_changes(session_id, limit=2000)
        terminal = db.list_terminal_chunks(session_id, limit=20000)
        context_items = db.list_context_items(session_id, limit=2000)
        permissions_all = db.list_permission_requests(session_id, limit=2000)

        return {
            "schema": "fanfan.session_export.v1",
            "exported_at": _now_iso(),
            "session": record,
            "messages": messages,
            "turns": turns,
            "steps_by_turn": steps_by_turn,
            "events": events,
            "file_changes": file_changes,
            "terminal_chunks": terminal,
            "context_items": context_items,
            "permission_requests": permissions_all,
        }

    @app.get("/api/v2/sessions/{session_id}/export.json")
    async def export_session_json_v2(session_id: str) -> Response:
        data = _collect_session_export(session_id)
        body = json.dumps(data, ensure_ascii=False, indent=2)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{session_id}.json"'},
        )

    @app.get("/api/v2/sessions/{session_id}/export.md")
    async def export_session_markdown_v2(session_id: str) -> PlainTextResponse:
        data = _collect_session_export(session_id)
        sess = data["session"]
        title = str(sess.get("title") or "Session").strip()

        lines: list[str] = []
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"- Session ID: `{sess.get('id', session_id)}`")
        lines.append(f"- Created: `{sess.get('created_at', '')}`")
        lines.append(f"- Updated: `{sess.get('updated_at', '')}`")
        lines.append(f"- Exported: `{data.get('exported_at', '')}`")
        lines.append("")

        # Chat transcript
        lines.append("## Messages")
        lines.append("")
        for m in data.get("messages", []):
            role = str(m.get("role") or "")
            content = str(m.get("content") or "")
            ts = str(m.get("ts") or m.get("created_at") or "")
            lines.append(f"### {role}")
            if ts:
                lines.append(f"*{ts}*")
            lines.append("")
            lines.append(content)
            lines.append("")

        # Events (compact)
        lines.append("## Events")
        lines.append("")
        for e in data.get("events", [])[-500:]:
            seq = e.get("seq")
            etype = e.get("type")
            ts = e.get("ts")
            turn_id = e.get("turn_id") or ""
            step_id = e.get("step_id") or ""
            lines.append(f"- `{seq}` `{etype}` `{turn_id}` `{step_id}` `{ts}`")
        lines.append("")

        # File changes
        lines.append("## File Changes")
        lines.append("")
        for fc in data.get("file_changes", [])[:200]:
            path = fc.get("path") or "unknown"
            diff_text = fc.get("diff") or ""
            lines.append(f"### `{path}`")
            lines.append("")
            lines.append("```diff")
            lines.append(diff_text.rstrip("\n"))
            lines.append("```")
            lines.append("")

        # Terminal
        lines.append("## Terminal")
        lines.append("")
        term_text = "".join([str(r.get("text") or "") for r in data.get("terminal_chunks", [])])
        if term_text.strip():
            lines.append("```text")
            lines.append(term_text.rstrip("\n"))
            lines.append("```")
            lines.append("")
        else:
            lines.append("(no terminal output)")
            lines.append("")

        # Context
        lines.append("## Context Items")
        lines.append("")
        for ci in data.get("context_items", [])[:200]:
            pinned = "pinned" if int(ci.get("pinned") or 0) == 1 else "unpinned"
            lines.append(f"- `{pinned}` `{ci.get('kind','')}` {ci.get('title','')}")
        lines.append("")

        # Permissions
        lines.append("## Permission Requests")
        lines.append("")
        for pr in data.get("permission_requests", [])[:200]:
            lines.append(
                f"- `{pr.get('status','')}` `{pr.get('scope','')}` `{pr.get('tool_name','')}` `{pr.get('id','')}`"
            )
        lines.append("")

        body = "\n".join(lines).rstrip("\n") + "\n"
        return PlainTextResponse(
            content=body,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{session_id}.md"'},
        )

    @app.patch("/api/v2/sessions/{session_id}")
    async def patch_session_v2(session_id: str, payload: SessionPatchRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        db.update_session_title(session_id, payload.title)
        return db.get_session(session_id) or {"id": session_id, "title": payload.title}

    @app.delete("/api/v2/sessions/{session_id}")
    async def delete_session_v2(session_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        async with sessions_lock:
            task = running_tasks.pop(session_id, None)
            if task and not task.done():
                task.cancel()
        db.delete_session(session_id)
        return {"deleted": True}

    # v1 aliases (keep old clients working)
    @app.post("/api/v1/sessions")
    async def create_session_v1(payload: SessionCreateRequest) -> dict[str, Any]:
        return await create_session_v2(payload)

    @app.get("/api/v1/sessions")
    async def list_sessions_v1() -> list[dict[str, Any]]:
        return await list_sessions_v2()

    @app.get("/api/v1/sessions/{session_id}")
    async def get_session_v1(session_id: str) -> dict[str, Any]:
        return await get_session_v2(session_id)

    @app.patch("/api/v1/sessions/{session_id}")
    async def patch_session_v1(session_id: str, payload: SessionPatchRequest) -> dict[str, Any]:
        return await patch_session_v2(session_id, payload)

    @app.delete("/api/v1/sessions/{session_id}")
    async def delete_session_v1(session_id: str) -> dict[str, Any]:
        return await delete_session_v2(session_id)

    # ── Auto-naming helper ────────────────────────────────────────

    async def _auto_name_session(session_id: str, user_text: str) -> None:
        if provider is None:
            return
        try:
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
            resp = await provider.chat(messages=naming_messages, tools=[], model=model)
            title = (resp.content or "").strip().strip('"').strip("'")[:30]
            if not title:
                title = user_text[:20].strip()
        except Exception:
            title = user_text[:20].strip()
        if title:
            db.update_session_title(session_id, title)

    # ── Turns / Agent Runs ────────────────────────────────────────

    async def _start_turn(session_id: str, content: str) -> dict[str, Any]:
        runner_ = _require_runner()
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        async with sessions_lock:
            existing = running_tasks.get(session_id)
            if existing and not existing.done():
                raise HTTPException(status_code=409, detail="session is busy")

        # Persist user message (history)
        db.add_message(session_id, "user", content)
        db.touch_session(session_id)

        # Auto-name on first user message
        messages = db.get_messages(session_id)
        user_count = len([m for m in messages if m["role"] == "user"])
        is_first = user_count == 1

        # Create turn record (v2)
        turn = db.create_turn(session_id, content)
        turn_id = turn["id"]

        async def run_turn_task() -> None:
            try:
                if is_first:
                    asyncio.create_task(_auto_name_session(session_id, content))

                assistant_text = await runner_.run_turn(session_id=session_id, turn_id=turn_id, user_text=content)
                if assistant_text:
                    db.add_message(session_id, "assistant", assistant_text)
            except asyncio.CancelledError:
                # Emit a lightweight error event for UI visibility.
                step = db.create_step(turn_id, idx=9999)
                await bus.publish(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_id=step["id"],
                    type="error",
                    payload={"code": "CANCELLED", "message": "Run cancelled by user"},
                )
                db.finish_step(step["id"], status="error")
                raise
            except Exception as exc:
                step = db.create_step(turn_id, idx=9999)
                await bus.publish(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_id=step["id"],
                    type="error",
                    payload={"code": "TURN_ERROR", "message": str(exc)},
                )
                db.finish_step(step["id"], status="error")
            finally:
                async with sessions_lock:
                    running_tasks.pop(session_id, None)
                db.touch_session(session_id)

        task = asyncio.create_task(run_turn_task())
        async with sessions_lock:
            running_tasks[session_id] = task

        return {"accepted": True, "session_id": session_id, "turn_id": turn_id}

    @app.post("/api/v2/sessions/{session_id}/turns")
    async def create_turn_v2(session_id: str, payload: TurnCreateRequest) -> dict[str, Any]:
        return await _start_turn(session_id, payload.content)

    # v1 alias: POST message starts a turn
    @app.post("/api/v1/sessions/{session_id}/messages")
    async def post_message_v1(session_id: str, payload: MessageCreateRequest) -> dict[str, Any]:
        return await _start_turn(session_id, payload.content)

    @app.get("/api/v2/sessions/{session_id}/turns")
    async def list_turns_v2(session_id: str) -> list[dict[str, Any]]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return db.list_turns(session_id)

    @app.get("/api/v2/turns/{turn_id}")
    async def get_turn_v2(turn_id: str) -> dict[str, Any]:
        rec = db.get_turn(turn_id)
        if not rec:
            raise HTTPException(status_code=404, detail="turn not found")
        return rec

    @app.get("/api/v2/turns/{turn_id}/steps")
    async def list_steps_v2(turn_id: str) -> list[dict[str, Any]]:
        if not db.get_turn(turn_id):
            raise HTTPException(status_code=404, detail="turn not found")
        return db.list_steps(turn_id)

    # ── Cancel ───────────────────────────────────────────────────

    @app.post("/api/v2/sessions/{session_id}/cancel")
    async def cancel_v2(session_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        async with sessions_lock:
            task = running_tasks.get(session_id)
            if task and not task.done():
                task.cancel()
                running_tasks.pop(session_id, None)
                return {"cancelled": True}
        return {"cancelled": False, "reason": "no active run"}

    @app.post("/api/v1/sessions/{session_id}/cancel")
    async def cancel_v1(session_id: str) -> dict[str, Any]:
        return await cancel_v2(session_id)

    # ── Memory (legacy, kept) ─────────────────────────────────────

    @app.get("/api/v1/memory")
    async def get_memory_v1() -> dict[str, str]:
        return db.get_memory()

    @app.put("/api/v1/memory")
    async def put_memory_v1(payload: MemoryPutRequest) -> dict[str, Any]:
        db.put_memory(payload.key, payload.value)
        return {"ok": True, "key": payload.key}

    @app.delete("/api/v1/memory/{key}")
    async def delete_memory_v1(key: str) -> dict[str, Any]:
        deleted = db.delete_memory(key)
        if not deleted:
            raise HTTPException(status_code=404, detail="key not found")
        return {"deleted": True}

    # ── Tools ────────────────────────────────────────────────────

    @app.get("/api/v2/tools")
    async def list_tools_v2() -> dict[str, Any]:
        defs = runner._tools.get_definitions() if runner is not None else []  # type: ignore[attr-defined]
        perms = db.get_tool_permissions()
        return {
            "tools": defs,
            "tool_permissions": perms,
            "tool_enabled": {
                "run_command": settings.tool_enabled_run_command,
                "read_file": settings.tool_enabled_read_file,
                "write_file": settings.tool_enabled_write_file,
                "apply_patch": settings.tool_enabled_apply_patch,
                "search": settings.tool_enabled_search,
                "http_fetch": settings.tool_enabled_http_fetch,
            },
        }

    # ── Artifacts for Inspector ───────────────────────────────────

    @app.get("/api/v2/sessions/{session_id}/file_changes")
    async def list_file_changes(session_id: str) -> list[dict[str, Any]]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return db.list_file_changes(session_id)

    @app.get("/api/v2/sessions/{session_id}/terminal")
    async def list_terminal(session_id: str) -> list[dict[str, Any]]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return db.list_terminal_chunks(session_id)

    @app.get("/api/v2/sessions/{session_id}/context")
    async def list_context(session_id: str) -> list[dict[str, Any]]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return db.list_context_items(session_id)

    @app.post("/api/v2/sessions/{session_id}/context/pin")
    async def pin_context(session_id: str, payload: ContextPinRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        db.set_context_pinned(payload.context_id, True)
        return {"ok": True}

    @app.post("/api/v2/sessions/{session_id}/context/unpin")
    async def unpin_context(session_id: str, payload: ContextPinRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        db.set_context_pinned(payload.context_id, False)
        return {"ok": True}

    # ── Permissions ───────────────────────────────────────────────

    @app.get("/api/v2/sessions/{session_id}/permissions/pending")
    async def pending_permissions(session_id: str) -> list[dict[str, Any]]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return db.list_pending_permission_requests(session_id)

    @app.post("/api/v2/permissions/{request_id}/resolve")
    async def resolve_permission(request_id: str, payload: PermissionResolveRequest) -> dict[str, Any]:
        await permissions.resolve(
            request_id=request_id,
            status=payload.status,  # type: ignore[arg-type]
            scope=payload.scope,    # type: ignore[arg-type]
        )
        return {"ok": True}

    # ── Events (Replay) ──────────────────────────────────────────

    @app.get("/api/v2/sessions/{session_id}/events")
    async def get_session_events(session_id: str, since: int | None = None, since_seq: int | None = None) -> list[dict[str, Any]]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return db.get_session_events_v2(session_id=session_id, since_id=since, since_seq=since_seq)

    # ── SSE: Global Event Stream ──────────────────────────────────

    @app.get("/event")
    async def stream_event_bus(request: Request, session_id: str | None = None, since: int | None = None):
        header_last_id = request.headers.get("last-event-id")
        initial_last_id: int | None = None
        if since is not None:
            initial_last_id = int(since)
        elif header_last_id:
            try:
                initial_last_id = int(header_last_id)
            except Exception:
                initial_last_id = None

        async def event_stream():
            last_id = initial_last_id

            # connected (not persisted)
            connected = {
                "id": 0,
                "seq": 0,
                "ts": _now_ts(),
                "type": "connected",
                "session_id": session_id or "",
                "turn_id": "",
                "step_id": "",
                "payload": {"server_time": _now_iso(), "latest_id": last_id or 0},
            }
            yield f"event: connected\ndata: {json.dumps(connected, ensure_ascii=False)}\n\n"

            # backlog
            pending = bus.get_events_since(session_id=session_id, since_id=last_id)
            for item in pending:
                last_id = int(item.get("id", last_id or 0) or 0)
                payload = json.dumps(item, ensure_ascii=False)
                yield f"id: {item.get('id')}\nevent: event\ndata: {payload}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                has_new = await bus.wait_for_new(timeout_s=settings.sse_wait_timeout_s)
                if not has_new:
                    hb = {
                        "id": 0,
                        "seq": 0,
                        "ts": _now_ts(),
                        "type": "heartbeat",
                        "session_id": session_id or "",
                        "turn_id": "",
                        "step_id": "",
                        "payload": {},
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(hb, ensure_ascii=False)}\n\n"
                    continue

                new_items = bus.get_events_since(session_id=session_id, since_id=last_id)
                for item in new_items:
                    last_id = int(item.get("id", last_id or 0) or 0)
                    payload = json.dumps(item, ensure_ascii=False)
                    yield f"id: {item.get('id')}\nevent: event\ndata: {payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Legacy per-session SSE path (v1 clients). Uses the v2 event envelope.
    @app.get("/api/v1/sessions/{session_id}/events")
    async def stream_session_events_v1(session_id: str, request: Request, last_event_id: int | None = None):
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return await stream_event_bus(request, session_id=session_id, since=last_event_id)

    # ── Config / Provider / Model Management ──────────────────────

    # Known models per provider for auto-detection
    KNOWN_MODELS = {
        "openrouter": [
            {"id": "openrouter/anthropic/claude-sonnet-4", "name": "Claude Sonnet 4"},
            {"id": "openrouter/anthropic/claude-opus-4", "name": "Claude Opus 4"},
            {"id": "openrouter/anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet"},
            {"id": "openrouter/google/gemini-2.5-pro-preview", "name": "Gemini 2.5 Pro"},
            {"id": "openrouter/google/gemini-2.5-flash-preview", "name": "Gemini 2.5 Flash"},
            {"id": "openrouter/deepseek/deepseek-r1", "name": "DeepSeek R1"},
            {"id": "openrouter/deepseek/deepseek-chat-v3", "name": "DeepSeek Chat V3"},
            {"id": "openrouter/meta-llama/llama-4-maverick", "name": "Llama 4 Maverick"},
            {"id": "openrouter/openai/gpt-4.1", "name": "GPT-4.1"},
            {"id": "openrouter/openai/o4-mini", "name": "o4-mini"},
        ],
        "anthropic": [
            {"id": "anthropic/claude-opus-4-5", "name": "Claude Opus 4.5"},
            {"id": "anthropic/claude-sonnet-4-5", "name": "Claude Sonnet 4.5"},
            {"id": "anthropic/claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "anthropic/claude-haiku-3-5", "name": "Claude Haiku 3.5"},
        ],
        "openai": [
            {"id": "openai/gpt-4.1", "name": "GPT-4.1"},
            {"id": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "openai/gpt-4.1-nano", "name": "GPT-4.1 Nano"},
            {"id": "openai/o4-mini", "name": "o4-mini"},
            {"id": "openai/o3", "name": "o3"},
            {"id": "openai/o3-mini", "name": "o3-mini"},
        ],
        "deepseek": [
            {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat"},
            {"id": "deepseek/deepseek-reasoner", "name": "DeepSeek Reasoner"},
        ],
        "gemini": [
            {"id": "gemini/gemini-2.5-pro-preview-06-05", "name": "Gemini 2.5 Pro"},
            {"id": "gemini/gemini-2.5-flash-preview-05-20", "name": "Gemini 2.5 Flash"},
            {"id": "gemini/gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
        ],
        "groq": [
            {"id": "groq/llama-3.3-70b-versatile", "name": "Llama 3.3 70B"},
            {"id": "groq/llama-3.1-8b-instant", "name": "Llama 3.1 8B"},
            {"id": "groq/gemma2-9b-it", "name": "Gemma 2 9B"},
        ],
        "zhipu": [
            {"id": "zhipu/glm-4-plus", "name": "GLM-4 Plus"},
            {"id": "zhipu/glm-4-flash", "name": "GLM-4 Flash"},
        ],
        "moonshot": [
            {"id": "moonshot/moonshot-v1-auto", "name": "Moonshot V1 Auto"},
        ],
    }

    class ProviderUpdateRequest(BaseModel):
        api_key: str = ""
        api_base: str | None = None

    class ModelSelectRequest(BaseModel):
        model: str = Field(min_length=1)

    @app.get("/api/v2/providers")
    async def list_providers() -> dict[str, Any]:
        """List all providers with connection status."""
        providers_list = []
        provider_configs = {
            "anthropic": config.providers.anthropic,
            "openai": config.providers.openai,
            "openrouter": config.providers.openrouter,
            "deepseek": config.providers.deepseek,
            "gemini": config.providers.gemini,
            "groq": config.providers.groq,
            "zhipu": config.providers.zhipu,
            "moonshot": config.providers.moonshot,
        }
        for name, prov in provider_configs.items():
            connected = bool(prov.api_key)
            hint = ""
            if connected and len(prov.api_key) > 4:
                hint = prov.api_key[-4:]
            providers_list.append({
                "id": name,
                "name": name.title(),
                "connected": connected,
                "has_api_key": connected,
                "key_hint": hint,
                "api_base": prov.api_base or None,
            })
        return {"providers": providers_list}

    @app.put("/api/v2/providers/{provider_id}")
    async def update_provider(provider_id: str, payload: ProviderUpdateRequest) -> dict[str, Any]:
        """Update provider API key and base URL. Persists to config file."""
        from nanobot.config.loader import load_config as _load, save_config, get_config_path

        valid_providers = ["anthropic", "openai", "openrouter", "deepseek", "gemini", "groq", "zhipu", "moonshot"]
        if provider_id not in valid_providers:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_id}")

        # Load fresh config, update, save
        cfg = _load()
        prov = getattr(cfg.providers, provider_id)
        if payload.api_key:
            prov.api_key = payload.api_key
        if payload.api_base is not None:
            prov.api_base = payload.api_base or None
        setattr(cfg.providers, provider_id, prov)
        save_config(cfg)

        return {"ok": True, "provider": provider_id, "connected": bool(prov.api_key)}

    @app.delete("/api/v2/providers/{provider_id}")
    async def disconnect_provider(provider_id: str) -> dict[str, Any]:
        """Remove provider API key."""
        from nanobot.config.loader import load_config as _load, save_config

        valid_providers = ["anthropic", "openai", "openrouter", "deepseek", "gemini", "groq", "zhipu", "moonshot"]
        if provider_id not in valid_providers:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_id}")

        cfg = _load()
        prov = getattr(cfg.providers, provider_id)
        prov.api_key = ""
        prov.api_base = None
        setattr(cfg.providers, provider_id, prov)
        save_config(cfg)

        return {"ok": True, "provider": provider_id, "connected": False}

    @app.get("/api/v2/models")
    async def list_models() -> dict[str, Any]:
        """List available models based on connected providers."""
        available = []
        provider_configs = {
            "anthropic": config.providers.anthropic,
            "openai": config.providers.openai,
            "openrouter": config.providers.openrouter,
            "deepseek": config.providers.deepseek,
            "gemini": config.providers.gemini,
            "groq": config.providers.groq,
            "zhipu": config.providers.zhipu,
            "moonshot": config.providers.moonshot,
        }
        for name, prov in provider_configs.items():
            if prov.api_key:
                models = KNOWN_MODELS.get(name, [])
                for m in models:
                    available.append({**m, "provider": name})

        return {
            "models": available,
            "current": model,
        }

    @app.put("/api/v2/model")
    async def set_model(payload: ModelSelectRequest) -> dict[str, Any]:
        """Set the active model. Persists to config file."""
        from nanobot.config.loader import load_config as _load, save_config

        cfg = _load()
        cfg.agents.defaults.model = payload.model
        save_config(cfg)

        # NOTE: model change takes effect on next turn (runner uses module-level `model` variable).
        # A full restart may be needed for the model to change completely.
        nonlocal model
        model = payload.model

        return {"ok": True, "model": payload.model}

    # ── UI serving / proxy ────────────────────────────────────────

    mimetypes.add_type("application/manifest+json", ".webmanifest")

    async def _proxy_to(target_base: str, request: Request, full_path: str) -> Response:
        base = target_base.rstrip("/")
        path = "/" + full_path if full_path else "/"
        url = base + path
        if request.url.query:
            url = url + "?" + request.url.query

        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length", "connection")
        }
        body = await request.body()

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            r = await client.request(request.method, url, headers=headers, content=body)

        # Avoid hop-by-hop headers
        excluded = {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
        out_headers = {k: v for k, v in r.headers.items() if k.lower() not in excluded}
        return Response(content=r.content, status_code=r.status_code, headers=out_headers)

    # Static mode: serve from built dist directory
    dist_dir = settings.resolved_ui_static_dir()
    legacy_static_dir = Path(__file__).parent / "static"

    if settings.ui_mode == "static" and dist_dir.exists():
        # Serve built assets
        if (dist_dir / "assets").exists():
            app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")
        if (dist_dir / "icons").exists():
            app.mount("/icons", StaticFiles(directory=str(dist_dir / "icons")), name="icons")

        @app.get("/manifest.webmanifest")
        async def serve_manifest():
            p = dist_dir / "manifest.webmanifest"
            if p.exists():
                return FileResponse(str(p), media_type="application/manifest+json")
            raise HTTPException(status_code=404)

        @app.get("/sw.js")
        async def serve_sw():
            p = dist_dir / "sw.js"
            if p.exists():
                return FileResponse(
                    str(p),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"},
                )
            raise HTTPException(status_code=404)

        # Serve legacy mounts for static resources if present
        if legacy_static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(legacy_static_dir)), name="static")

        @app.get("/")
        async def serve_index():
            if missing_llm_config:
                return _setup_page()
            p = dist_dir / "index.html"
            if p.exists():
                return FileResponse(str(p), headers={"Cache-Control": "no-store"})
            raise HTTPException(status_code=404)

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if missing_llm_config:
                if full_path.startswith("api/"):
                    raise HTTPException(status_code=404)
                return _setup_page()
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)

            # If a real file exists, serve it.
            candidate = (dist_dir / full_path)
            try:
                if candidate.exists() and candidate.is_file():
                    return FileResponse(str(candidate))
            except Exception:
                pass

            # Don't fall back for missing static assets
            if full_path.startswith(("static/", "assets/", "icons/")):
                raise HTTPException(status_code=404)

            p = dist_dir / "index.html"
            if p.exists():
                return FileResponse(str(p), headers={"Cache-Control": "no-store"})
            raise HTTPException(status_code=404)

    else:
        # Proxy mode (remote/dev): proxy all non-API routes to the UI origin.
        @app.api_route("/", methods=["GET", "HEAD"])
        async def proxy_root(request: Request):
            if missing_llm_config:
                return _setup_page()
            target = settings.ui_url if settings.ui_mode == "remote" else settings.ui_dev_server_url
            return await _proxy_to(target, request, "")

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"])
        async def proxy_catchall(full_path: str, request: Request):
            if full_path.startswith("api/") or full_path.startswith("docs") or full_path == "openapi.json":
                raise HTTPException(status_code=404)
            if missing_llm_config:
                return _setup_page()
            target = settings.ui_url if settings.ui_mode == "remote" else settings.ui_dev_server_url
            return await _proxy_to(target, request, full_path)

    return app
