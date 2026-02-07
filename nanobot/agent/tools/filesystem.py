"""File system tools: read, write, edit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _resolve_path(raw_path: str, *, root: Path | None) -> tuple[Path | None, str | None]:
    """Resolve a user-supplied path.

    If root is set, the final resolved path must be within that directory.
    Relative paths are interpreted as relative to root.
    """

    if not raw_path:
        return None, "Error: path is required"

    try:
        p = Path(raw_path).expanduser()
    except Exception as e:
        return None, f"Error: invalid path: {e}"

    if root is None:
        return p, None

    try:
        root_resolved = root.expanduser().resolve()
        if not p.is_absolute():
            p = root_resolved / p
        resolved = p.resolve()

        # Python 3.11: Path.is_relative_to
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return resolved, None
        return None, "Error: path is outside allowed root"
    except Exception as e:
        return None, f"Error: invalid path: {e}"


def _display_path(p: Path, *, root: Path | None) -> str:
    if root is None:
        return str(p)
    try:
        return p.resolve().relative_to(root.expanduser().resolve()).as_posix()
    except Exception:
        return str(p)


class ReadFileTool(Tool):
    """Tool to read file contents."""

    def __init__(self, *, root: str | Path | None = None):
        self._root = Path(root).expanduser() if root else None

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read",
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        resolved, err = _resolve_path(path, root=self._root)
        if err:
            return err
        assert resolved is not None

        try:
            if not resolved.exists():
                return f"Error: File not found: {_display_path(resolved, root=self._root)}"
            if not resolved.is_file():
                return f"Error: Not a file: {_display_path(resolved, root=self._root)}"
            return resolved.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"Error: Permission denied: {_display_path(resolved, root=self._root)}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, *, root: str | Path | None = None):
        self._root = Path(root).expanduser() if root else None

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        resolved, err = _resolve_path(path, root=self._root)
        if err:
            return err
        assert resolved is not None

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {_display_path(resolved, root=self._root)}"
        except PermissionError:
            return f"Error: Permission denied: {_display_path(resolved, root=self._root)}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, *, root: str | Path | None = None):
        self._root = Path(root).expanduser() if root else None

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to edit",
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace",
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        resolved, err = _resolve_path(path, root=self._root)
        if err:
            return err
        assert resolved is not None

        try:
            if not resolved.exists():
                return f"Error: File not found: {_display_path(resolved, root=self._root)}"

            content = resolved.read_text(encoding="utf-8", errors="replace")
            if old_text not in content:
                return "Error: old_text not found in file. Make sure it matches exactly."

            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            resolved.write_text(new_content, encoding="utf-8")
            return f"Successfully edited {_display_path(resolved, root=self._root)}"
        except PermissionError:
            return f"Error: Permission denied: {_display_path(resolved, root=self._root)}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, *, root: str | Path | None = None):
        self._root = Path(root).expanduser() if root else None

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list",
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        resolved, err = _resolve_path(path, root=self._root)
        if err:
            return err
        assert resolved is not None

        try:
            if not resolved.exists():
                return f"Error: Directory not found: {_display_path(resolved, root=self._root)}"
            if not resolved.is_dir():
                return f"Error: Not a directory: {_display_path(resolved, root=self._root)}"

            items = []
            for item in sorted(resolved.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {_display_path(resolved, root=self._root)} is empty"

            return "\n".join(items)
        except PermissionError:
            return f"Error: Permission denied: {_display_path(resolved, root=self._root)}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
