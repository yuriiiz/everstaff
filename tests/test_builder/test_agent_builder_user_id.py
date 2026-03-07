"""Tests for user_id injection into AgentBuilder mem0 scope."""
from unittest.mock import MagicMock


class TestAgentBuilderUserId:
    def test_accepts_user_id_param(self):
        from everstaff.builder.agent_builder import AgentBuilder
        from everstaff.schema.agent_spec import AgentSpec

        spec = AgentSpec(agent_name="test", uuid="test-uuid")
        env = MagicMock()
        env.config.memory.enabled = True

        builder = AgentBuilder(spec, env, user_id="alice")
        assert builder._user_id == "alice"

    def test_user_id_defaults_to_none(self):
        from everstaff.builder.agent_builder import AgentBuilder
        from everstaff.schema.agent_spec import AgentSpec

        spec = AgentSpec(agent_name="test", uuid="test-uuid")
        env = MagicMock()

        builder = AgentBuilder(spec, env)
        assert builder._user_id is None
