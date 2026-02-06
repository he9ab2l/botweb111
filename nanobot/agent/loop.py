"""Agent loop: the core processing engine with full streaming event support."""

from __future__ import annotations

import asyncio
import difflib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk, ToolCallRequest
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager
from nanobot.web.protocol import (
    StreamEvent,
    new_run_id,
    new_block_id,
    evt_status,
    evt_content_block_start,
    evt_content_block_delta,
    evt_content_block_stop,
    evt_thinking,
    evt_tool_use,
    evt_tool_result,
    evt_tool_error,
    evt_patch,
    evt_message_delta,
    evt_final_done,
    evt_error,
    BlockType,
    ToolStatus,
)

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig
    from nanobot.cron.service import CronService


# ── File content cache for diff generation ───────────────────────

_file_snapshots: dict[str, str] = {}


def _snapshot_file(path: str) -> None:
    """Take a snapshot of a file's content before modification."""
    try:
        p = Path(path).expanduser()
        if p.exists() and p.is_file():
            _file_snapshots[str(p)] = p.read_text(encoding="utf-8", errors="replace")
        else:
            _file_snapshots[str(p)] = ""
    except Exception:
        _file_snapshots[str(Path(path).expanduser())] = ""


def _generate_diff(path: str) -> str | None:
    """Generate a unified diff between snapshot and current file content."""
    try:
        p = Path(path).expanduser()
        old = _file_snapshots.pop(str(p), "")
        new = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        if old == new:
            return None
        diff_lines = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{p.name}",
            tofile=f"b/{p.name}",
            lineterm="",
        )
        return "\n".join(diff_lines)
    except Exception:
        return None


# Tools that modify files and should generate patches
_PATCH_TOOLS = {"write_file", "edit_file"}


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM (with true streaming)
    4. Executes tool calls (emitting status events)
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        stream_final_events: bool = True,
        final_event_chunk_size: int = 160,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self._event_callback = event_callback
        self._stream_final_events = stream_final_events
        self._final_event_chunk_size = final_event_chunk_size
        
        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )
        
        self._running = False
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._register_default_tools()

    # ── Event emission ────────────────────────────────────────────

    async def _emit(self, event: StreamEvent, session_id: str = "") -> None:
        """Emit a StreamEvent through the callback (for web channel)."""
        if not self._event_callback:
            return
        d = event.to_dict()
        d["id"] = event.id
        d["session_id"] = session_id
        await self._event_callback(d)

    # Legacy helpers (kept for backward compat with non-streaming paths)
    def _build_event(
        self,
        session_id: str,
        event_type: str,
        status: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": f"evt_{uuid.uuid4().hex}",
            "session_id": session_id,
            "type": event_type,
            "status": status,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _emit_event(
        self,
        session_id: str,
        event_type: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        if not self._event_callback:
            return
        event = self._build_event(session_id, event_type, status, payload)
        await self._event_callback(event)

    # ── Tool registration ─────────────────────────────────────────
    
    def _register_default_tools(self) -> None:
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(EditFileTool())
        self.tools.register(ListDirTool())
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
    
    # ── Main loop ─────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    if msg.channel == "web":
                        await self._emit_event(
                            msg.chat_id, "error", "error",
                            {"code": "AGENT_RUNTIME_ERROR", "message": str(e)},
                        )
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        self._running = False
        logger.info("Agent loop stopping")

    def cancel_run(self, session_id: str) -> bool:
        """Cancel an active run for a session. Returns True if cancelled."""
        task = self._active_tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    # ── Message processing (streaming) ────────────────────────────
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")

        is_web = msg.channel == "web"
        run_id = new_run_id()

        if is_web:
            # Emit user message event
            await self._emit(
                evt_status(run_id, "started", msg.chat_id), msg.chat_id
            )
            await self._emit_event(
                msg.chat_id, "user", "done",
                {"text": msg.content, "sender_id": msg.sender_id},
            )
        
        session = self.sessions.get_or_create(msg.session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)
        
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )
        
        # Agent loop with streaming
        iteration = 0
        final_content = None
        total_usage: dict[str, int] = {}
        
        while iteration < self.max_iterations:
            iteration += 1
            step = iteration

            if is_web:
                # Try streaming path
                result = await self._streaming_llm_call(
                    messages, run_id, step, msg.chat_id
                )
            else:
                # Non-web channels: use non-streaming for simplicity
                result = await self._nonstreaming_llm_call(messages)

            if result is None:
                # Error already emitted
                final_content = "I encountered an error processing your request."
                break

            content, tool_calls, finish_reason, usage, thinking = result

            # Merge usage
            if usage:
                for k, v in usage.items():
                    total_usage[k] = total_usage.get(k, 0) + v

            if tool_calls:
                # Add assistant message with tool calls to context
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, content, tool_call_dicts
                )

                # Emit plan thinking if provider didn't produce reasoning_content
                if is_web and not thinking:
                    tool_names = [tc.name for tc in tool_calls]
                    plan_text = f"Planning to use: {', '.join(tool_names)}"
                    if content:
                        plan_text = content[:200]
                    plan_start = time.time()
                    await self._emit(
                        evt_thinking(run_id, "start", plan_text, step=step),
                        msg.chat_id,
                    )
                    await self._emit(
                        evt_thinking(run_id, "end", duration_ms=50, step=step),
                        msg.chat_id,
                    )
                
                # Execute tools with event emission
                for tc in tool_calls:
                    tool_result = await self._execute_tool_with_events(
                        tc, run_id, step, msg.chat_id, is_web
                    )
                    messages = self.context.add_tool_result(
                        messages, tc.id, tc.name, tool_result
                    )
            else:
                final_content = content
                break
        
        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        # Emit final done
        if is_web:
            await self._emit(
                evt_message_delta(run_id, "end_turn", total_usage or None, step=iteration),
                msg.chat_id,
            )
            await self._emit(
                evt_final_done(run_id, msg.chat_id, step=iteration),
                msg.chat_id,
            )

        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )

    async def _streaming_llm_call(
        self,
        messages: list[dict[str, Any]],
        run_id: str,
        step: int,
        session_id: str,
    ) -> tuple[str | None, list[ToolCallRequest], str, dict[str, int], str | None] | None:
        """
        Call the LLM with streaming, emitting content_block events.

        Returns (content, tool_calls, finish_reason, usage, thinking) or None on error.
        """
        try:
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[ToolCallRequest] = []
            finish_reason = "stop"
            usage: dict[str, int] = {}

            text_block_id: str | None = None
            thinking_block_id: str | None = None
            thinking_start_time: float | None = None

            async for chunk in self.provider.chat_stream(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
            ):
                # Text content delta
                if chunk.delta:
                    if text_block_id is None:
                        text_block_id = new_block_id()
                        await self._emit(
                            evt_content_block_start(run_id, text_block_id, BlockType.TEXT, step),
                            session_id,
                        )
                    content_parts.append(chunk.delta)
                    await self._emit(
                        evt_content_block_delta(run_id, text_block_id, chunk.delta, step),
                        session_id,
                    )

                # Thinking delta
                if chunk.thinking_delta:
                    if thinking_block_id is None:
                        thinking_block_id = new_block_id()
                        thinking_start_time = time.time()
                        await self._emit(
                            evt_thinking(run_id, "start", chunk.thinking_delta, step=step),
                            session_id,
                        )
                    thinking_parts.append(chunk.thinking_delta)

                # Tool calls (arrive as complete list on final chunk)
                if chunk.tool_calls_delta:
                    for tc_data in chunk.tool_calls_delta:
                        fn = tc_data.get("function", {})
                        args = fn.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {"raw": args}
                        tool_calls.append(ToolCallRequest(
                            id=tc_data.get("id", f"tc_{uuid.uuid4().hex[:8]}"),
                            name=fn.get("name", "unknown"),
                            arguments=args,
                        ))

                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                if chunk.usage:
                    usage = chunk.usage

            # Close open blocks
            if text_block_id:
                await self._emit(
                    evt_content_block_stop(run_id, text_block_id, step),
                    session_id,
                )
            if thinking_block_id:
                duration = int((time.time() - (thinking_start_time or time.time())) * 1000)
                await self._emit(
                    evt_thinking(run_id, "end", duration_ms=duration, step=step),
                    session_id,
                )

            content = "".join(content_parts) if content_parts else None
            thinking = "".join(thinking_parts) if thinking_parts else None

            return (content, tool_calls, finish_reason, usage, thinking)

        except Exception as e:
            logger.error(f"Streaming LLM call failed: {e}")
            await self._emit(
                evt_error(run_id, "LLM_STREAM_ERROR", str(e), step=step),
                session_id,
            )
            # Fallback to non-streaming
            result = await self._nonstreaming_llm_call(messages)
            if result and result[0]:
                # Emit the non-streamed content as a single block
                block_id = new_block_id()
                await self._emit(
                    evt_content_block_start(run_id, block_id, BlockType.TEXT, step),
                    session_id,
                )
                await self._emit(
                    evt_content_block_delta(run_id, block_id, result[0], step),
                    session_id,
                )
                await self._emit(
                    evt_content_block_stop(run_id, block_id, step),
                    session_id,
                )
            return result

    async def _nonstreaming_llm_call(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[str | None, list[ToolCallRequest], str, dict[str, int], str | None] | None:
        """Non-streaming LLM call. Returns same tuple as streaming version."""
        try:
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
            )
            return (
                response.content,
                response.tool_calls,
                response.finish_reason,
                response.usage,
                getattr(response, "thinking", None),
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    async def _execute_tool_with_events(
        self,
        tool_call: ToolCallRequest,
        run_id: str,
        step: int,
        session_id: str,
        emit_events: bool = True,
    ) -> str:
        """Execute a tool and emit tool_use/tool_result/tool_error/patch events."""
        tool_name = tool_call.name
        args = tool_call.arguments
        tc_id = tool_call.id

        # Truncate args for display (avoid huge payloads in events)
        display_args = {}
        for k, v in args.items():
            sv = str(v)
            display_args[k] = sv[:500] + "..." if len(sv) > 500 else sv

        # Emit tool_use (running)
        if emit_events:
            await self._emit(
                evt_tool_use(run_id, tc_id, tool_name, display_args, ToolStatus.RUNNING, step),
                session_id,
            )

        # Snapshot file before modification (for patch generation)
        file_path: str | None = None
        if tool_name in _PATCH_TOOLS:
            file_path = args.get("path", "")
            if file_path:
                _snapshot_file(file_path)

        start_time = time.time()
        try:
            result = await self.tools.execute(tool_name, args)
            duration_ms = int((time.time() - start_time) * 1000)

            is_error = result.startswith("Error")

            if emit_events:
                if is_error:
                    await self._emit(
                        evt_tool_error(run_id, tc_id, tool_name, result, duration_ms, step),
                        session_id,
                    )
                else:
                    # Truncate output for event (keep full for LLM context)
                    display_output = result[:2000] + "..." if len(result) > 2000 else result
                    await self._emit(
                        evt_tool_result(run_id, tc_id, tool_name, display_output, duration_ms, step),
                        session_id,
                    )

                    # Generate and emit patch for file-modifying tools
                    if file_path and tool_name in _PATCH_TOOLS and not is_error:
                        diff = _generate_diff(file_path)
                        if diff:
                            await self._emit(
                                evt_patch(run_id, tc_id, [
                                    {"path": file_path, "action": tool_name, "diff": diff}
                                ], step),
                                session_id,
                            )

            return result

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Error executing {tool_name}: {str(e)}"
            if emit_events:
                await self._emit(
                    evt_tool_error(run_id, tc_id, tool_name, error_msg, duration_ms, step),
                    session_id,
                )
            return error_msg

    # ── System message processing (subagent announces) ────────────

    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        logger.info(f"Processing system message from {msg.sender_id}")
        
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )
        
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    # ── Direct processing (CLI / cron) ────────────────────────────

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""
