"""Tests for mutation tool provider."""
import pytest
from everstaff.daemon.mutation_tool_provider import MutationToolProvider


def test_provider_returns_tool_definitions():
    provider = MutationToolProvider(
        agent_name="bot",
        agent_yaml_path="/tmp/bot.yaml",
        daemon_reload_fn=lambda: None,
    )
    tools = provider.get_tools()
    names = [t.name for t in tools]
    assert "update_agent_skills" in names
    assert "update_agent_mcp" in names
    assert "update_agent_instructions" in names
    assert "update_agent_triggers" in names


def test_provider_does_not_expose_permission_tools():
    provider = MutationToolProvider(
        agent_name="bot",
        agent_yaml_path="/tmp/bot.yaml",
        daemon_reload_fn=lambda: None,
    )
    tools = provider.get_tools()
    names = [t.name for t in tools]
    assert "update_agent_permissions" not in names
