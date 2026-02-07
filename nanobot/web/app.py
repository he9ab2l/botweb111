"""FastAPI web application for fanfan (OpenCode-style WebUI).

Key properties:
- Two-stage WebUI: UI is served or reverse-proxied at `/` (same-origin)
- Global SSE bus: `GET /event` (reconnect + replay)
- SQLite persistence: sessions/messages + v2 turns/steps/events + artifacts
- Agent runner: OpenCode-style tool loop with streaming parts
"""

from __future__ import annotations

import asyncio
import os
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

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.web.database import Database
from nanobot.web.event_bus import EventBus
from nanobot.web.permissions import PermissionManager
from nanobot.web.runner import FanfanWebRunner
from nanobot.web.settings import WebSettings, repo_root


APP_VERSION = "0.4.3"


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


class PermissionModeRequest(BaseModel):
    mode: str = Field(pattern="^(ask|allow)$")


class ContextPinRequest(BaseModel):
    context_id: str = Field(min_length=1)


class ContextPinnedRefRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    content_ref: str = Field(min_length=1, max_length=4096)
    pinned: bool = True


class FsRollbackRequest(BaseModel):
    path: str = Field(min_length=1)
    version_id: str = Field(min_length=1)


class SessionModelSetRequest(BaseModel):
    model: str = Field(min_length=1)


class ProviderUpdateRequest(BaseModel):
    api_key: str | None = None
    api_base: str | None = None


class ConfigUpdateRequest(BaseModel):
    default_model: str | None = None
    providers: dict[str, ProviderUpdateRequest] | None = None


def create_app() -> FastAPI:
    settings = WebSettings()

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

    def _load_cfg():
        return load_config()

    def _any_provider_key(cfg) -> bool:
        try:
            p = cfg.providers
            return bool(
                p.openrouter.api_key
                or p.anthropic.api_key
                or p.openai.api_key
                or p.deepseek.api_key
                or p.groq.api_key
                or p.zhipu.api_key
                or p.vllm.api_key
                or p.gemini.api_key
                or p.moonshot.api_key
            )
        except Exception:
            return bool(cfg.get_api_key())

    def _llm_configured() -> bool:
        cfg = _load_cfg()
        return bool(_any_provider_key(cfg) or cfg.agents.defaults.model.startswith("bedrock/"))

    def _effective_model(cfg, session_id: str) -> tuple[str, str | None, str]:
        default_model = cfg.agents.defaults.model
        override = db.get_session_model_override(session_id) if session_id else None
        effective = override or default_model
        return effective, override, default_model

    def _make_provider(cfg, model: str) -> LiteLLMProvider:
        return LiteLLMProvider(
            api_key=cfg.get_api_key(model),
            api_base=cfg.get_api_base(model),
            default_model=model,
        )

    def _make_runner_for_session(session_id: str) -> tuple[FanfanWebRunner, str]:
        cfg = _load_cfg()
        model, _override, _default = _effective_model(cfg, session_id)
        api_key = cfg.get_api_key(model)
        is_bedrock = model.startswith("bedrock/")
        if not api_key and not is_bedrock:
            raise HTTPException(
                status_code=503,
                detail=(
                    "LLM not configured. Open Settings and add a provider API key (e.g. GLM/Z.ai), "
                    "then retry."
                ),
            )

        provider = _make_provider(cfg, model)
        runner = FanfanWebRunner(
            db=db,
            bus=bus,
            permissions=permissions,
            provider=provider,
            settings=settings,
            model=model,
            max_iterations=cfg.agents.defaults.max_tool_iterations,
            brave_api_key=cfg.tools.web.search.api_key or None,
        )
        return runner, model

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
            demo_user = "Demo: show a tool call and a diff."
            demo_assistant = "Demo completed. You should see tool cards and a diff in the inspector."

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
          <p>Create <span class="pill">~/.nanobot/config.json</span> and set at least one provider key (for example <code>providers.openrouter.apiKey</code>).</p>
          <pre><code>mkdir -p ~/.nanobot

# From the project root:
cp ./config.example.json ~/.nanobot/config.json

# Then edit ~/.nanobot/config.json and set your apiKey
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


    # ── Health ───────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "time": _now_iso(),
            "version": APP_VERSION,
            "llm_configured": _llm_configured(),
            "ui_mode": settings.ui_mode,
        }

    @app.get("/api/v2/health")
    async def health_v2() -> dict[str, Any]:
        return {
            "ok": True,
            "time": _now_iso(),
            "version": APP_VERSION,
            "llm_configured": _llm_configured(),
            "db_path": str(settings.resolved_db_path()),
        }

    # Legacy health path
    @app.get("/api/v1/health")
    async def health_v1() -> dict[str, Any]:
        return await health_v2()

    # ── Config / Models ─────────────────────────────────────────

    def _config_summary(cfg) -> dict[str, Any]:
        p = cfg.providers
        return {
            "config_path": str(get_config_path()),
            "default_model": cfg.agents.defaults.model,
            "llm_configured": _llm_configured(),
            "providers": {
                "openrouter": {
                    "configured": bool(p.openrouter.api_key),
                    "api_base": p.openrouter.api_base or "https://openrouter.ai/api/v1",
                },
                "anthropic": {"configured": bool(p.anthropic.api_key), "api_base": p.anthropic.api_base},
                "openai": {"configured": bool(p.openai.api_key), "api_base": p.openai.api_base},
                "deepseek": {"configured": bool(p.deepseek.api_key), "api_base": p.deepseek.api_base},
                "gemini": {"configured": bool(p.gemini.api_key), "api_base": p.gemini.api_base},
                "groq": {"configured": bool(p.groq.api_key), "api_base": p.groq.api_base},
                "moonshot": {"configured": bool(p.moonshot.api_key), "api_base": p.moonshot.api_base},
                "zhipu": {"configured": bool(p.zhipu.api_key), "api_base": p.zhipu.api_base},
                "vllm": {"configured": bool(p.vllm.api_key), "api_base": p.vllm.api_base},
            },
            "recommended_models": [
                "anthropic/claude-opus-4-5",
                "openrouter/anthropic/claude-3.5-sonnet",
                "openai/gpt-4o",
                "zai/glm-4",
                "zai/glm-4-plus",
            ],
        }

    @app.get("/api/v2/config")
    async def get_config_v2() -> dict[str, Any]:
        cfg = _load_cfg()
        return _config_summary(cfg)

    @app.post("/api/v2/config")
    async def update_config_v2(payload: ConfigUpdateRequest) -> dict[str, Any]:
        cfg = _load_cfg()

        if payload.default_model is not None:
            cfg.agents.defaults.model = (payload.default_model or "").strip()

        if payload.providers is not None:
            allowed = {
                "openrouter",
                "anthropic",
                "openai",
                "deepseek",
                "gemini",
                "groq",
                "moonshot",
                "zhipu",
                "vllm",
            }
            for name, upd in (payload.providers or {}).items():
                if name not in allowed:
                    raise HTTPException(status_code=400, detail=f"Unknown provider: {name}")
                p = getattr(cfg.providers, name)
                if upd.api_key is not None:
                    p.api_key = (upd.api_key or "").strip()
                if upd.api_base is not None:
                    b = (upd.api_base or "").strip()
                    p.api_base = b or None

        save_config(cfg)
        return _config_summary(cfg)

    # ── Docs / Knowledge Base ─────────────────────────────────

    _DOCS_DEFAULT = [
        {"id": "project_guide", "title": "PROJECT_GUIDE.md", "path": "PROJECT_GUIDE.md"},
        {"id": "nanobot_arch", "title": "Nanobot 架构方案", "path": "DESIGN.md"},
        {"id": "full_flow", "title": "全流程实现", "path": "DEPLOY.md"},
        {"id": "readme", "title": "README.md", "path": "README.md"},
        {"id": "communication", "title": "COMMUNICATION.md", "path": "COMMUNICATION.md"},
    ]

    _DOCS_IGNORE_DIRS = {
        ".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__",
        "dist", "build", ".mypy_cache", ".ruff_cache", ".pytest_cache",
        "data", "workspace", ".cache", ".next", ".turbo", ".idea", ".vscode",
    }

    def _docs_root() -> Path:
        return repo_root().resolve()

    def _docs_default_paths() -> set[str]:
        return {d["path"] for d in _DOCS_DEFAULT}

    def _safe_doc_path(rel: str) -> Path | None:
        if not rel:
            return None
        p = Path(rel).as_posix().lstrip("/")
        root = _docs_root()
        candidate = (root / p).resolve()

        # Docs API is intentionally restricted to markdown to avoid accidental secret leaks
        # (e.g. reading .git/config or other non-doc files under the repo root).
        if candidate.suffix.lower() not in (".md", ".markdown"):
            return None

        try:
            if candidate.is_file() and candidate.is_relative_to(root):
                return candidate
        except Exception:
            return None
        return None

    def _discover_docs(max_depth: int = 3) -> list[dict[str, str]]:
        root = _docs_root()
        out: list[dict[str, str]] = []
        default_paths = _docs_default_paths()

        for dirpath, dirnames, filenames in os.walk(root):
            rel = Path(dirpath).resolve().relative_to(root)
            depth = len(rel.parts) if str(rel) != '.' else 0
            if depth > max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in _DOCS_IGNORE_DIRS]

            for fname in filenames:
                if not fname.lower().endswith(".md"):
                    continue
                rel_path = (Path(dirpath) / fname).resolve().relative_to(root).as_posix()
                if rel_path in default_paths:
                    continue
                doc_id = rel_path.replace('/', '_').replace('.', '_')
                out.append({"id": doc_id, "title": fname, "path": rel_path})

        return out

    @app.get("/api/v2/docs")
    async def list_docs_v2() -> dict[str, Any]:
        root = _docs_root()
        defaults: list[dict[str, Any]] = []
        for doc in _DOCS_DEFAULT:
            p = _safe_doc_path(doc["path"])
            defaults.append({**doc, "exists": bool(p)})

        extra = _discover_docs(max_depth=3)
        return {"root": str(root), "default": defaults, "extra": extra}

    @app.get("/api/v2/docs/file")
    async def read_doc_v2(path: str) -> dict[str, Any]:
        p = _safe_doc_path(path)
        if p is None:
            raise HTTPException(status_code=404, detail="doc not found")

        raw = p.read_text(encoding="utf-8", errors="replace")
        max_chars = 200_000
        truncated = len(raw) > max_chars
        content = raw[:max_chars]

        return {
            "path": p.resolve().relative_to(_docs_root()).as_posix(),
            "title": p.name,
            "content": content,
            "truncated": truncated,
        }

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

    @app.get("/api/v2/sessions/{session_id}/model")
    async def get_session_model_v2(session_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        cfg = _load_cfg()
        override = db.get_session_model_override(session_id)
        default_model = cfg.agents.defaults.model
        effective = override or default_model
        return {
            "session_id": session_id,
            "default_model": default_model,
            "override_model": override,
            "effective_model": effective,
        }

    @app.post("/api/v2/sessions/{session_id}/model")
    async def set_session_model_v2(session_id: str, payload: SessionModelSetRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        m = (payload.model or "").strip()
        if not m:
            raise HTTPException(status_code=400, detail="model is required")
        db.set_session_model_override(session_id, m)
        return await get_session_model_v2(session_id)

    @app.delete("/api/v2/sessions/{session_id}/model")
    async def clear_session_model_v2(session_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        db.clear_session_model_override(session_id)
        return await get_session_model_v2(session_id)

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
        try:
            cfg = _load_cfg()
            eff_model, _override, _default = _effective_model(cfg, session_id)
            api_key = cfg.get_api_key(eff_model)
            is_bedrock = eff_model.startswith("bedrock/")
            if not api_key and not is_bedrock:
                return

            provider = _make_provider(cfg, eff_model)

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
            resp = await provider.chat(messages=naming_messages, tools=[], model=eff_model)
            title = (resp.content or "").strip().strip('"').strip("'")[:30]
            if not title:
                title = user_text[:20].strip()
        except Exception:
            title = user_text[:20].strip()
        if title:
            db.update_session_title(session_id, title)

    # ── Turns / Agent Runs ────────────────────────────────────────

    async def _start_turn(session_id: str, content: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        async with sessions_lock:
            existing = running_tasks.get(session_id)
            if existing and not existing.done():
                raise HTTPException(status_code=409, detail="session is busy")

        runner_, effective_model = _make_runner_for_session(session_id)

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

        return {"accepted": True, "session_id": session_id, "turn_id": turn_id, "model": effective_model}

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

    def _tool_registry():
        cfg = _load_cfg()
        brave_api_key = cfg.tools.web.search.api_key or None
        fs_root_ = settings.resolved_fs_root().expanduser().resolve()

        from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
        from nanobot.agent.tools.opencode import HttpFetchTool, SearchTool
        from nanobot.agent.tools.patch import ApplyPatchTool
        from nanobot.agent.tools.registry import ToolRegistry
        from nanobot.web.runner import SpawnSubagentTool

        reg = ToolRegistry()
        reg.register(ReadFileTool(root=fs_root_))
        reg.register(WriteFileTool(root=fs_root_))
        reg.register(ApplyPatchTool(allowed_root=fs_root_))
        reg.register(SearchTool(api_key=brave_api_key))
        reg.register(HttpFetchTool())
        reg.register(SpawnSubagentTool(None))
        return reg

    def _tool_def_name(d: dict[str, Any]) -> str | None:
        if not isinstance(d, dict):
            return None
        fn = d.get('function')
        if isinstance(fn, dict) and fn.get('name'):
            return str(fn.get('name'))
        if d.get('name'):
            return str(d.get('name'))
        return None

    def _tool_names() -> list[str]:
        reg = _tool_registry()
        names: list[str] = []
        for d in reg.get_definitions():
            name = _tool_def_name(d)
            if name:
                names.append(name)
        return names

    def _permission_mode(tool_names: list[str]) -> str:
        perms = db.get_tool_permissions()
        if not tool_names:
            return 'ask'
        values = [perms.get(n) for n in tool_names]
        if all(v == 'allow' for v in values):
            return 'allow'
        if all((v is None or v == '' or v == 'ask') for v in values):
            return 'ask'
        return 'custom'

    @app.get("/api/v2/permissions/mode")
    async def get_permission_mode() -> dict[str, Any]:
        names = _tool_names()
        return {"mode": _permission_mode(names), "tools": names}

    @app.post("/api/v2/permissions/mode")
    async def set_permission_mode(payload: PermissionModeRequest) -> dict[str, Any]:
        names = _tool_names()
        mode = (payload.mode or '').strip()
        if mode not in ('ask', 'allow'):
            raise HTTPException(status_code=400, detail='invalid mode')
        policies = {n: mode for n in names}
        db.set_tool_permissions_bulk(policies)
        return {"ok": True, "mode": mode}

    @app.get("/api/v2/tools")
    async def list_tools_v2() -> dict[str, Any]:
        reg = _tool_registry()
        defs = reg.get_definitions()
        perms = db.get_tool_permissions()
        names = []
        for d in defs:
            name = _tool_def_name(d)
            if name:
                names.append(name)
        return {
            "tools": defs,
            "tool_permissions": perms,
            "permission_mode": _permission_mode(names),
            "tool_enabled": {
                "run_command": settings.tool_enabled_run_command,
                "read_file": settings.tool_enabled_read_file,
                "write_file": settings.tool_enabled_write_file,
                "apply_patch": settings.tool_enabled_apply_patch,
                "search": settings.tool_enabled_search,
                "http_fetch": settings.tool_enabled_http_fetch,
                "spawn_subagent": settings.tool_enabled("spawn_subagent"),
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

    @app.post("/api/v2/sessions/{session_id}/context/set_pinned_ref")
    async def set_context_pinned_ref(session_id: str, payload: ContextPinnedRefRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        kind = (payload.kind or "").strip().lower()
        if kind not in ("doc", "file", "web"):
            raise HTTPException(status_code=400, detail="invalid kind")

        ref = (payload.content_ref or "").strip()
        title = (payload.title or "").strip()
        pinned = bool(payload.pinned)

        if kind == "doc":
            # Docs are restricted to markdown under the repo root (same rules as /api/v2/docs/file).
            safe = _safe_doc_path(ref)
            if safe is None:
                raise HTTPException(status_code=404, detail="file not found")
            ref = safe.resolve().relative_to(_docs_root()).as_posix()

        if kind == "file":
            # Restrict context refs to existing files within FANFAN_FS_ROOT.
            raw = Path(ref).as_posix().lstrip("/")
            if not raw or ".." in Path(raw).parts:
                raise HTTPException(status_code=400, detail="invalid content_ref")

            fs_root = settings.resolved_fs_root().expanduser().resolve()
            candidate = (fs_root / raw).resolve()

            try:
                ok = candidate.is_relative_to(fs_root)
            except Exception:
                ok = str(candidate).startswith(str(fs_root))

            if not ok or not candidate.is_file():
                raise HTTPException(status_code=404, detail="file not found")

            ref = candidate.relative_to(fs_root).as_posix()

        if kind == "web":
            if not (ref.startswith("http://") or ref.startswith("https://")):
                raise HTTPException(status_code=400, detail="invalid url")

        if not title:
            title = ref

        item = db.upsert_context_item_by_ref(
            session_id=session_id,
            kind=kind,
            title=title,
            content_ref=ref,
            pinned=pinned,
        )
        return item

    # ── FS (File Tree + Versions) ────────────────────────────────

    fs_root = settings.resolved_fs_root().expanduser().resolve()

    _FS_IGNORE_DIRS = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "data",
    }

    def _resolve_fs_path(raw: str) -> Path:
        if not raw:
            raise HTTPException(status_code=400, detail="path is required")

        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = fs_root / p

        try:
            resolved = p.resolve()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid path")

        root = fs_root.resolve()
        if resolved == root or resolved.is_relative_to(root):
            return resolved

        raise HTTPException(status_code=400, detail="path is outside allowed root")

    def _rel_fs_path(p: Path) -> str:
        try:
            return p.resolve().relative_to(fs_root.resolve()).as_posix()
        except Exception:
            return str(p)

    def _walk_fs_tree(max_files: int = 5000) -> tuple[list[dict[str, Any]], bool]:
        items: list[dict[str, Any]] = []
        truncated = False

        for dirpath, dirnames, filenames in os.walk(fs_root):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _FS_IGNORE_DIRS and not d.startswith(".")
            ]

            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                full = Path(dirpath) / fn
                try:
                    rel = _rel_fs_path(full)
                    if not rel or rel.startswith(".."):
                        continue
                    st = full.stat()
                    items.append({"path": rel, "size": int(st.st_size), "mtime": float(st.st_mtime)})
                except Exception:
                    continue

                if len(items) >= max_files:
                    truncated = True
                    break

            if truncated:
                break

        items.sort(key=lambda x: x.get("path") or "")
        return items, truncated

    @app.get("/api/v2/sessions/{session_id}/fs/tree")
    async def fs_tree(session_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        items, truncated = _walk_fs_tree()
        return {"root": ".", "items": items, "truncated": bool(truncated)}

    @app.get("/api/v2/sessions/{session_id}/fs/read")
    async def fs_read(session_id: str, path: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        p = _resolve_fs_path(path)
        if not p.exists() or not p.is_file():
            raise HTTPException(status_code=404, detail="file not found")

        st = p.stat()
        # Avoid loading huge files into memory in the UI.
        max_chars = 200_000
        content = p.read_text(encoding="utf-8", errors="replace")
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated = True

        return {
            "path": _rel_fs_path(p),
            "size": int(st.st_size),
            "mtime": float(st.st_mtime),
            "truncated": bool(truncated),
            "content": content,
        }

    @app.get("/api/v2/sessions/{session_id}/fs/versions")
    async def fs_versions(session_id: str, path: str) -> list[dict[str, Any]]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        p = _resolve_fs_path(path)
        rel = _rel_fs_path(p)
        return db.list_file_versions(session_id, rel, limit=200)

    @app.get("/api/v2/sessions/{session_id}/fs/version/{version_id}")
    async def fs_get_version(session_id: str, version_id: str) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        rec = db.get_file_version(version_id)
        if not rec or str(rec.get("session_id") or "") != session_id:
            raise HTTPException(status_code=404, detail="version not found")

        content = str(rec.get("content") or "")
        max_chars = 200_000
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated = True

        return {
            "id": str(rec.get("id")),
            "session_id": session_id,
            "path": str(rec.get("path")),
            "idx": int(rec.get("idx") or 0),
            "note": str(rec.get("note") or ""),
            "created_at": str(rec.get("created_at") or ""),
            "truncated": bool(truncated),
            "content": content,
        }

    @app.post("/api/v2/sessions/{session_id}/fs/rollback")
    async def fs_rollback(session_id: str, payload: FsRollbackRequest) -> dict[str, Any]:
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")

        target = db.get_file_version(payload.version_id)
        if not target or str(target.get("session_id") or "") != session_id:
            raise HTTPException(status_code=404, detail="version not found")

        p = _resolve_fs_path(payload.path)
        rel = _rel_fs_path(p)
        if str(target.get("path") or "") != rel:
            raise HTTPException(status_code=400, detail="version does not match file path")

        # Read current
        before = p.read_text(encoding="utf-8", errors="replace") if p.exists() and p.is_file() else ""
        after = str(target.get("content") or "")

        if before == after:
            return {"ok": True, "path": rel, "changed": False}

        # Write rollback content
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(after, encoding="utf-8")

        # Record as an internal v2 turn so artifacts remain consistent.
        turn = db.create_turn(session_id, f"[rollback] {rel} -> v{int(target.get('idx') or 0)}")
        s0 = db.create_step(turn["id"], idx=0)
        db.finish_step(s0["id"], status="completed")
        s1 = db.create_step(turn["id"], idx=1)

        diff = "\n".join(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile="a/" + rel,
                tofile="b/" + rel,
                lineterm="",
            )
        ) + "\n"

        db.add_file_change(session_id, turn["id"], s1["id"], rel, diff)
        db.record_file_change_versions(
            session_id=session_id,
            turn_id=turn["id"],
            step_id=s1["id"],
            path=rel,
            before=before,
            after=after,
            note="rollback",
        )

        tool_call_id = f"rollback_{uuid.uuid4().hex[:8]}"
        await bus.publish(
            session_id=session_id,
            turn_id=turn["id"],
            step_id=s1["id"],
            type="tool_call",
            payload={
                "tool_call_id": tool_call_id,
                "tool_name": "fs.rollback",
                "input": {
                    "path": rel,
                    "version_id": payload.version_id,
                    "idx": int(target.get("idx") or 0),
                },
                "status": "running",
            },
        )

        await bus.publish(
            session_id=session_id,
            turn_id=turn["id"],
            step_id=s1["id"],
            type="fs_rollback",
            payload={
                "tool_call_id": tool_call_id,
                "path": rel,
                "version_id": payload.version_id,
                "idx": int(target.get("idx") or 0),
            },
        )
        await bus.publish(
            session_id=session_id,
            turn_id=turn["id"],
            step_id=s1["id"],
            type="diff",
            payload={"tool_call_id": tool_call_id, "path": rel, "diff": diff},
        )
        await bus.publish(
            session_id=session_id,
            turn_id=turn["id"],
            step_id=s1["id"],
            type="tool_result",
            payload={
                "tool_call_id": tool_call_id,
                "tool_name": "fs.rollback",
                "ok": True,
                "output": f"Rolled back {rel} to v{int(target.get('idx') or 0)}",
                "error": "",
                "duration_ms": 0,
            },
        )
        db.finish_step(s1["id"], status="completed")
        db.touch_session(session_id)

        return {"ok": True, "path": rel, "changed": True}

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
            p = dist_dir / "index.html"
            if p.exists():
                return FileResponse(str(p), headers={"Cache-Control": "no-store"})
            raise HTTPException(status_code=404)

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
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
            target = settings.ui_url if settings.ui_mode == "remote" else settings.ui_dev_server_url
            return await _proxy_to(target, request, "")

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
        async def proxy_catchall(full_path: str, request: Request):
            if full_path.startswith("api/") or full_path.startswith("docs") or full_path == "openapi.json":
                raise HTTPException(status_code=404)
            target = settings.ui_url if settings.ui_mode == "remote" else settings.ui_dev_server_url
            return await _proxy_to(target, request, full_path)

    return app
