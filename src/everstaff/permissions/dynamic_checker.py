"""DynamicPermissionChecker — wraps static checkers with session grants and HITL fallback."""
from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING, Any, Callable

from everstaff.protocols import PermissionResult

if TYPE_CHECKING:
    from everstaff.permissions.rule_checker import RuleBasedChecker


class DynamicPermissionChecker:
    """Middleware permission checker.

    Resolution order:
    1. deny (global + agent) → reject
    2. allow (global OR agent, union) → permit
    3. session grants → permit
    4. system tool → permit
    5. fallback → needs_hitl=True
    """

    def __init__(
        self,
        global_checker: RuleBasedChecker | None,
        agent_checker: RuleBasedChecker,
        session_grants: list[str],
        is_system_tool: Callable[[str], bool],
    ) -> None:
        self._global = global_checker
        self._agent = agent_checker
        self._session_grants = list(session_grants)
        self._is_system = is_system_tool

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        # 1. Deny check (global + agent)
        if self._global is not None and self._global.matches_deny(tool_name, args):
            return PermissionResult(allowed=False, reason=f"Denied by global policy for '{tool_name}'")
        if self._agent.matches_deny(tool_name, args):
            return PermissionResult(allowed=False, reason=f"Denied by agent policy for '{tool_name}'")

        # 2. Allow check (union: global OR agent)
        if self._global is not None and self._global.matches_allow(tool_name, args):
            return PermissionResult(allowed=True)
        if self._agent.matches_allow(tool_name, args):
            return PermissionResult(allowed=True)

        # 3. Session grants
        for pattern in self._session_grants:
            if fnmatch.fnmatch(tool_name, pattern):
                return PermissionResult(allowed=True)

        # 4. System tool bypass
        if self._is_system(tool_name):
            return PermissionResult(allowed=True)

        # 5. Not found → HITL
        return PermissionResult(
            allowed=False,
            needs_hitl=True,
            reason=f"'{tool_name}' not in allow list, requires human approval",
        )

    def add_session_grant(self, pattern: str) -> None:
        """Add a permission pattern for the current session."""
        if pattern not in self._session_grants:
            self._session_grants.append(pattern)

    @property
    def session_grants(self) -> list[str]:
        """Return current session grants (for persistence)."""
        return list(self._session_grants)
