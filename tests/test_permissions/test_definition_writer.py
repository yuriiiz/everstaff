"""Test AgentDefinitionWriter -- writes permanent grants back to agent YAML."""
import pytest
import yaml


@pytest.fixture
def agent_yaml(tmp_path):
    path = tmp_path / "TestAgent.yaml"
    path.write_text(yaml.dump({
        "agent_name": "TestAgent",
        "tools": ["Bash", "Read"],
        "permissions": {
            "allow": ["Read"],
            "deny": [],
        },
    }))
    return path


@pytest.mark.asyncio
async def test_yaml_writer_adds_allow_permission(agent_yaml):
    from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
    writer = YamlAgentDefinitionWriter(agents_dir=str(agent_yaml.parent))
    await writer.add_allow_permission("TestAgent", "Bash")

    data = yaml.safe_load(agent_yaml.read_text())
    assert "Bash" in data["permissions"]["allow"]
    assert "Read" in data["permissions"]["allow"]


@pytest.mark.asyncio
async def test_yaml_writer_no_duplicate(agent_yaml):
    from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
    writer = YamlAgentDefinitionWriter(agents_dir=str(agent_yaml.parent))
    await writer.add_allow_permission("TestAgent", "Read")

    data = yaml.safe_load(agent_yaml.read_text())
    assert data["permissions"]["allow"].count("Read") == 1


@pytest.mark.asyncio
async def test_yaml_writer_creates_permissions_section(tmp_path):
    path = tmp_path / "SimpleAgent.yaml"
    path.write_text(yaml.dump({
        "agent_name": "SimpleAgent",
        "tools": ["Bash"],
    }))
    from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
    writer = YamlAgentDefinitionWriter(agents_dir=str(tmp_path))
    await writer.add_allow_permission("SimpleAgent", "Bash")

    data = yaml.safe_load(path.read_text())
    assert data["permissions"]["allow"] == ["Bash"]


@pytest.mark.asyncio
async def test_yaml_writer_nonexistent_agent(tmp_path):
    from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
    writer = YamlAgentDefinitionWriter(agents_dir=str(tmp_path))
    # Should not raise, just log warning
    await writer.add_allow_permission("NonExistent", "Bash")
