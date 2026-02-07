"""Web server settings for fanfan (OpenCode-style WebUI server).

This settings module is intentionally separate from ~/.fanfan/config.json:
- ~/.fanfan/config.json keeps LLM/provider config (existing behavior)
- .env (or environment variables) controls web runtime behavior (ports, UI proxy, DB path, permissions)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    # nanobot/web/settings.py -> nanobot/web -> nanobot -> repo root
    return Path(__file__).resolve().parents[2]


Policy = Literal["deny", "ask", "allow"]
UiMode = Literal["static", "remote", "dev"]


class WebSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FANFAN_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 4096

    # Data / DB
    data_dir: str = "data"
    db_path: str | None = None
    db_copy_from_legacy: bool = True

    # UI proxy/serving
    ui_mode: UiMode = "static"
    ui_url: str = ""  # required when ui_mode=remote
    ui_static_dir: str = "nanobot/web/static/dist"
    ui_dev_server_url: str = "http://127.0.0.1:4444"

    # SSE
    sse_heartbeat_s: float = 15.0
    sse_wait_timeout_s: float = 15.0

    # CSP
    csp: str = "default-src 'self'"
    csp_dev: str = (
        "default-src 'self' blob: data:; "
        "img-src 'self' blob: data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "connect-src 'self' ws: wss: http: https:; "
        "worker-src 'self' blob:; "
        "frame-ancestors 'self';"
    )

    # Optional auth for write endpoints (MVP: bearer token)
    auth_token: str = ""

    # Tool permissions (defaults can be overridden per tool)
    tool_policy_default: Policy = "ask"
    tool_policy_run_command: Policy | None = None
    tool_policy_read_file: Policy | None = None
    tool_policy_write_file: Policy | None = None
    tool_policy_apply_patch: Policy | None = None
    tool_policy_search: Policy | None = None
    tool_policy_http_fetch: Policy | None = None

    # Tool enable flags
    tool_enabled_run_command: bool = True
    tool_enabled_read_file: bool = True
    tool_enabled_write_file: bool = True
    tool_enabled_apply_patch: bool = True
    tool_enabled_search: bool = True
    tool_enabled_http_fetch: bool = True

    def resolved_data_dir(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else repo_root() / p

    def resolved_db_path(self) -> Path:
        if self.db_path:
            p = Path(self.db_path)
            return p if p.is_absolute() else repo_root() / p

        # Always prefer a per-repo DB to avoid accidental cross-instance corruption.
        # If a legacy global DB exists, create_app() may optionally copy it into data_dir.
        return self.resolved_data_dir() / "fanfan.db"

    def resolved_ui_static_dir(self) -> Path:
        p = Path(self.ui_static_dir)
        return p if p.is_absolute() else repo_root() / p

    def tool_policy(self, tool_name: str) -> Policy:
        override = {
            "run_command": self.tool_policy_run_command,
            "read_file": self.tool_policy_read_file,
            "write_file": self.tool_policy_write_file,
            "apply_patch": self.tool_policy_apply_patch,
            "search": self.tool_policy_search,
            "http_fetch": self.tool_policy_http_fetch,
        }.get(tool_name)
        return override or self.tool_policy_default

    def tool_enabled(self, tool_name: str) -> bool:
        return {
            "run_command": self.tool_enabled_run_command,
            "read_file": self.tool_enabled_read_file,
            "write_file": self.tool_enabled_write_file,
            "apply_patch": self.tool_enabled_apply_patch,
            "search": self.tool_enabled_search,
            "http_fetch": self.tool_enabled_http_fetch,
        }.get(tool_name, True)
