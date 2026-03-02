from __future__ import annotations

import fnmatch
from typing import Any

from everstaff.protocols import PermissionResult


class RuleBasedChecker:
    """
    Permission checker with allow/deny rule lists.

    Priority: deny > allow > default.

    strict=True  (default): empty allow = deny all (whitelist mode).
    strict=False           : empty allow = allow all (global/open mode).

    Supports fnmatch wildcards (e.g. "Bash*").
    """

    def __init__(
        self,
        allow: list[str],
        deny: list[str],
        strict: bool = True,
    ) -> None:
        self._allow = list(allow)
        self._deny = list(deny)
        self._strict = strict

    def matches_deny(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Return True if tool_name matches any deny pattern."""
        for pattern in self._deny:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
        return False

    def matches_allow(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Return True if tool_name matches any allow pattern."""
        for pattern in self._allow:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
        return False

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        # 1. deny wins always
        if self.matches_deny(tool_name, args):
            return PermissionResult(
                allowed=False,
                reason=f"Matched deny rule for '{tool_name}'",
            )

        # 2. allow whitelist
        if self.matches_allow(tool_name, args):
            return PermissionResult(allowed=True)

        # 3. default: strict = deny, open = allow
        if self._strict:
            return PermissionResult(
                allowed=False,
                reason=f"'{tool_name}' not in allow list",
            )
        return PermissionResult(allowed=True)

    @classmethod
    def merge(cls, checkers: list[RuleBasedChecker]) -> RuleBasedChecker:
        """Union of all rules. Merged checker is always strict=True."""
        all_deny: list[str] = []
        all_allow: list[str] = []
        for c in checkers:
            all_deny.extend(c._deny)
            all_allow.extend(c._allow)
        return cls(
            allow=all_allow,
            deny=all_deny,
            strict=True,
        )
