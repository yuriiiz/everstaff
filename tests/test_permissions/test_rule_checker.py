import warnings

from everstaff.protocols import PermissionResult
from everstaff.permissions.rule_checker import RuleBasedChecker


# ── PermissionResult ──────────────────────────────────────────────────────────

def test_permission_result_has_needs_hitl_field():
    from everstaff.protocols import PermissionResult
    result = PermissionResult(allowed=False, needs_hitl=True)
    assert result.needs_hitl is True
    result2 = PermissionResult(allowed=True)
    assert result2.needs_hitl is False


def test_permission_grant_scope_enum():
    from everstaff.permissions import PermissionGrantScope
    assert PermissionGrantScope.ONCE == "once"
    assert PermissionGrantScope.SESSION == "session"
    assert PermissionGrantScope.PERMANENT == "permanent"


# ── PermissionConfig deprecation ─────────────────────────────────────────────

def test_permission_config_require_approval_deprecated():
    from everstaff.permissions import PermissionConfig
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = PermissionConfig(allow=["Read"], deny=[], require_approval=["Bash"])
        assert len(w) == 1
        assert "deprecated" in str(w[0].message).lower()
    assert cfg.require_approval == []


def test_permission_config_no_warning_without_require_approval():
    from everstaff.permissions import PermissionConfig
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = PermissionConfig(allow=["Read"], deny=[])
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(dep_warnings) == 0


# ── strict=True (default) ─────────────────────────────────────────────────────

def test_strict_empty_allow_denies_everything():
    """allow=[] with strict=True must deny all tools."""
    checker = RuleBasedChecker(allow=[], deny=[])
    assert not checker.check("any_tool", {}).allowed


def test_strict_tool_in_allow_is_permitted():
    checker = RuleBasedChecker(allow=["Read", "Glob"], deny=[])
    assert checker.check("Read", {}).allowed
    assert checker.check("Glob", {}).allowed
    assert not checker.check("Bash", {}).allowed


def test_deny_wins_over_allow():
    checker = RuleBasedChecker(allow=["Bash"], deny=["Bash"])
    assert not checker.check("Bash", {}).allowed
    assert "deny" in checker.check("Bash", {}).reason.lower()


def test_wildcard_deny():
    checker = RuleBasedChecker(allow=["Bash", "Bash_exec", "Read"], deny=["Bash*"])
    assert not checker.check("Bash", {}).allowed
    assert not checker.check("Bash_exec", {}).allowed
    # Non-matching tool that is in the allow list must still be permitted
    assert checker.check("Read", {}).allowed


def test_wildcard_allow():
    checker = RuleBasedChecker(allow=["Bash*"], deny=[])
    assert checker.check("Bash", {}).allowed
    assert checker.check("Bash_exec", {}).allowed
    assert not checker.check("Read", {}).allowed


# ── strict=False (global checker / open mode) ─────────────────────────────────

def test_non_strict_empty_allow_permits_everything():
    """strict=False with allow=[] must allow all (pass-through for global checker)."""
    checker = RuleBasedChecker(allow=[], deny=[], strict=False)
    assert checker.check("any_tool", {}).allowed


def test_non_strict_deny_still_blocks():
    checker = RuleBasedChecker(allow=[], deny=["Bash"], strict=False)
    assert not checker.check("Bash", {}).allowed
    assert checker.check("Read", {}).allowed


# ── merge ──────────────────────────────────────────────────────────────────────

def test_merge_combines_allow_and_deny():
    a = RuleBasedChecker(allow=["Read"], deny=["Bash"])
    b = RuleBasedChecker(allow=["Glob"], deny=["Write"])
    merged = RuleBasedChecker.merge([a, b])
    assert not merged.check("Bash", {}).allowed
    assert not merged.check("Write", {}).allowed
    assert merged.check("Read", {}).allowed
    assert merged.check("Glob", {}).allowed
    assert not merged.check("Edit", {}).allowed  # not in either allow list


def test_merge_preserves_strict_true():
    """Merged checker must remain strict (deny-all by default)."""
    a = RuleBasedChecker(allow=["Read"], deny=[])
    b = RuleBasedChecker(allow=["Glob"], deny=[])
    merged = RuleBasedChecker.merge([a, b])
    assert not merged.check("Bash", {}).allowed  # not in merged allow
