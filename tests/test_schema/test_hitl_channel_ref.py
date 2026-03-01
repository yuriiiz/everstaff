def test_hitl_channel_ref_ref_only():
    from everstaff.schema.autonomy import HitlChannelRef
    ref = HitlChannelRef(ref="lark-main")
    assert ref.ref == "lark-main"
    assert ref.overrides() == {}


def test_hitl_channel_ref_with_overrides():
    from everstaff.schema.autonomy import HitlChannelRef
    ref = HitlChannelRef(ref="lark-main", chat_id="oc_other", bot_name="MyBot")
    assert ref.ref == "lark-main"
    assert ref.overrides() == {"chat_id": "oc_other", "bot_name": "MyBot"}


def test_trigger_config_hitl_channels_default_none():
    from everstaff.schema.autonomy import TriggerConfig
    t = TriggerConfig(id="t1", type="cron", schedule="* * * * *", task="do it")
    assert t.hitl_channels is None


def test_trigger_config_hitl_channels_parsed():
    from everstaff.schema.autonomy import TriggerConfig
    t = TriggerConfig(
        id="t1", type="cron", schedule="* * * * *", task="do it",
        hitl_channels=[{"ref": "lark-main", "chat_id": "oc_x"}],
    )
    assert len(t.hitl_channels) == 1
    assert t.hitl_channels[0].ref == "lark-main"
    assert t.hitl_channels[0].overrides() == {"chat_id": "oc_x"}


def test_agent_spec_hitl_channels_default_empty():
    from everstaff.schema.agent_spec import AgentSpec
    spec = AgentSpec(agent_name="test")
    assert spec.hitl_channels == []


def test_agent_spec_hitl_channels_parsed():
    from everstaff.schema.agent_spec import AgentSpec
    spec = AgentSpec(
        agent_name="test",
        hitl_channels=[{"ref": "lark-main"}, {"ref": "webhook"}],
    )
    assert len(spec.hitl_channels) == 2
    assert spec.hitl_channels[0].ref == "lark-main"
