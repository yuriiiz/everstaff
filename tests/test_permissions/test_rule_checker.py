from everstaff.protocols import PermissionResult
from everstaff.permissions.rule_checker import RuleBasedChecker


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


def test_require_approval_wins_over_allow():
    """require_approval fires even when the tool is also in allow."""
    checker = RuleBasedChecker(
        allow=["Bash"],
        deny=[],
        require_approval=["Bash"],
    )
    result = checker.check("Bash", {})
    assert result.allowed is False
    assert result.require_approval is True


def test_deny_wins_over_require_approval():
    checker = RuleBasedChecker(
        allow=["Bash"],
        deny=["Bash"],
        require_approval=["Bash"],
    )
    result = checker.check("Bash", {})
    assert result.allowed is False
    assert result.require_approval is False  # deny, not approval


def test_require_approval_with_strict_and_tool_not_in_allow():
    """require_approval fires before the whitelist default-deny."""
    checker = RuleBasedChecker(allow=[], deny=[], require_approval=["deploy*"])
    result = checker.check("deploy-prod", {})
    assert result.allowed is False
    assert result.require_approval is True


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


def test_non_strict_require_approval_fires():
    checker = RuleBasedChecker(allow=[], deny=[], require_approval=["deploy*"], strict=False)
    result = checker.check("deploy-prod", {})
    assert result.allowed is False
    assert result.require_approval is True


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


def test_merge_combines_require_approval():
    c1 = RuleBasedChecker(allow=["send:*"], deny=[], require_approval=["send:*"])
    c2 = RuleBasedChecker(allow=["delete:*"], deny=[], require_approval=["delete:*"])
    merged = RuleBasedChecker.merge([c1, c2])
    assert merged.check("send:email", {}).require_approval is True
    assert merged.check("delete:file", {}).require_approval is True


def test_merge_preserves_strict_true():
    """Merged checker must remain strict (deny-all by default)."""
    a = RuleBasedChecker(allow=["Read"], deny=[])
    b = RuleBasedChecker(allow=["Glob"], deny=[])
    merged = RuleBasedChecker.merge([a, b])
    assert not merged.check("Bash", {}).allowed  # not in merged allow
