from __future__ import annotations

import fnmatch
from typing import Any

from everstaff.protocols import PermissionResult


def _parse_permission_pattern(pattern: str) -> tuple[str, str | None, str | None]:
    """Parse a permission pattern string.

    Formats:
        "Bash"               → ("Bash", None, None)        — tool-only, matches all args
        "Bash(*)"            → ("Bash", None, "*")         — explicit wildcard, same as bare name
        "Bash(ls *)"         → ("Bash", None, "ls *")      — shorthand, glob-matched against every string arg
        "Bash(command:ls *)" → ("Bash", "command", "ls *") — explicit key, glob-matched against only that arg

    Returns (tool_pattern, arg_key_or_none, arg_value_pattern_or_none).
    """
    if "(" not in pattern or not pattern.endswith(")"):
        return pattern, None, None
    idx = pattern.index("(")
    tool_pattern = pattern[:idx]
    inner = pattern[idx + 1 : -1]
    if not inner:
        return tool_pattern, None, None
    # Check for explicit key: "key:value_pattern"
    if ":" in inner:
        colon = inner.index(":")
        key = inner[:colon]
        # Ensure key looks like an identifier (not a path like /foo/bar:baz)
        if key.isidentifier():
            return tool_pattern, key, inner[colon + 1 :]
    return tool_pattern, None, inner


def _matches_rule(pattern: str, tool_name: str, args: dict[str, Any]) -> bool:
    """Check if a permission pattern matches a tool call.

    For patterns without an explicit key (e.g. ``Bash(ls *)``), the arg pattern
    is matched against every string-valued argument.  This avoids a centralised
    primary-arg registry — the tool's ``permission_hint`` is only used at *grant
    time* to suggest the pattern, not at *check time*.
    """
    pat_tool, pat_key, pat_val = _parse_permission_pattern(pattern)
    if not fnmatch.fnmatch(tool_name, pat_tool):
        return False
    if pat_val is None:
        return True  # No arg constraint → match all invocations

    if pat_key is not None:
        # Explicit key → match only that arg; missing key = no match
        if pat_key not in args:
            return False
        arg_val = str(args[pat_key])
        return fnmatch.fnmatch(arg_val, pat_val)

    # No explicit key → match against any string-valued arg
    for v in args.values():
        if isinstance(v, str) and fnmatch.fnmatch(v, pat_val):
            return True
    return False


class RuleBasedChecker:
    """
    Permission checker with allow/deny rule lists.

    Priority: deny > allow > default.

    strict=True  (default): empty allow = deny all (whitelist mode).
    strict=False           : empty allow = allow all (global/open mode).

    Supports:
      - ``fnmatch`` wildcards on tool name: ``Bash*``
      - Argument patterns: ``Bash(ls *)``, ``Bash(command:ls *)``
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
            if _matches_rule(pattern, tool_name, args):
                return True
        return False

    def matches_allow(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Return True if tool_name matches any allow pattern."""
        for pattern in self._allow:
            if _matches_rule(pattern, tool_name, args):
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
