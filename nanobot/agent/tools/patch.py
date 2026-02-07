"""apply_patch tool: apply a unified diff to the workspace.

This is used by the fanfan v2 web runner to support OpenCode-style patch workflows.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


_DIFF_START_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")
_PLUS_RE = re.compile(r"^\+\+\+ b/(.+)$")


def _extract_files_from_patch(patch: str) -> list[dict[str, str]]:
    """Return [{path, diff}] split by diff --git sections."""
    lines = patch.splitlines()
    files: list[dict[str, str]] = []
    cur_path: str | None = None
    cur_lines: list[str] = []

    def _flush() -> None:
        nonlocal cur_path, cur_lines
        if cur_path and cur_lines:
            files.append({"path": cur_path, "diff": "\n".join(cur_lines) + "\n"})
        cur_path = None
        cur_lines = []

    for line in lines:
        m = _DIFF_START_RE.match(line)
        if m:
            _flush()
            # Prefer the b/ path
            cur_path = m.group(2)
            cur_lines.append(line)
            continue
        if cur_path is None:
            # Try to recover path from +++ b/ line for patches without diff --git
            pm = _PLUS_RE.match(line)
            if pm:
                cur_path = pm.group(1)
        cur_lines.append(line)

    _flush()

    if not files:
        return [{"path": "", "diff": patch if patch.endswith("\n") else patch + "\n"}]
    return files


def _validate_rel_path(path: str) -> str | None:
    if not path:
        return None
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:\\\\", path):
        return "absolute paths are not allowed"
    if ".." in Path(path).parts:
        return "path traversal is not allowed"
    return None


class ApplyPatchTool(Tool):
    def __init__(self, *, allowed_root: str | Path | None = None):
        # If set, every patched file must resolve within this root.
        self._allowed_root = Path(allowed_root).expanduser().resolve() if allowed_root else None

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return "Apply a unified diff patch to the repository (git apply)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Unified diff to apply"},
            },
            "required": ["patch"],
        }

    async def execute(self, patch: str, **kwargs: Any) -> str:
        # Validate patch file paths best-effort before applying.
        files = _extract_files_from_patch(patch)

        # Apply using git (works for multi-file patches and keeps implementation small).
        cwd = kwargs.get("cwd") or kwargs.get("workdir") or kwargs.get("working_dir") or None
        cwd_path = Path(str(cwd)).expanduser().resolve() if cwd else Path.cwd().resolve()

        for f in files:
            rel = str(f.get("path", "") or "")
            err = _validate_rel_path(rel)
            if err:
                return json.dumps({"applied": False, "error": f"invalid path in patch: {err}", "files": files})

            if self._allowed_root and rel:
                try:
                    candidate = (cwd_path / rel).resolve()
                    if candidate != self._allowed_root and not candidate.is_relative_to(self._allowed_root):
                        return json.dumps(
                            {
                                "applied": False,
                                "error": "invalid path in patch: path is outside allowed root",
                                "files": files,
                            },
                            ensure_ascii=False,
                        )
                except Exception:
                    return json.dumps(
                        {
                            "applied": False,
                            "error": "invalid path in patch: failed to resolve path",
                            "files": files,
                        },
                        ensure_ascii=False,
                    )

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "apply",
                "--whitespace=nowarn",
                "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd_path),
            )
            assert proc.stdin is not None
            proc.stdin.write(patch.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            stdout_b, stderr_b = await proc.communicate()
            ok = proc.returncode == 0
            stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
            stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
            return json.dumps(
                {
                    "applied": ok,
                    "files": files,
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"applied": False, "error": str(e), "files": files}, ensure_ascii=False)
