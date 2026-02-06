"""Shell execution tool."""

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """Tool to execute shell commands."""
    
    def __init__(
        self,
        tool_name: str = "exec",
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
    ):
        self._tool_name = tool_name
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"\b(format|mkfs|diskpart)\b",   # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
    
    @property
    def name(self) -> str:
        return self._tool_name
    
    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                }
            },
            "required": ["command"]
        }
    
    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error
        
        try:
            stream_cb = kwargs.get("_stream_cb")

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            out_parts: list[str] = []
            err_parts: list[str] = []

            async def _emit(stream_name: str, text: str) -> None:
                if not stream_cb:
                    return
                try:
                    res = stream_cb(stream=stream_name, text=text)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    # Streaming is best-effort; the command result must still complete.
                    return

            async def _read_pipe(pipe: asyncio.StreamReader | None, stream_name: str) -> None:
                if pipe is None:
                    return
                while True:
                    chunk = await pipe.read(1024)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    if stream_name == "stdout":
                        out_parts.append(text)
                    else:
                        err_parts.append(text)
                    await _emit(stream_name, text)

            t_out = asyncio.create_task(_read_pipe(process.stdout, "stdout"))
            t_err = asyncio.create_task(_read_pipe(process.stderr, "stderr"))

            try:
                await asyncio.wait_for(process.wait(), timeout=self.timeout)
            except asyncio.TimeoutError:
                process.kill()
                await _emit("stderr", f"\n[timeout] killed after {self.timeout}s\n")
                return f"Error: Command timed out after {self.timeout} seconds"
            finally:
                # Drain pipes quickly
                await asyncio.gather(t_out, t_err, return_exceptions=True)

            output_parts: list[str] = []
            if out_parts:
                output_parts.append("".join(out_parts))
            if err_parts and "".join(err_parts).strip():
                output_parts.append("STDERR:\n" + "".join(err_parts))

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"
            
            # Truncate very long output
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"
            
            return result
            
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            posix_paths = re.findall(r"/[^\s\"']+", cmd)

            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw).resolve()
                except Exception:
                    continue
                if cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None
