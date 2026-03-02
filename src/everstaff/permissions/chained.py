"""ChainedPermissionChecker — runs checkers in order, stops at first rejection."""
from __future__ import annotations

from typing import Any

from everstaff.protocols import PermissionChecker, PermissionResult


class ChainedPermissionChecker:
    """Evaluates permission checkers in order.

    The first checker to return allowed=False wins. This means a global
    deny always overrides per-agent allow rules.
    """

    def __init__(self, *checkers: PermissionChecker) -> None:
        self._checkers = checkers

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        for checker in self._checkers:
            result = checker.check(tool_name, args)
            if not result.allowed:
                return result
        return PermissionResult(allowed=True)
