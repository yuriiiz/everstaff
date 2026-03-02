"""Test AgentBuilder permission wiring with DynamicPermissionChecker."""
from unittest.mock import MagicMock

from everstaff.builder.agent_builder import AgentBuilder
from everstaff.schema.agent_spec import AgentSpec
from everstaff.permissions import PermissionConfig
from everstaff.permissions.dynamic_checker import DynamicPermissionChecker
from everstaff.core.config import FrameworkConfig
from everstaff.schema.model_config import ModelMapping


def _make_builder(agent_allow=None, agent_deny=None, global_allow=None, global_deny=None, tools=None):
    spec = AgentSpec(
        agent_name="TestAgent",
        tools=tools or [],
        permissions=PermissionConfig(allow=agent_allow or [], deny=agent_deny or []),
    )
    cfg = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="fake/m")},
        permissions=PermissionConfig(allow=global_allow or [], deny=global_deny or []),
    )
    mock_env = MagicMock()
    mock_env.config = cfg
    return AgentBuilder(spec=spec, env=mock_env)


def test_returns_dynamic_checker():
    builder = _make_builder(agent_allow=["Read"])
    checker = builder._build_permissions(system_tool_names=set())
    assert isinstance(checker, DynamicPermissionChecker)


def test_spec_tools_not_auto_allowed():
    """Tools in spec.tools should NOT be auto-injected into allow."""
    builder = _make_builder(tools=["Bash", "Read"])
    checker = builder._build_permissions(system_tool_names=set())
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl


def test_explicit_allow_permits():
    builder = _make_builder(agent_allow=["Read"], tools=["Read", "Bash"])
    checker = builder._build_permissions(system_tool_names=set())
    assert checker.check("Read", {}).allowed
    assert checker.check("Bash", {}).needs_hitl


def test_global_deny_wins():
    builder = _make_builder(agent_allow=["Bash"], global_deny=["Bash"])
    checker = builder._build_permissions(system_tool_names=set())
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl


def test_global_allow_union():
    builder = _make_builder(global_allow=["Read"], agent_allow=["Glob"])
    checker = builder._build_permissions(system_tool_names=set())
    assert checker.check("Read", {}).allowed
    assert checker.check("Glob", {}).allowed


def test_system_tools_always_allowed():
    builder = _make_builder()
    checker = builder._build_permissions(system_tool_names={"request_human_input"})
    assert checker.check("request_human_input", {}).allowed


def test_session_grants_loaded():
    builder = _make_builder()
    checker = builder._build_permissions(
        system_tool_names=set(),
        session_grants=["Bash"],
    )
    assert checker.check("Bash", {}).allowed


def test_framework_config_has_permissions_field():
    cfg = FrameworkConfig()
    assert isinstance(cfg.permissions, PermissionConfig)
    assert cfg.permissions.deny == []
