"""Tests for the MCP management API router."""
import asyncio
import pytest
import yaml
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from pathlib import Path

from everstaff.core.config import FrameworkConfig
from everstaff.api import create_app
from everstaff.protocols import ToolDefinition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dirs(tmp_path):
    """Create standard temp directories for testing."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    return {
        "agents": agents_dir,
        "templates": templates_dir,
        "sessions": sessions_dir,
        "root": tmp_path,
    }


@pytest.fixture
def app(tmp_dirs):
    agents_dir = tmp_dirs["agents"]
    templates_dir = tmp_dirs["templates"]
    sessions_dir = tmp_dirs["sessions"]

    # Create a test template
    (templates_dir / "test-server.yaml").write_text(yaml.dump({
        "name": "test-server",
        "display_name": "Test Server",
        "description": "A test",
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "test_server"],
    }))

    # Create a test agent
    (agents_dir / "my-agent.yaml").write_text(yaml.dump({
        "agent_name": "my-agent",
        "instructions": "test",
        "mcp_servers": [],
    }, sort_keys=False))

    config = FrameworkConfig(
        agents_dir=str(agents_dir),
        mcp_templates_dirs=[str(templates_dir)],
        sessions_dir=str(sessions_dir),
    )
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------

def test_list_templates(client):
    """GET /mcp/templates returns all templates."""
    resp = client.get("/api/mcp/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    names = [t["name"] for t in data]
    assert "test-server" in names


def test_list_templates_include_source(client):
    """GET /mcp/templates includes a source field."""
    resp = client.get("/api/mcp/templates")
    assert resp.status_code == 200
    data = resp.json()
    for item in data:
        assert "source" in item


def test_get_template(client):
    """GET /mcp/templates/{name} returns a specific template."""
    resp = client.get("/api/mcp/templates/test-server")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test-server"
    assert data["display_name"] == "Test Server"
    assert data["command"] == "python"


def test_get_template_not_found(client):
    """GET /mcp/templates/{name} returns 404 for unknown template."""
    resp = client.get("/api/mcp/templates/nonexistent")
    assert resp.status_code == 404


def test_create_template(client, tmp_dirs):
    """POST /mcp/templates creates a new template."""
    resp = client.post("/api/mcp/templates", json={
        "name": "new-tpl",
        "display_name": "New Template",
        "transport": "stdio",
        "command": "echo",
        "args": ["hi"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "new-tpl"

    # Verify it appears in listing
    resp2 = client.get("/api/mcp/templates")
    names = [t["name"] for t in resp2.json()]
    assert "new-tpl" in names


def test_create_template_duplicate(client):
    """POST /mcp/templates returns 409 for duplicate name."""
    resp = client.post("/api/mcp/templates", json={
        "name": "test-server",
        "transport": "stdio",
        "command": "echo",
    })
    assert resp.status_code == 409


def test_update_template(client):
    """PUT /mcp/templates/{name} updates an existing template."""
    resp = client.put("/api/mcp/templates/test-server", json={
        "display_name": "Updated Server",
        "command": "node",
    })
    assert resp.status_code == 200
    assert resp.json()["updated"] is True

    # Verify update took effect
    resp2 = client.get("/api/mcp/templates/test-server")
    data = resp2.json()
    assert data["display_name"] == "Updated Server"
    assert data["command"] == "node"


def test_update_template_not_found(client):
    """PUT /mcp/templates/{name} returns 404 for unknown template."""
    resp = client.put("/api/mcp/templates/nonexistent", json={
        "display_name": "X",
        "command": "echo",
    })
    assert resp.status_code == 404


def test_delete_template(client, tmp_dirs):
    """DELETE /mcp/templates/{name} removes a user template."""
    # Create one first, then delete it
    client.post("/api/mcp/templates", json={
        "name": "to-delete",
        "transport": "stdio",
        "command": "echo",
    })
    resp = client.delete("/api/mcp/templates/to-delete")
    assert resp.status_code == 204

    # Verify it's gone
    resp2 = client.get("/api/mcp/templates/to-delete")
    assert resp2.status_code == 404


def test_delete_template_not_found(client):
    """DELETE /mcp/templates/{name} returns 404 for unknown template."""
    resp = client.delete("/api/mcp/templates/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Per-agent MCP server endpoints
# ---------------------------------------------------------------------------

def test_list_agent_mcp_servers(client):
    """GET /agents/{name}/mcp-servers returns empty list for fresh agent."""
    resp = client.get("/api/agents/my-agent/mcp-servers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_add_mcp_server_to_agent(client):
    """POST /agents/{name}/mcp-servers adds a server to the agent."""
    resp = client.post("/api/agents/my-agent/mcp-servers", json={
        "name": "my-server",
        "transport": "stdio",
        "command": "echo",
        "args": ["hello"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-server"
    assert data["agent"] == "my-agent"

    # Verify it's in the list
    resp2 = client.get("/api/agents/my-agent/mcp-servers")
    servers = resp2.json()
    assert len(servers) == 1
    assert servers[0]["name"] == "my-server"
    assert servers[0]["command"] == "echo"


def test_add_mcp_server_from_template(client):
    """POST /agents/{name}/mcp-servers with template field installs from template."""
    resp = client.post("/api/agents/my-agent/mcp-servers", json={
        "template": "test-server",
        "env": {"EXTRA": "val"},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-server"

    # Verify server was added with template values
    resp2 = client.get("/api/agents/my-agent/mcp-servers")
    servers = resp2.json()
    assert len(servers) == 1
    assert servers[0]["command"] == "python"
    assert servers[0]["args"] == ["-m", "test_server"]
    assert servers[0]["env"]["EXTRA"] == "val"


def test_add_mcp_server_from_template_not_found(client):
    """POST /agents/{name}/mcp-servers returns 404 for unknown template."""
    resp = client.post("/api/agents/my-agent/mcp-servers", json={
        "template": "nonexistent-template",
    })
    assert resp.status_code == 404


def test_add_duplicate_mcp_server(client):
    """POST /agents/{name}/mcp-servers returns 409 for duplicate server name."""
    client.post("/api/agents/my-agent/mcp-servers", json={
        "name": "dup-server",
        "transport": "stdio",
        "command": "echo",
    })
    resp = client.post("/api/agents/my-agent/mcp-servers", json={
        "name": "dup-server",
        "transport": "stdio",
        "command": "echo",
    })
    assert resp.status_code == 409


def test_add_mcp_server_no_name_no_template(client):
    """POST /agents/{name}/mcp-servers returns 400 when name and template are both missing."""
    resp = client.post("/api/agents/my-agent/mcp-servers", json={
        "transport": "stdio",
        "command": "echo",
    })
    assert resp.status_code == 400


def test_update_mcp_server(client):
    """PUT /agents/{name}/mcp-servers/{server} updates a server."""
    # Add first
    client.post("/api/agents/my-agent/mcp-servers", json={
        "name": "updatable",
        "transport": "stdio",
        "command": "echo",
    })

    # Update
    resp = client.put("/api/agents/my-agent/mcp-servers/updatable", json={
        "name": "updatable",
        "transport": "stdio",
        "command": "node",
        "args": ["server.js"],
    })
    assert resp.status_code == 200
    assert resp.json()["updated"] is True

    # Verify update
    resp2 = client.get("/api/agents/my-agent/mcp-servers")
    servers = resp2.json()
    srv = [s for s in servers if s["name"] == "updatable"][0]
    assert srv["command"] == "node"
    assert srv["args"] == ["server.js"]


def test_update_mcp_server_not_found(client):
    """PUT /agents/{name}/mcp-servers/{server} returns 404 for unknown server."""
    resp = client.put("/api/agents/my-agent/mcp-servers/nonexistent", json={
        "name": "nonexistent",
        "transport": "stdio",
        "command": "echo",
    })
    assert resp.status_code == 404


def test_delete_mcp_server(client):
    """DELETE /agents/{name}/mcp-servers/{server} removes a server."""
    # Add first
    client.post("/api/agents/my-agent/mcp-servers", json={
        "name": "to-remove",
        "transport": "stdio",
        "command": "echo",
    })

    resp = client.delete("/api/agents/my-agent/mcp-servers/to-remove")
    assert resp.status_code == 204

    # Verify it's gone
    resp2 = client.get("/api/agents/my-agent/mcp-servers")
    names = [s["name"] for s in resp2.json()]
    assert "to-remove" not in names


def test_delete_mcp_server_not_found(client):
    """DELETE /agents/{name}/mcp-servers/{server} returns 404 for unknown server."""
    resp = client.delete("/api/agents/my-agent/mcp-servers/nonexistent")
    assert resp.status_code == 404


def test_agent_not_found(client):
    """Per-agent endpoints return 404 for unknown agent."""
    resp = client.get("/api/agents/no-such-agent/mcp-servers")
    assert resp.status_code == 404

    resp2 = client.post("/api/agents/no-such-agent/mcp-servers", json={
        "name": "x", "transport": "stdio", "command": "echo",
    })
    assert resp2.status_code == 404

    resp3 = client.put("/api/agents/no-such-agent/mcp-servers/x", json={
        "name": "x", "transport": "stdio", "command": "echo",
    })
    assert resp3.status_code == 404

    resp4 = client.delete("/api/agents/no-such-agent/mcp-servers/x")
    assert resp4.status_code == 404


# ---------------------------------------------------------------------------
# Connection test endpoint
# ---------------------------------------------------------------------------

def test_test_connection_success(client):
    """POST /mcp/test returns discovered tools on successful connection."""
    # Build mock MCPTool objects with .definition.name / .definition.description
    mock_tool_1 = MagicMock()
    mock_tool_1.definition = ToolDefinition(
        name="read_file", description="Read a file", parameters={}
    )
    mock_tool_2 = MagicMock()
    mock_tool_2.definition = ToolDefinition(
        name="write_file", description="Write a file", parameters={}
    )

    mock_conn_instance = MagicMock()
    mock_conn_instance.connect = AsyncMock(return_value=[mock_tool_1, mock_tool_2])
    mock_conn_instance.disconnect = AsyncMock()

    with patch(
        "everstaff.mcp_client.connection.MCPConnection",
        return_value=mock_conn_instance,
    ):
        resp = client.post("/api/mcp/test", json={
            "name": "my-server",
            "transport": "stdio",
            "command": "echo",
            "args": ["hello"],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["tools"]) == 2
    assert data["tools"][0]["name"] == "read_file"
    assert data["tools"][0]["description"] == "Read a file"
    assert data["tools"][1]["name"] == "write_file"

    # Verify disconnect was called
    mock_conn_instance.disconnect.assert_awaited_once()


def test_test_connection_failure(client):
    """POST /mcp/test returns 502 when the MCP server connection fails."""
    mock_conn_instance = MagicMock()
    mock_conn_instance.connect = AsyncMock(
        side_effect=ConnectionRefusedError("Connection refused")
    )
    mock_conn_instance.disconnect = AsyncMock()

    with patch(
        "everstaff.mcp_client.connection.MCPConnection",
        return_value=mock_conn_instance,
    ):
        resp = client.post("/api/mcp/test", json={
            "name": "bad-server",
            "transport": "stdio",
            "command": "nonexistent-binary",
        })

    assert resp.status_code == 502
    data = resp.json()
    assert "Connection failed" in data["error"]

    # Verify disconnect was called even on failure
    mock_conn_instance.disconnect.assert_awaited_once()


def test_test_connection_timeout(client):
    """POST /mcp/test returns 504 when the connection times out."""
    mock_conn_instance = MagicMock()
    mock_conn_instance.connect = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_conn_instance.disconnect = AsyncMock()

    with patch(
        "everstaff.mcp_client.connection.MCPConnection",
        return_value=mock_conn_instance,
    ):
        resp = client.post("/api/mcp/test", json={
            "name": "slow-server",
            "transport": "stdio",
            "command": "sleep",
            "args": ["999"],
        })

    assert resp.status_code == 504
    data = resp.json()
    assert "timed out" in data["error"].lower()
    mock_conn_instance.disconnect.assert_awaited_once()


def test_test_connection_includes_tool_count(client):
    """POST /mcp/test response includes tool_count field."""
    mock_tool = MagicMock()
    mock_tool.definition = ToolDefinition(
        name="tool1", description="A tool", parameters={}
    )
    mock_conn_instance = MagicMock()
    mock_conn_instance.connect = AsyncMock(return_value=[mock_tool])
    mock_conn_instance.disconnect = AsyncMock()

    with patch(
        "everstaff.mcp_client.connection.MCPConnection",
        return_value=mock_conn_instance,
    ):
        resp = client.post("/api/mcp/test", json={
            "name": "tc-server",
            "transport": "stdio",
            "command": "echo",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_count"] == 1
