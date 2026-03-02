import pytest
from everstaff.permissions.rule_checker import RuleBasedChecker
from everstaff.permissions.dynamic_checker import DynamicPermissionChecker


def _make_checker(
    global_allow=None, global_deny=None,
    agent_allow=None, agent_deny=None,
    session_grants=None,
    system_tools=None,
):
    global_checker = RuleBasedChecker(
        allow=global_allow or [], deny=global_deny or [],
    ) if (global_allow is not None or global_deny is not None) else None
    agent_checker = RuleBasedChecker(
        allow=agent_allow or [], deny=agent_deny or [],
    )
    return DynamicPermissionChecker(
        global_checker=global_checker,
        agent_checker=agent_checker,
        session_grants=session_grants or [],
        is_system_tool=lambda name: name in (system_tools or set()),
    )


def test_deny_always_wins():
    checker = _make_checker(agent_allow=["Bash"], agent_deny=["Bash"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl


def test_global_deny_wins_over_agent_allow():
    checker = _make_checker(global_deny=["Bash"], agent_allow=["Bash"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl


def test_agent_allow_permits():
    checker = _make_checker(agent_allow=["Read"])
    result = checker.check("Read", {})
    assert result.allowed


def test_global_allow_permits():
    checker = _make_checker(global_allow=["Read"])
    result = checker.check("Read", {})
    assert result.allowed


def test_union_allow():
    """Tool in global allow OR agent allow should be permitted."""
    checker = _make_checker(global_allow=["Read"], agent_allow=["Glob"])
    assert checker.check("Read", {}).allowed
    assert checker.check("Glob", {}).allowed


def test_session_grants_permit():
    checker = _make_checker(session_grants=["Bash"])
    result = checker.check("Bash", {})
    assert result.allowed


def test_system_tool_always_allowed():
    checker = _make_checker(system_tools={"request_human_input"})
    result = checker.check("request_human_input", {})
    assert result.allowed


def test_unknown_tool_triggers_hitl():
    checker = _make_checker(agent_allow=["Read"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl is True


def test_add_session_grant():
    checker = _make_checker()
    result = checker.check("Bash", {})
    assert result.needs_hitl

    checker.add_session_grant("Bash")
    result = checker.check("Bash", {})
    assert result.allowed


def test_deny_beats_session_grant():
    checker = _make_checker(agent_deny=["Bash"], session_grants=["Bash"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl


def test_deny_beats_system_tool():
    """Explicit deny blocks even system tools."""
    checker = _make_checker(agent_deny=["request_human_input"], system_tools={"request_human_input"})
    result = checker.check("request_human_input", {})
    assert not result.allowed


def test_session_grants_property():
    checker = _make_checker(session_grants=["Bash"])
    checker.add_session_grant("Write")
    grants = checker.session_grants
    assert "Bash" in grants
    assert "Write" in grants


def test_no_duplicate_session_grants():
    checker = _make_checker()
    checker.add_session_grant("Bash")
    checker.add_session_grant("Bash")
    assert checker.session_grants.count("Bash") == 1
