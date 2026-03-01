from everstaff.permissions.rule_checker import RuleBasedChecker


def test_global_deny_wins_over_agent_allow():
    from everstaff.permissions.chained import ChainedPermissionChecker
    global_checker = RuleBasedChecker(allow=[], deny=["DangerousTool"], require_approval=[], strict=False)
    agent_checker = RuleBasedChecker(allow=["DangerousTool", "SafeTool"], deny=[], require_approval=[])
    chained = ChainedPermissionChecker(global_checker, agent_checker)

    result = chained.check("DangerousTool", {})
    assert not result.allowed
    assert "deny" in result.reason.lower()


def test_global_require_approval_fires_before_agent_allow():
    from everstaff.permissions.chained import ChainedPermissionChecker
    global_checker = RuleBasedChecker(allow=[], deny=[], require_approval=["Bash"], strict=False)
    agent_checker = RuleBasedChecker(allow=["Bash"], deny=[], require_approval=[])
    chained = ChainedPermissionChecker(global_checker, agent_checker)

    result = chained.check("Bash", {})
    assert not result.allowed
    assert result.require_approval


def test_agent_rules_apply_when_global_passes():
    from everstaff.permissions.chained import ChainedPermissionChecker
    global_checker = RuleBasedChecker(allow=[], deny=[], require_approval=[], strict=False)
    agent_checker = RuleBasedChecker(allow=[], deny=["BlockedByAgent"], require_approval=[])
    chained = ChainedPermissionChecker(global_checker, agent_checker)

    result = chained.check("BlockedByAgent", {})
    assert not result.allowed


def test_allowed_when_both_pass():
    from everstaff.permissions.chained import ChainedPermissionChecker
    global_checker = RuleBasedChecker(allow=[], deny=[], require_approval=[], strict=False)
    agent_checker = RuleBasedChecker(allow=[], deny=[], require_approval=[], strict=False)
    chained = ChainedPermissionChecker(global_checker, agent_checker)

    result = chained.check("AnyTool", {})
    assert result.allowed
