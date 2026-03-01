def test_framework_config_has_permissions_field():
    from everstaff.core.config import FrameworkConfig
    from everstaff.permissions import PermissionConfig
    cfg = FrameworkConfig()
    assert isinstance(cfg.permissions, PermissionConfig)
    assert cfg.permissions.deny == []
    assert cfg.permissions.require_approval == []


def test_build_permissions_no_global_rules_returns_agent_checker():
    """When global has no rules, returns agent's checker directly (no chaining)."""
    from unittest.mock import MagicMock
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.permissions import PermissionConfig
    from everstaff.permissions.rule_checker import RuleBasedChecker
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping

    spec = AgentSpec(
        agent_name="TestAgent",
        permissions=PermissionConfig(allow=["SafeTool"], deny=[], require_approval=[]),
    )
    cfg = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="fake/m")},
        # No global permissions set — defaults to empty
    )
    mock_env = MagicMock()
    mock_env.config = cfg
    builder = AgentBuilder(spec=spec, env=mock_env)
    checker = builder._build_permissions()

    # SafeTool is allowed (in agent's allow list)
    result = checker.check("SafeTool", {})
    assert result.allowed

    # OtherTool is not in agent allow list — should be blocked
    result = checker.check("OtherTool", {})
    assert not result.allowed


def test_build_permissions_global_deny_wins():
    """Global deny blocks even when agent allow list includes the tool."""
    from unittest.mock import MagicMock
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.permissions import PermissionConfig
    from everstaff.permissions.chained import ChainedPermissionChecker
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping

    spec = AgentSpec(
        agent_name="TestAgent",
        permissions=PermissionConfig(allow=["BlockedGlobally", "SafeTool"], deny=[], require_approval=[]),
    )
    cfg = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="fake/m")},
        permissions=PermissionConfig(deny=["BlockedGlobally"], require_approval=["Bash"]),
    )
    mock_env = MagicMock()
    mock_env.config = cfg
    builder = AgentBuilder(spec=spec, env=mock_env)
    checker = builder._build_permissions()
    assert isinstance(checker, ChainedPermissionChecker)

    # Global deny wins
    result = checker.check("BlockedGlobally", {})
    assert not result.allowed

    # Global require_approval fires
    result = checker.check("Bash", {})
    assert result.require_approval

    # SafeTool still works (allowed by agent, not blocked globally)
    result = checker.check("SafeTool", {})
    assert result.allowed
