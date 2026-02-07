"""Tool permission gate for fanfan web runs (v2).

Policy levels:
- deny: tool execution is blocked
- allow: tool executes without prompt
- ask: emits a permission-required tool_call and waits for UI resolution
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

from nanobot.web.database import Database
from nanobot.web.settings import Policy, WebSettings


ResolveStatus = Literal["approved", "denied"]
ResolveScope = Literal["once", "session", "always"]


@dataclass(frozen=True)
class PermissionResult:
    approved: bool
    scope: ResolveScope


class PermissionManager:
    def __init__(self, *, db: Database, settings: WebSettings):
        self._db = db
        self._settings = settings
        self._pending: dict[str, asyncio.Future[PermissionResult]] = {}
        self._pending_meta: dict[str, dict[str, str]] = {}
        self._session_overrides: dict[str, dict[str, Policy]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    def effective_policy(self, *, session_id: str, tool_name: str) -> Policy:
        if not self._settings.tool_enabled(tool_name):
            return "deny"

        if tool_name == "spawn_subagent":
            # Compute-only orchestration; subagent tools still go through approvals.
            return "allow"

        if tool_name in self._session_overrides.get(session_id, {}):
            return self._session_overrides[session_id][tool_name]

        global_policies = self._db.get_tool_permissions()
        if tool_name in global_policies:
            p = global_policies[tool_name]
            if p in ("deny", "ask", "allow"):
                return p  # type: ignore[return-value]
        return self._settings.tool_policy(tool_name)

    async def create_request(
        self,
        *,
        session_id: str,
        turn_id: str,
        step_id: str,
        tool_name: str,
        input_data: dict[str, Any],
    ) -> str:
        rec = self._db.create_permission_request(
            session_id=session_id,
            turn_id=turn_id,
            step_id=step_id,
            tool_name=tool_name,
            input_data=input_data,
        )
        request_id = str(rec["id"])

        fut: asyncio.Future[PermissionResult] = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._pending[request_id] = fut
            self._pending_meta[request_id] = {
                "session_id": session_id,
                "tool_name": tool_name,
            }
        return request_id

    async def wait(self, *, request_id: str, timeout_s: float = 120.0) -> PermissionResult:
        async with self._lock:
            fut = self._pending.get(request_id)
        if fut is None:
            return PermissionResult(approved=False, scope="once")
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            self._db.resolve_permission_request(request_id, status="expired", scope="once")
            await self._finalize(request_id, PermissionResult(approved=False, scope="once"))
            return PermissionResult(approved=False, scope="once")

    async def resolve(
        self,
        *,
        request_id: str,
        status: ResolveStatus,
        scope: ResolveScope,
    ) -> None:
        meta = self._pending_meta.get(request_id) or {}
        session_id = meta.get("session_id", "")
        tool_name = meta.get("tool_name", "")

        approved = status == "approved"
        self._db.resolve_permission_request(request_id, status=status, scope=scope)

        # Persist/remember policy by scope
        if tool_name:
            if scope == "always":
                self._db.upsert_tool_permission(tool_name, "allow" if approved else "deny")
            elif scope == "session" and session_id:
                self._session_overrides[session_id][tool_name] = "allow" if approved else "deny"

        await self._finalize(request_id, PermissionResult(approved=approved, scope=scope))

    async def _finalize(self, request_id: str, result: PermissionResult) -> None:
        async with self._lock:
            fut = self._pending.pop(request_id, None)
            self._pending_meta.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.set_result(result)

