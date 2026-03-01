from __future__ import annotations

import fnmatch
from typing import Any

from everstaff.protocols import PermissionResult


class RuleBasedChecker:
    """
    Permission checker with allow/deny/require_approval rule lists.

    Priority: deny > require_approval > allow > default.

    strict=True  (default): empty allow = deny all (whitelist mode).
    strict=False           : empty allow = allow all (global/open mode).

    Supports fnmatch wildcards (e.g. "Bash*").
    """

    def __init__(
        self,
        allow: list[str],
        deny: list[str],
        require_approval: list[str] | None = None,
        strict: bool = True,
    ) -> None:
        self._allow = list(allow)
        self._deny = list(deny)
        self._require_approval = list(require_approval or [])
        self._strict = strict

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        # 1. deny wins always
        for pattern in self._deny:
            if fnmatch.fnmatch(tool_name, pattern):
                return PermissionResult(
                    allowed=False,
                    reason=f"Matched deny rule '{pattern}'",
                )

        # 2. require_approval — fires before allow (higher priority)
        for pattern in self._require_approval:
            if fnmatch.fnmatch(tool_name, pattern):
                return PermissionResult(
                    allowed=False,
                    require_approval=True,
                    reason=f"Matched require_approval rule '{pattern}'",
                )

        # 3. allow whitelist
        for pattern in self._allow:
            if fnmatch.fnmatch(tool_name, pattern):
                return PermissionResult(allowed=True)

        # 4. default: strict = deny, open = allow
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
        all_approval: list[str] = []
        for c in checkers:
            all_deny.extend(c._deny)
            all_allow.extend(c._allow)
            all_approval.extend(c._require_approval)
        return cls(
            allow=all_allow,
            deny=all_deny,
            require_approval=all_approval,
            strict=True,
        )
