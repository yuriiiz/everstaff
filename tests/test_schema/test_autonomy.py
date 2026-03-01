import pytest
from everstaff.schema.autonomy import AutonomyConfig, TriggerConfig, GoalConfig


def test_trigger_config_cron():
    t = TriggerConfig(id="daily", type="cron", schedule="0 9 * * *", task="hello")
    assert t.overlap_policy == "skip"
    assert t.exclusive is False
    assert t.internal is False


def test_trigger_config_interval():
    t = TriggerConfig(id="check", type="interval", every=1800, task="check")
    assert t.every == 1800


def test_trigger_config_webhook():
    t = TriggerConfig(id="gh", type="webhook", path="/hooks/github", filter="issue.opened")
    assert t.path == "/hooks/github"


def test_trigger_config_event():
    t = TriggerConfig(id="lark", type="event", source="lark", filter="mention:@yuri")
    assert t.source == "lark"


def test_trigger_config_file_watch():
    t = TriggerConfig(id="fw", type="file_watch", paths=["/data/reports/"])
    assert t.paths == ["/data/reports/"]


def test_goal_config():
    g = GoalConfig(id="efficiency", description="improve", success_criteria="rate > 95%", priority="high")
    assert g.priority == "high"


def test_autonomy_config_defaults():
    a = AutonomyConfig()
    assert a.enabled is False
    assert a.level == "supervised"
    assert a.tick_interval == 3600
    assert a.max_instances == 1
    assert a.triggers == []
    assert a.goals == []


def test_autonomy_config_full():
    a = AutonomyConfig(
        enabled=True,
        level="autonomous",
        tick_interval=1800,
        max_instances=3,
        instance_strategy="parallel",
        think_model="fast",
        act_model="smart",
        triggers=[TriggerConfig(id="t1", type="cron", schedule="0 9 * * *", task="daily")],
        goals=[GoalConfig(id="g1", description="test", priority="high")],
    )
    assert a.level == "autonomous"
    assert len(a.triggers) == 1
    assert len(a.goals) == 1


def test_agent_spec_with_autonomy():
    from everstaff.schema.agent_spec import AgentSpec
    spec = AgentSpec(
        agent_name="Test",
        autonomy=AutonomyConfig(enabled=True, level="autonomous"),
    )
    assert spec.autonomy.enabled is True
