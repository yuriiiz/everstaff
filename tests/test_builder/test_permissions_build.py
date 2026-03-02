"""Tests for AgentBuilder._build_permissions() with DynamicPermissionChecker."""
from unittest.mock import MagicMock

from everstaff.permissions.dynamic_checker import DynamicPermissionChecker


def _make_env(global_deny=None, global_allow=None):
    """Build a minimal RuntimeEnvironment mock."""
    from everstaff.permissions import PermissionConfig
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping

    cfg = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="fake/m")},
        permissions=PermissionConfig(allow=global_allow or [], deny=global_deny or []),
    )
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
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.permissions import PermissionConfig

    perm = permissions if permissions is not None else PermissionConfig()
    spec = AgentSpec(
        agent_name="TestAgent",
        tools=tools or [],
        hitl_mode=hitl_mode,
        permissions=perm,
    )
    # sub_agents and workflow are set via model fields, but we override them
    # directly here for convenience since they require complex objects.
    if sub_agents is not None:
        object.__setattr__(spec, "sub_agents", sub_agents)
    if workflow is not None:
        object.__setattr__(spec, "workflow", workflow)
    return spec


def _make_permissions(allow=None, deny=None):
    from everstaff.permissions import PermissionConfig
    return PermissionConfig(allow=allow or [], deny=deny or [])


def _build(spec, env, system_tool_names=None):
    from everstaff.builder.agent_builder import AgentBuilder
    builder = AgentBuilder.__new__(AgentBuilder)
    builder._spec = spec
    builder._env = env
    return builder._build_permissions(system_tool_names=system_tool_names or set())


# -- returns DynamicPermissionChecker ----------------------------------------

def test_returns_dynamic_checker():
    """_build_permissions always returns DynamicPermissionChecker."""
    spec = _make_spec(permissions=_make_permissions(allow=[]), hitl_mode="never")
    checker = _build(spec, _make_env())
    assert isinstance(checker, DynamicPermissionChecker)


# -- empty PermissionConfig (the real default AgentSpec produces) ------------

def test_empty_permissions_unknown_tool_triggers_hitl():
    """Empty allow list -> unknown tools trigger needs_hitl (not hard deny)."""
    spec = _make_spec(permissions=_make_permissions(allow=[]), hitl_mode="never")
    checker = _build(spec, _make_env())
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl


def test_system_tool_allowed_via_is_system():
    """System tools (e.g. request_human_input) are allowed via is_system_tool."""
    spec = _make_spec(permissions=_make_permissions(allow=[]), hitl_mode="on_request")
    checker = _build(spec, _make_env(), system_tool_names={"request_human_input"})
    assert checker.check("request_human_input", {}).allowed


def test_system_tool_delegate_allowed():
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        sub_agents={"worker": MagicMock()},
        hitl_mode="never",
    )
    checker = _build(spec, _make_env(), system_tool_names={"delegate_task_to_subagent"})
    assert checker.check("delegate_task_to_subagent", {}).allowed


def test_system_tool_workflow_allowed():
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        workflow=MagicMock(),
        hitl_mode="never",
    )
    checker = _build(spec, _make_env(), system_tool_names={"write_workflow_plan"})
    assert checker.check("write_workflow_plan", {}).allowed


# -- permissions field present -----------------------------------------------

def test_empty_allow_triggers_hitl_for_plain_tool():
    """permissions.allow=[] -> plain tool triggers HITL."""
    spec = _make_spec(permissions=_make_permissions(allow=[]), hitl_mode="never")
    checker = _build(spec, _make_env())
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl


def test_explicit_allow_permits_tool():
    spec = _make_spec(permissions=_make_permissions(allow=["Bash"]), hitl_mode="never")
    checker = _build(spec, _make_env())
    assert checker.check("Bash", {}).allowed
    result = checker.check("Read", {})
    assert not result.allowed
    assert result.needs_hitl


def test_framework_tools_allowed_via_system_tool_names():
    """Framework tools are allowed when passed as system_tool_names."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        hitl_mode="on_request",
        sub_agents={"w": MagicMock()},
        workflow=MagicMock(),
    )
    system_tools = {"request_human_input", "delegate_task_to_subagent", "write_workflow_plan"}
    checker = _build(spec, _make_env(), system_tool_names=system_tools)
    assert checker.check("request_human_input", {}).allowed
    assert checker.check("delegate_task_to_subagent", {}).allowed
    assert checker.check("write_workflow_plan", {}).allowed
    # Non-system tool still triggers HITL
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl


# -- global deny overrides agent allow --------------------------------------

def test_global_deny_overrides_agent_allow():
    spec = _make_spec(permissions=_make_permissions(allow=["Bash"]), hitl_mode="never")
    env = _make_env(global_deny=["Bash"])
    checker = _build(spec, env)
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl  # hard deny, not HITL


# -- agent-level deny overrides agent-level allow ---------------------------

def test_agent_deny_overrides_agent_allow():
    """Agent-level deny wins over agent-level allow."""
    spec = _make_spec(
        permissions=_make_permissions(allow=["Bash", "Read"], deny=["Read"]),
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    assert checker.check("Bash", {}).allowed
    result = checker.check("Read", {})
    assert not result.allowed
    assert not result.needs_hitl  # hard deny


# -- spec.tools NO LONGER auto-injected ------------------------------------

def test_spec_tools_not_auto_injected_into_allow():
    """Tools listed in spec.tools are NOT automatically permitted (new behavior)."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        tools=["Bash", "Read"],
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl  # triggers HITL, not hard deny


def test_spec_tools_in_deny_still_blocked():
    """spec.tools that are in deny list are denied (hard deny)."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[], deny=["Bash"]),
        tools=["Bash", "Read"],
        hitl_mode="never",
    )
    checker = _build(spec, _make_env())
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl  # hard deny


# -- bootstrap tools via system_tool_names ----------------------------------

def test_bootstrap_tools_allowed_via_system_tools():
    """enable_bootstrap tools are allowed when passed as system_tool_names."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        hitl_mode="never",
    )
    spec.enable_bootstrap = True
    checker = _build(spec, _make_env(), system_tool_names={"create_agent", "create_skill"})
    assert checker.check("create_agent", {}).allowed
    assert checker.check("create_skill", {}).allowed


def test_bootstrap_tools_not_in_system_tools_trigger_hitl():
    """Bootstrap tools not in system_tool_names trigger HITL."""
    spec = _make_spec(
        permissions=_make_permissions(allow=[]),
        hitl_mode="never",
    )
    spec.enable_bootstrap = False
    checker = _build(spec, _make_env())
    result = checker.check("create_agent", {})
    assert not result.allowed
    assert result.needs_hitl
