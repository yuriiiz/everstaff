"""Test that session grants are loaded from session.json on session resume."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from everstaff.builder.agent_builder import AgentBuilder
from everstaff.schema.agent_spec import AgentSpec
from everstaff.permissions import PermissionConfig
from everstaff.permissions.dynamic_checker import DynamicPermissionChecker


@pytest.mark.asyncio
async def test_load_session_grants_from_file_store():
    spec = AgentSpec(agent_name="TestAgent", tools=["Bash"])

    mock_file_store = AsyncMock()
    session_data = json.dumps({
        "session_id": "sess-123",
        "extra_permissions": ["Bash", "Write"],
    }).encode()
    mock_file_store.read = AsyncMock(return_value=session_data)
    mock_file_store.exists = AsyncMock(return_value=True)

    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping
    mock_env = MagicMock()
    mock_env.config = FrameworkConfig(model_mappings={"smart": ModelMapping(model_id="fake/m")})

    builder = AgentBuilder(spec=spec, env=mock_env, session_id="sess-123")
    grants = await builder._load_session_grants(mock_file_store)
    assert grants == ["Bash", "Write"]


@pytest.mark.asyncio
async def test_load_session_grants_no_session_id():
    spec = AgentSpec(agent_name="TestAgent")
    mock_env = MagicMock()
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping
    mock_env.config = FrameworkConfig(model_mappings={"smart": ModelMapping(model_id="fake/m")})

    builder = AgentBuilder(spec=spec, env=mock_env)  # no session_id
    grants = await builder._load_session_grants(None)
    assert grants == []


@pytest.mark.asyncio
async def test_load_session_grants_file_not_found():
    spec = AgentSpec(agent_name="TestAgent")
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping
    mock_env = MagicMock()
    mock_env.config = FrameworkConfig(model_mappings={"smart": ModelMapping(model_id="fake/m")})

    mock_file_store = AsyncMock()
    mock_file_store.exists = AsyncMock(return_value=False)

    builder = AgentBuilder(spec=spec, env=mock_env, session_id="sess-999")
    grants = await builder._load_session_grants(mock_file_store)
    assert grants == []


@pytest.mark.asyncio
async def test_session_grants_used_in_permissions():
    spec = AgentSpec(agent_name="TestAgent", tools=["Bash"])
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping
    mock_env = MagicMock()
    mock_env.config = FrameworkConfig(model_mappings={"smart": ModelMapping(model_id="fake/m")})

    builder = AgentBuilder(spec=spec, env=mock_env)
    checker = builder._build_permissions(
        system_tool_names=set(),
        session_grants=["Bash"],
    )
    assert isinstance(checker, DynamicPermissionChecker)
    assert checker.check("Bash", {}).allowed
