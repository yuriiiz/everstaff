"""Tests for AgentSpec schema."""

from everstaff.schema.agent_spec import AgentSpec, SubAgentSpec, KnowledgeSourceSpec


def test_minimal_agent_spec():
    spec = AgentSpec(agent_name="test")
    assert spec.agent_name == "test"
    assert spec.version == "0.1.0"
    assert spec.adviced_model_kind == "smart"
    assert spec.skills == []
    assert spec.sub_agents == {}


def test_full_agent_spec():
    spec = AgentSpec(
        agent_name="Test Agent",
        description="A test agent",
        version="2.0.0",
        adviced_model_kind="fast",
        instructions="You are a test agent.",
        skills=["find-skills"],
        knowledge_base=[
            KnowledgeSourceSpec(type="local_dir", path="./docs"),
        ],
        sub_agents={
            "helper": SubAgentSpec(
                description="A helper agent",
                instructions="Help with tasks.",
                adviced_model_kind="inherit",
                tools=["search"],
            ),
        },
        model_override=None,
        temperature=0.5,
        max_tokens=4096,
    )
    assert spec.agent_name == "Test Agent"
    assert spec.version == "2.0.0"
    assert len(spec.knowledge_base) == 1
    assert "helper" in spec.sub_agents
    assert spec.sub_agents["helper"].tools == ["search"]


def test_agent_spec_from_yaml_dict():
    """Test creating AgentSpec from a dict (as from YAML loading)."""
    data = {
        "agent_name": "YAML Agent",
        "description": "Loaded from YAML",
        "version": "1.0.0",
        "adviced_model_kind": "smart",
        "instructions": "Be helpful.",
        "skills": ["find-skills"],
        "knowledge_base": [],
    }
    spec = AgentSpec(**data)
    assert spec.agent_name == "YAML Agent"
    assert spec.skills == ["find-skills"]
