"""OpenCode-aligned tool aliases.

The existing project started with tool names like:
- exec, web_search, web_fetch

The fanfan v2 web protocol requires:
- run_command, search, http_fetch

These wrappers keep the implementation in one place while exposing the desired names.
"""

from __future__ import annotations

from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool


class RunCommandTool(ExecTool):
    def __init__(self, **kwargs):
        super().__init__(tool_name="run_command", **kwargs)

    @property
    def description(self) -> str:  # type: ignore[override]
        return "Run a shell command and stream its output."


class SearchTool(WebSearchTool):
    name = "search"
    description = "Search the web. Returns titles, URLs, and snippets."


class HttpFetchTool(WebFetchTool):
    name = "http_fetch"
    description = "Fetch a URL and extract readable content (HTML -> markdown/text)."

