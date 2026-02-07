"""fanfan web runner (v2).

This runner implements an OpenCode-style agent loop:
- stream assistant deltas as SSE events
- execute tool calls with permission gating
- emit tool_result / diff / terminal_chunk events
- persist all events for replay
"""

from __future__ import annotations

import difflib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.agent.tools.opencode import HttpFetchTool, RunCommandTool, SearchTool
from nanobot.agent.tools.patch import ApplyPatchTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider, ToolCallRequest
from nanobot.web.database import Database
from nanobot.web.event_bus import EventBus
from nanobot.web.permissions import PermissionManager
from nanobot.web.settings import WebSettings, repo_root


def _unified_diff(path: str, before: str, after: str) -> str:
    p = Path(path)
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{p.as_posix()}",
        tofile=f"b/{p.as_posix()}",
        lineterm="",
    )
    return "\n".join(lines) + "\n"


def _read_file_best_effort(path: str | Path) -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists() or not p.is_file():
            return ""
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _looks_like_tool_error(text: str) -> bool:
    s = (text or "").lstrip()
    return s.startswith("Error:") or s.startswith("Error ")


def _tool_ok_and_error(tool_name: str, tool_output: str) -> tuple[bool, str]:
    """Best-effort ok/error detection for tool outputs.

    Some tools (e.g. http_fetch/apply_patch) return JSON even on failure, so
    string-prefix checks are not sufficient.
    """

    if tool_name == "http_fetch":
        try:
            data = json.loads(tool_output)
            if isinstance(data, dict) and data.get("error"):
                return False, str(data.get("error"))
        except Exception:
            pass

    if tool_name == "apply_patch":
        try:
            data = json.loads(tool_output)
            if isinstance(data, dict) and not bool(data.get("applied")):
                err = (
                    data.get("error")
                    or data.get("stderr")
                    or data.get("stdout")
                    or "Patch not applied"
                )
                return False, str(err)
        except Exception:
            pass

    if _looks_like_tool_error(tool_output):
        return False, tool_output
    return True, ""


class FanfanWebRunner:
    def __init__(
        self,
        *,
        db: Database,
        bus: EventBus,
        permissions: PermissionManager,
        provider: LLMProvider,
        settings: WebSettings,
        model: str,
        max_iterations: int,
        brave_api_key: str | None = None,
    ):
        self._db = db
        self._bus = bus
        self._permissions = permissions
        self._provider = provider
        self._settings = settings
        self._model = model
        self._max_iterations = max_iterations

        self._fs_root = settings.resolved_fs_root().expanduser().resolve()

        self._workspace = repo_root() / "workspace"
        self._context = ContextBuilder(self._workspace)

        self._tools = ToolRegistry()
        self._register_tools(brave_api_key=brave_api_key)

    def _register_tools(self, *, brave_api_key: str | None) -> None:
        # OpenCode-required tool names
        self._tools.register(RunCommandTool(working_dir=str(repo_root())))
        self._tools.register(ReadFileTool(root=self._fs_root))
        self._tools.register(WriteFileTool(root=self._fs_root))
        self._tools.register(ApplyPatchTool(allowed_root=self._fs_root))
        self._tools.register(SearchTool(api_key=brave_api_key))
        self._tools.register(HttpFetchTool())

    def _resolve_fs_path(self, raw_path: str) -> Path | None:
        try:
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = self._fs_root / p
            resolved = p.resolve()
            root = self._fs_root.resolve()
            if resolved == root or resolved.is_relative_to(root):
                return resolved
            return None
        except Exception:
            return None

    def _display_fs_path(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self._fs_root.resolve()).as_posix()
        except Exception:
            return str(p)

    async def run_turn(self, *, session_id: str, turn_id: str, user_text: str) -> str:
        """Run a single user turn (async task). Returns final assistant text."""
        # Step 0: persist and emit user message
        step0 = self._db.create_step(turn_id, idx=0)
        user_message_id = f"msg_{uuid.uuid4().hex[:12]}"
        await self._bus.publish(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step0["id"],
            type="message_delta",
            payload={"role": "user", "message_id": user_message_id, "delta": user_text},
        )
        self._db.finish_step(step0["id"], status="completed")

        # Build LLM messages from DB history to keep one canonical store.
        history_rows = self._db.get_messages(session_id)
        history: list[dict[str, Any]] = [{"role": r["role"], "content": r["content"]} for r in history_rows[-50:]]
        messages = self._context.build_messages(
            history=history,
            current_message=user_text,
            channel="web",
            chat_id=session_id,
        )

        final_text: str = ""
        total_usage: dict[str, int] = {}

        for iteration in range(1, self._max_iterations + 1):
            step = self._db.create_step(turn_id, idx=iteration)
            step_id = step["id"]
            assistant_message_id = f"msg_{uuid.uuid4().hex[:12]}"

            try:
                content_parts: list[str] = []
                tool_calls: list[ToolCallRequest] = []
                finish_reason = "stop"
                usage: dict[str, int] = {}

                thinking_started = False
                thinking_start_t = 0.0
                thinking_buf: list[str] = []

                async for chunk in self._provider.chat_stream(
                    messages=messages,
                    tools=self._tools.get_definitions(),
                    model=self._model,
                ):
                    if chunk.delta:
                        content_parts.append(chunk.delta)
                        await self._bus.publish(
                            session_id=session_id,
                            turn_id=turn_id,
                            step_id=step_id,
                            type="message_delta",
                            payload={
                                "role": "assistant",
                                "message_id": assistant_message_id,
                                "delta": chunk.delta,
                            },
                        )

                    if chunk.thinking_delta:
                        if not thinking_started:
                            thinking_started = True
                            thinking_start_t = time.time()
                            await self._bus.publish(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                type="thinking",
                                payload={"status": "start"},
                            )
                        thinking_buf.append(chunk.thinking_delta)
                        await self._bus.publish(
                            session_id=session_id,
                            turn_id=turn_id,
                            step_id=step_id,
                            type="thinking",
                            payload={"status": "delta", "text": chunk.thinking_delta},
                        )

                    if chunk.tool_calls_delta:
                        for tc_data in chunk.tool_calls_delta:
                            fn = tc_data.get("function", {}) if isinstance(tc_data, dict) else {}
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    args = {"raw": args}
                            tool_calls.append(
                                ToolCallRequest(
                                    id=tc_data.get("id") or f"tc_{uuid.uuid4().hex[:8]}",
                                    name=fn.get("name") or "unknown",
                                    arguments=args if isinstance(args, dict) else {"raw": args},
                                )
                            )

                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    if chunk.usage:
                        usage = chunk.usage

                if thinking_started:
                    duration_ms = int((time.time() - thinking_start_t) * 1000)
                    await self._bus.publish(
                        session_id=session_id,
                        turn_id=turn_id,
                        step_id=step_id,
                        type="thinking",
                        payload={"status": "end", "duration_ms": duration_ms},
                    )

                # Merge usage
                for k, v in (usage or {}).items():
                    try:
                        total_usage[k] = total_usage.get(k, 0) + int(v)
                    except Exception:
                        continue

                content = "".join(content_parts).strip()

                if tool_calls:
                    # Add assistant tool-call message to context
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                        }
                        for tc in tool_calls
                    ]
                    messages = self._context.add_assistant_message(messages, content, tool_call_dicts)

                    # Execute tool calls sequentially
                    for tc in tool_calls:
                        tool_name = tc.name
                        tool_call_id = tc.id
                        args = tc.arguments or {}

                        # Tool disabled?
                        if not self._settings.tool_enabled(tool_name):
                            err = f"Tool '{tool_name}' is disabled by configuration"
                            await self._emit_tool_result(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                ok=False,
                                output="",
                                error=err,
                                duration_ms=0,
                            )
                            messages = self._context.add_tool_result(messages, tool_call_id, tool_name, err)
                            continue

                        policy = self._permissions.effective_policy(session_id=session_id, tool_name=tool_name)

                        if policy == "deny":
                            err = f"Permission denied for tool '{tool_name}'"
                            await self._emit_tool_result(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                ok=False,
                                output="",
                                error=err,
                                duration_ms=0,
                            )
                            messages = self._context.add_tool_result(messages, tool_call_id, tool_name, err)
                            continue

                        if policy == "ask":
                            request_id = await self._permissions.create_request(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                tool_name=tool_name,
                                input_data=args,
                            )
                            await self._bus.publish(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                type="tool_call",
                                payload={
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_name,
                                    "input": args,
                                    "status": "permission_required",
                                    "permission_request_id": request_id,
                                    "choices": ["once", "session", "always", "deny"],
                                },
                            )
                            decision = await self._permissions.wait(request_id=request_id)
                            if not decision.approved:
                                err = f"Permission denied for tool '{tool_name}'"
                                await self._emit_tool_result(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name,
                                    ok=False,
                                    output="",
                                    error=err,
                                    duration_ms=0,
                                )
                                messages = self._context.add_tool_result(messages, tool_call_id, tool_name, err)
                                continue

                        # Allowed: emit tool_call running
                        await self._bus.publish(
                            session_id=session_id,
                            turn_id=turn_id,
                            step_id=step_id,
                            type="tool_call",
                            payload={
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "input": args,
                                "status": "running",
                            },
                        )

                        start_t = time.time()
                        tool_output = ""
                        tool_error = ""
                        ok = True

                        # File snapshot for diff (write_file only; apply_patch emits per-file diffs itself)
                        before_text: str | None = None
                        target_raw_path: str | None = None
                        target_path: Path | None = None
                        target_display_path: str | None = None
                        if tool_name == "write_file":
                            target_raw_path = str(args.get("path") or "")
                            if target_raw_path:
                                target_path = self._resolve_fs_path(target_raw_path)
                                if target_path is not None:
                                    target_display_path = self._display_fs_path(target_path)
                                    before_text = _read_file_best_effort(target_path)

                        # Terminal streaming for run_command
                        if tool_name == "run_command":
                            async def _term_cb(stream: str, text: str) -> None:
                                ts = time.time()
                                self._db.add_terminal_chunk(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    tool_call_id=tool_call_id,
                                    stream=stream,
                                    text=text,
                                    ts=ts,
                                )
                                await self._bus.publish(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    type="terminal_chunk",
                                    payload={"tool_call_id": tool_call_id, "stream": stream, "text": text},
                                    ts=ts,
                                )

                            tool_output = await self._tools.execute(tool_name, {**args, "_stream_cb": _term_cb})
                        else:
                            # Ensure apply_patch runs from repo root so git apply works.
                            if tool_name == "apply_patch":
                                tool_output = await self._tools.execute(tool_name, {**args, "cwd": str(repo_root())})
                            else:
                                tool_output = await self._tools.execute(tool_name, args)

                        duration_ms = int((time.time() - start_t) * 1000)

                        # Determine ok/error. Some tools return JSON even on failure.
                        ok, parsed_err = _tool_ok_and_error(tool_name, tool_output)
                        if not ok:
                            tool_error = parsed_err

                        # Emit tool_result
                        await self._emit_tool_result(
                            session_id=session_id,
                            turn_id=turn_id,
                            step_id=step_id,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            ok=ok,
                            output=tool_output if ok else "",
                            error=tool_error if not ok else "",
                            duration_ms=duration_ms,
                        )

                        # Emit diff + persist file change
                        if ok and tool_name == "write_file" and target_path is not None and before_text is not None:
                            after_text = _read_file_best_effort(target_path)
                            if before_text != after_text:
                                display_path = target_display_path or self._display_fs_path(target_path)
                                diff = _unified_diff(display_path, before_text, after_text)
                                self._db.add_file_change(session_id, turn_id, step_id, display_path, diff)
                                await self._bus.publish(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    type="diff",
                                    payload={"tool_call_id": tool_call_id, "path": display_path, "diff": diff},
                                )

                        if ok and tool_name == "apply_patch":
                            # apply_patch returns JSON describing files + diffs
                            try:
                                data = json.loads(tool_output)
                                if data.get("applied") and isinstance(data.get("files"), list):
                                    for f in data["files"]:
                                        path = str(f.get("path") or "")
                                        diff = str(f.get("diff") or "")
                                        if path and diff:
                                            self._db.add_file_change(session_id, turn_id, step_id, path, diff)
                                            await self._bus.publish(
                                                session_id=session_id,
                                                turn_id=turn_id,
                                                step_id=step_id,
                                                type="diff",
                                                payload={"tool_call_id": tool_call_id, "path": path, "diff": diff},
                                            )
                            except Exception:
                                pass

                        # Opportunistic context items (MVP): successful read_file/http_fetch get remembered
                        if ok and tool_name == "read_file":
                            raw = str(args.get("path") or "")
                            if raw:
                                rp = self._resolve_fs_path(raw)
                                display = self._display_fs_path(rp) if rp is not None else raw
                                self._db.add_context_item(
                                    session_id, kind="file", title=display, content_ref=display, pinned=False
                                )
                        if ok and tool_name == "http_fetch":
                            try:
                                data = json.loads(tool_output)
                                url = str(data.get("url") or "")
                                if url:
                                    self._db.add_context_item(session_id, kind="web", title=url, content_ref=url, pinned=False)
                            except Exception:
                                pass

                        messages = self._context.add_tool_result(messages, tool_call_id, tool_name, tool_output)

                    self._db.finish_step(step_id, status="completed")
                    continue

                # No tools -> final
                final_text = content
                await self._bus.publish(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_id=step_id,
                    type="final",
                    payload={
                        "role": "assistant",
                        "message_id": assistant_message_id,
                        "text": final_text,
                        "finish_reason": finish_reason,
                        "usage": total_usage or usage or {},
                    },
                )
                self._db.finish_step(step_id, status="completed")
                break

            except Exception as e:
                logger.exception("web runner failed")
                await self._bus.publish(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_id=step_id,
                    type="error",
                    payload={"code": "WEB_RUN_ERROR", "message": str(e)},
                )
                self._db.finish_step(step_id, status="error")
                break

        if not final_text:
            final_text = "(no response)"
        return final_text

    async def _emit_tool_result(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        tool_call_id: str,
        tool_name: str,
        ok: bool,
        output: str,
        error: str,
        duration_ms: int,
    ) -> None:
        await self._bus.publish(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step_id,
            type="tool_result",
            payload={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "ok": bool(ok),
                "output": output[:2000] + ("..." if len(output) > 2000 else "") if output else "",
                "error": error[:2000] + ("..." if len(error) > 2000 else "") if error else "",
                "duration_ms": int(duration_ms),
            },
        )

