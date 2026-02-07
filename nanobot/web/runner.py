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

from nanobot.agent.tools.base import Tool
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.agent.tools.opencode import HttpFetchTool, SearchTool
from nanobot.agent.tools.patch import ApplyPatchTool, _extract_files_from_patch
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


class SpawnSubagentTool(Tool):
    def __init__(self, runner: "FanfanWebRunner | None" = None):
        self._runner = runner
        self._ctx: dict[str, str] = {}

    def set_context(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        parent_tool_call_id: str,
    ) -> None:
        self._ctx = {
            "session_id": session_id,
            "turn_id": turn_id,
            "step_id": step_id,
            "parent_tool_call_id": parent_tool_call_id,
        }

    @property
    def name(self) -> str:
        return "spawn_subagent"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to work on a focused task. "
            "The subagent runs as a nested execution tree and returns its final result."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task for the subagent"},
                "label": {"type": "string", "description": "Optional short label for UI"},
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        ctx = self._ctx or {}
        session_id = ctx.get("session_id", "")
        turn_id = ctx.get("turn_id", "")
        step_id = ctx.get("step_id", "")
        parent_tool_call_id = ctx.get("parent_tool_call_id", "")
        if not session_id or not turn_id or not step_id or not parent_tool_call_id:
            return "Error: spawn_subagent missing execution context"

        if self._runner is None:
            return "Error: spawn_subagent tool is not available in this context"

        return await self._runner._run_subagent(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step_id,
            parent_tool_call_id=parent_tool_call_id,
            task=task,
            label=label,
        )


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

        self._brave_api_key = brave_api_key

        self._fs_root = settings.resolved_fs_root().expanduser().resolve()

        self._workspace = repo_root() / "workspace"
        self._context = ContextBuilder(self._workspace)

        self._tools = ToolRegistry()
        self._register_tools(brave_api_key=brave_api_key)

    def _register_tools(self, *, brave_api_key: str | None) -> None:
        # OpenCode-required tool names
        self._tools.register(ReadFileTool(root=self._fs_root))
        self._tools.register(WriteFileTool(root=self._fs_root))
        self._tools.register(ApplyPatchTool(allowed_root=self._fs_root))
        self._tools.register(SearchTool(api_key=brave_api_key))
        self._tools.register(HttpFetchTool())
        self._tools.register(SpawnSubagentTool(self))

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

        # Keep the prompt aligned with the web runner tool set (no shell exec).
        if messages and isinstance(messages[0].get("content"), str):
            messages[0]["content"] += (
                "\n\n## Web Tools\n"
                "Available tools: read_file, write_file, apply_patch, search, http_fetch, spawn_subagent.\n"
                "Unavailable: exec/run_command (shell), message, cron.\n"
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
                        patch_before: dict[str, str] | None = None
                        if tool_name == "apply_patch":
                            patch_before = {}
                            patch_str = str(args.get("patch") or "")
                            if patch_str:
                                for f in _extract_files_from_patch(patch_str):
                                    rel = str(f.get("path") or "")
                                    if not rel:
                                        continue
                                    rp = self._resolve_fs_path(rel)
                                    if rp is None:
                                        continue
                                    patch_before[rel] = _read_file_best_effort(rp)

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

                        tool = self._tools.get(tool_name)
                        params = dict(args)

                        # Ensure apply_patch runs from repo root so git apply works.
                        if tool_name == "apply_patch":
                            params["cwd"] = str(repo_root())

                        if tool is None:
                            tool_output = f"Error: Tool '{tool_name}' not found"
                        else:
                            if hasattr(tool, "set_context"):
                                try:
                                    tool.set_context(
                                        session_id=session_id,
                                        turn_id=turn_id,
                                        step_id=step_id,
                                        parent_tool_call_id=tool_call_id,
                                    )
                                except Exception:
                                    pass

                            try:
                                errors = tool.validate_params(params)
                                if errors:
                                    tool_output = f"Error: Invalid parameters for tool '{tool_name}': " + "; ".join(errors)
                                else:
                                    tool_output = await tool.execute(**params)
                            except Exception as e:
                                tool_output = f"Error executing {tool_name}: {str(e)}"

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
                                self._db.record_file_change_versions(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    path=display_path,
                                    before=before_text,
                                    after=after_text,
                                    note="write_file",
                                )
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
                                            before = patch_before.get(path) if patch_before else None
                                            rp = self._resolve_fs_path(path)
                                            after = _read_file_best_effort(rp) if rp is not None else ""
                                            self._db.record_file_change_versions(
                                                session_id=session_id,
                                                turn_id=turn_id,
                                                step_id=step_id,
                                                path=path,
                                                before=before,
                                                after=after,
                                                note="apply_patch",
                                            )
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



    async def _publish_subagent_status(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        parent_tool_call_id: str,
        subagent_id: str,
        status: str,
        label: str,
        task: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        await self._bus.publish(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step_id,
            type="subagent",
            payload={
                "parent_tool_call_id": parent_tool_call_id,
                "subagent_id": subagent_id,
                "status": status,
                "label": label,
                "task": task,
                "result": result or "",
                "error": error or "",
            },
        )

    async def _publish_subagent_block(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        parent_tool_call_id: str,
        subagent_id: str,
        block: dict[str, Any],
    ) -> None:
        b = dict(block)
        b.setdefault("ts", time.time())
        await self._bus.publish(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step_id,
            type="subagent_block",
            payload={
                "parent_tool_call_id": parent_tool_call_id,
                "subagent_id": subagent_id,
                "block": b,
            },
        )

    async def _run_subagent(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        parent_tool_call_id: str,
        task: str,
        label: str | None = None,
    ) -> str:
        subagent_id = f"sub_{uuid.uuid4().hex[:8]}"
        display_label = (label or "").strip() or task.strip()[:40] + ("..." if len(task.strip()) > 40 else "")

        await self._publish_subagent_status(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step_id,
            parent_tool_call_id=parent_tool_call_id,
            subagent_id=subagent_id,
            status="start",
            label=display_label,
            task=task,
        )

        tools = ToolRegistry()
        tools.register(ReadFileTool(root=self._fs_root))
        tools.register(WriteFileTool(root=self._fs_root))
        tools.register(ApplyPatchTool(allowed_root=self._fs_root))
        tools.register(SearchTool(api_key=self._brave_api_key))
        tools.register(HttpFetchTool())

        sys = self._context.build_system_prompt()
        sys += (
            "\n\n# Subagent\n"
            "You are a subagent running inside a parent tool call.\n\n"
            "Rules:\n"
            "- Stay focused on the given task.\n"
            "- Return a clear final answer.\n"
            "- You may use tools if needed; file writes and patches may require approval.\n\n"
            "Web tools available: read_file, write_file, apply_patch, search, http_fetch.\n"
            "Shell execution is not available.\n"
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": sys},
            {"role": "user", "content": task},
        ]

        final_text: str = ""

        try:
            max_iterations = 12
            for _iter in range(1, max_iterations + 1):
                resp = await self._provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self._model,
                )

                if resp.thinking:
                    await self._publish_subagent_block(
                        session_id=session_id,
                        turn_id=turn_id,
                        step_id=step_id,
                        parent_tool_call_id=parent_tool_call_id,
                        subagent_id=subagent_id,
                        block={
                            "id": f"thinking_{subagent_id}_{_iter}",
                            "type": "thinking",
                            "text": resp.thinking,
                            "duration_ms": 0,
                        },
                    )

                if resp.has_tool_calls:
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                        }
                        for tc in resp.tool_calls
                    ]
                    messages = self._context.add_assistant_message(messages, resp.content or "", tool_call_dicts)

                    for tc in resp.tool_calls:
                        tool_name = tc.name
                        tool_call_id = tc.id or f"stc_{uuid.uuid4().hex[:8]}"
                        args = tc.arguments or {}

                        # Tool disabled?
                        if not self._settings.tool_enabled(tool_name):
                            err = f"Tool '{tool_name}' is disabled by configuration"
                            await self._publish_subagent_block(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                parent_tool_call_id=parent_tool_call_id,
                                subagent_id=subagent_id,
                                block={
                                    "id": tool_call_id,
                                    "type": "tool_call",
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_name,
                                    "status": "error",
                                    "input": args,
                                    "output": "",
                                    "error": err,
                                    "duration_ms": 0,
                                },
                            )
                            messages = self._context.add_tool_result(messages, tool_call_id, tool_name, err)
                            continue

                        policy = self._permissions.effective_policy(session_id=session_id, tool_name=tool_name)

                        if policy == "deny":
                            err = f"Permission denied for tool '{tool_name}'"
                            await self._publish_subagent_block(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                parent_tool_call_id=parent_tool_call_id,
                                subagent_id=subagent_id,
                                block={
                                    "id": tool_call_id,
                                    "type": "tool_call",
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_name,
                                    "status": "error",
                                    "input": args,
                                    "output": "",
                                    "error": err,
                                    "duration_ms": 0,
                                },
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
                            await self._publish_subagent_block(
                                session_id=session_id,
                                turn_id=turn_id,
                                step_id=step_id,
                                parent_tool_call_id=parent_tool_call_id,
                                subagent_id=subagent_id,
                                block={
                                    "id": tool_call_id,
                                    "type": "tool_call",
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_name,
                                    "status": "permission_required",
                                    "input": args,
                                    "permission_request_id": request_id,
                                },
                            )
                            decision = await self._permissions.wait(request_id=request_id)
                            if not decision.approved:
                                err = f"Permission denied for tool '{tool_name}'"
                                await self._publish_subagent_block(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    parent_tool_call_id=parent_tool_call_id,
                                    subagent_id=subagent_id,
                                    block={
                                        "id": tool_call_id,
                                        "type": "tool_call",
                                        "tool_call_id": tool_call_id,
                                        "tool_name": tool_name,
                                        "status": "error",
                                        "input": args,
                                        "output": "",
                                        "error": err,
                                        "duration_ms": 0,
                                    },
                                )
                                messages = self._context.add_tool_result(messages, tool_call_id, tool_name, err)
                                continue

                        await self._publish_subagent_block(
                            session_id=session_id,
                            turn_id=turn_id,
                            step_id=step_id,
                            parent_tool_call_id=parent_tool_call_id,
                            subagent_id=subagent_id,
                            block={
                                "id": tool_call_id,
                                "type": "tool_call",
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "status": "running",
                                "input": args,
                            },
                        )

                        start_t = time.time()
                        patch_before: dict[str, str] | None = None
                        if tool_name == "apply_patch":
                            patch_before = {}
                            patch_str = str(args.get("patch") or "")
                            if patch_str:
                                for f in _extract_files_from_patch(patch_str):
                                    rel = str(f.get("path") or "")
                                    if not rel:
                                        continue
                                    rp = self._resolve_fs_path(rel)
                                    if rp is None:
                                        continue
                                    patch_before[rel] = _read_file_best_effort(rp)

                        before_text: str | None = None
                        target_path: Path | None = None
                        target_display_path: str | None = None
                        if tool_name == "write_file":
                            raw = str(args.get("path") or "")
                            if raw:
                                target_path = self._resolve_fs_path(raw)
                                if target_path is not None:
                                    target_display_path = self._display_fs_path(target_path)
                                    before_text = _read_file_best_effort(target_path)

                        tool = tools.get(tool_name)
                        params = dict(args)
                        if tool_name == "apply_patch":
                            params["cwd"] = str(repo_root())

                        if tool is None:
                            tool_output = f"Error: Tool '{tool_name}' not found"
                        else:
                            errors = tool.validate_params(params)
                            if errors:
                                tool_output = f"Error: Invalid parameters for tool '{tool_name}': " + "; ".join(errors)
                            else:
                                tool_output = await tool.execute(**params)

                        duration_ms = int((time.time() - start_t) * 1000)
                        ok, parsed_err = _tool_ok_and_error(tool_name, tool_output)
                        tool_error = parsed_err if not ok else ""

                        await self._publish_subagent_block(
                            session_id=session_id,
                            turn_id=turn_id,
                            step_id=step_id,
                            parent_tool_call_id=parent_tool_call_id,
                            subagent_id=subagent_id,
                            block={
                                "id": tool_call_id,
                                "type": "tool_call",
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "status": "completed" if ok else "error",
                                "input": args,
                                "output": (tool_output[:2000] + ("..." if len(tool_output) > 2000 else "")) if ok else "",
                                "error": (tool_error[:2000] + ("..." if len(tool_error) > 2000 else "")) if tool_error else "",
                                "duration_ms": duration_ms,
                            },
                        )

                        if ok and tool_name == "write_file" and target_path is not None and before_text is not None:
                            after_text = _read_file_best_effort(target_path)
                            if before_text != after_text:
                                display_path = target_display_path or self._display_fs_path(target_path)
                                diff = _unified_diff(display_path, before_text, after_text)
                                self._db.add_file_change(session_id, turn_id, step_id, display_path, diff)
                                self._db.record_file_change_versions(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    path=display_path,
                                    before=before_text,
                                    after=after_text,
                                    note="write_file",
                                )
                                await self._publish_subagent_block(
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    step_id=step_id,
                                    parent_tool_call_id=parent_tool_call_id,
                                    subagent_id=subagent_id,
                                    block={
                                        "id": f"diff_{tool_call_id}_{uuid.uuid4().hex[:6]}",
                                        "type": "diff",
                                        "tool_call_id": tool_call_id,
                                        "path": display_path,
                                        "diff": diff,
                                    },
                                )

                        if ok and tool_name == "apply_patch":
                            try:
                                data = json.loads(tool_output)
                                if data.get("applied") and isinstance(data.get("files"), list):
                                    for f in data["files"]:
                                        path = str(f.get("path") or "")
                                        diff = str(f.get("diff") or "")
                                        if path and diff:
                                            self._db.add_file_change(session_id, turn_id, step_id, path, diff)
                                            before = patch_before.get(path) if patch_before else None
                                            rp = self._resolve_fs_path(path)
                                            after = _read_file_best_effort(rp) if rp is not None else ""
                                            self._db.record_file_change_versions(
                                                session_id=session_id,
                                                turn_id=turn_id,
                                                step_id=step_id,
                                                path=path,
                                                before=before,
                                                after=after,
                                                note="apply_patch",
                                            )
                                            await self._publish_subagent_block(
                                                session_id=session_id,
                                                turn_id=turn_id,
                                                step_id=step_id,
                                                parent_tool_call_id=parent_tool_call_id,
                                                subagent_id=subagent_id,
                                                block={
                                                    "id": f"diff_{tool_call_id}_{uuid.uuid4().hex[:6]}",
                                                    "type": "diff",
                                                    "tool_call_id": tool_call_id,
                                                    "path": path,
                                                    "diff": diff,
                                                },
                                            )
                            except Exception:
                                pass

                        messages = self._context.add_tool_result(messages, tool_call_id, tool_name, tool_output)

                    continue

                final_text = (resp.content or "").strip()
                if final_text:
                    await self._publish_subagent_block(
                        session_id=session_id,
                        turn_id=turn_id,
                        step_id=step_id,
                        parent_tool_call_id=parent_tool_call_id,
                        subagent_id=subagent_id,
                        block={
                            "id": f"assistant_{subagent_id}",
                            "type": "assistant",
                            "text": final_text,
                        },
                    )
                break

            if not final_text:
                final_text = "(no response)"

            await self._publish_subagent_status(
                session_id=session_id,
                turn_id=turn_id,
                step_id=step_id,
                parent_tool_call_id=parent_tool_call_id,
                subagent_id=subagent_id,
                status="end",
                label=display_label,
                task=task,
                result=final_text,
            )
            return final_text

        except Exception as e:
            err = str(e)
            await self._publish_subagent_block(
                session_id=session_id,
                turn_id=turn_id,
                step_id=step_id,
                parent_tool_call_id=parent_tool_call_id,
                subagent_id=subagent_id,
                block={
                    "id": f"error_{subagent_id}",
                    "type": "error",
                    "text": err,
                    "code": "SUBAGENT_ERROR",
                },
            )
            await self._publish_subagent_status(
                session_id=session_id,
                turn_id=turn_id,
                step_id=step_id,
                parent_tool_call_id=parent_tool_call_id,
                subagent_id=subagent_id,
                status="error",
                label=display_label,
                task=task,
                error=err,
            )
            return f"Error: {err}"
