"""Tests for AgentBuilder._build_permissions() under new strict semantics."""
from unittest.mock import MagicMock


def _make_env(global_deny=None, global_require_approval=None):
    """Build a minimal RuntimeEnvironment mock."""
    cfg = MagicMock()
    cfg.permissions.deny = global_deny or []
    cfg.permissions.require_approval = global_require_approval or []
    env = MagicMock()
    env.config = cfg
    return env


def _make_spec(
    permissions=None,
    tools=None,
    sub_agents=None,
    hitl_mode="on_request",
    workflow=None,
):
    spec = MagicMock()
    spec.configure_mock(**{
        "tools": tools or [],
        "sub_agents": sub_agents,
        "hitl_mode": hitl_mode,
        "workflow": workflow,
    })
    # AgentSpec.permissions is never None; default is PermissionConfig() which has empty lists.
    spec.permissions = permissions if permissions is not None else _make_permissions(allow=[])
    return spec


def _make_permissions(allow=None, deny=None, require_approval=None):
    p = MagicMock()
    p.allow = allow or []
    p.deny = deny or []
    p.require_approval = require_approval or []
    return p


def _build(spec, env):
    from everstaff.builder.agent_builder import AgentBuilder
    builder = AgentBuilder.__new__(AgentBuilder)
    builder._spec = spec
    builder._env = env
    return builder._build_permissions()


# ── empty PermissionConfig (the real default AgentSpec produces) ───────────────

def test_empty_permissions_denies_plain_tool():
    """Empty allow list → strict whitelist → plain tools denied."""
    spec = _make_spec(permissions=_make_permissions(allow=[]), hitl_mode="never")
    checker = _build(spec, _make_env())
    assert not checker.check("Bash", {}).allowed


def test_empty_permissions_allows_hitl_tool():
    """Empty allow + hitl_mode=on_request → request_human_input auto-injected."""
    spec = _make_spec(permissions=_make_permissions(allow=[]), hitl_mode="on_request")
    checker = _build(spec, _make_env())
    assert checker.check("request_human_input", {}).allowed


def test_empty_permissions_allows_delegate_when_sub_agents():
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        sub_agents={"worker": MagicMock()},
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    assert checker.check("delegate_task_to_subagent", {}).allowed


def test_empty_permissions_allows_workflow_when_enabled():
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        workflow=MagicMock(),
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    assert checker.check("write_workflow_plan", {}).allowed


# ── permissions field present ──────────────────────────────────────────────────

def test_empty_allow_denies_plain_tool():
    """permissions.allow=[] → strict → plain tool denied."""
    spec = _make_spec(permissions=_make_permissions(allow=[]), hitl_mode="never")
    checker = _build(spec, _make_env())
    assert not checker.check("Bash", {}).allowed


def test_explicit_allow_permits_tool():
    spec = _make_spec(permissions=_make_permissions(allow=["Bash"]), hitl_mode="never")
    checker = _build(spec, _make_env())
    assert checker.check("Bash", {}).allowed
    assert not checker.check("Read", {}).allowed


def test_framework_tools_injected_even_with_empty_allow():
    """Framework tools are injected unconditionally when features are enabled."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        hitl_mode="on_request",
        sub_agents={"w": MagicMock()},
        workflow=MagicMock(),
    )
    checker = _build(spec, _make_env())
    assert checker.check("request_human_input", {}).allowed
    assert checker.check("delegate_task_to_subagent", {}).allowed
    assert checker.check("write_workflow_plan", {}).allowed
    assert not checker.check("Bash", {}).allowed  # not a framework tool


# ── global deny overrides agent allow ─────────────────────────────────────────

def test_global_deny_overrides_agent_allow():
    spec = _make_spec(permissions=_make_permissions(allow=["Bash"]), hitl_mode="never")
    env = _make_env(global_deny=["Bash"])
    checker = _build(spec, env)
    assert not checker.check("Bash", {}).allowed


def test_global_require_approval_overrides_agent_allow():
    spec = _make_spec(permissions=_make_permissions(allow=["Bash"]), hitl_mode="never")
    env = _make_env(global_require_approval=["Bash"])
    checker = _build(spec, env)
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.require_approval is True


# ── agent-level deny overrides agent-level allow ───────────────────────────────

def test_agent_deny_overrides_agent_allow():
    """Agent-level deny wins over agent-level allow."""
    spec = _make_spec(
        permissions=_make_permissions(allow=["Bash", "Read"], deny=["Read"]),
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    assert checker.check("Bash", {}).allowed
    assert not checker.check("Read", {}).allowed


# ── spec.tools auto-inject ─────────────────────────────────────────────────────

def test_spec_tools_auto_injected_into_allow():
    """Tools listed in spec.tools are automatically permitted."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        tools=["Bash", "Read"],
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    assert checker.check("Bash", {}).allowed
    assert checker.check("Read", {}).allowed
    assert not checker.check("Glob", {}).allowed


def test_spec_tools_auto_injected_with_empty_permissions():
    """spec.tools auto-injected even when permissions has empty allow list."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        tools=["Read"],
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    assert checker.check("Read", {}).allowed
    assert not checker.check("Bash", {}).allowed


def test_spec_tools_in_deny_still_blocked():
    """spec.tools that are in deny list are NOT injected into allow (deny wins)."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[], deny=["Bash"]),
        tools=["Bash", "Read"],
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    assert not checker.check("Bash", {}).allowed  # denied — not injected into allow
    assert checker.check("Read", {}).allowed       # allowed via spec.tools


# ── bootstrap tools injection ──────────────────────────────────────────────────

def test_bootstrap_tools_injected_when_enabled():
    """enable_bootstrap=True auto-injects create_agent and create_skill into allow."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        hitl_mode="never",
    )
    spec.enable_bootstrap = True
    checker = _build(spec, _make_env())
    assert checker.check("create_agent", {}).allowed
    assert checker.check("create_skill", {}).allowed


def test_bootstrap_tools_not_injected_when_disabled():
    """enable_bootstrap=False does not inject bootstrap tools."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        hitl_mode="never",
    )
    spec.enable_bootstrap = False
    checker = _build(spec, _make_env())
    assert not checker.check("create_agent", {}).allowed
    assert not checker.check("create_skill", {}).allowed
