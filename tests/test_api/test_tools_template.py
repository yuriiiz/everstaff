"""Tests for tool creation template and validation."""
import pytest
from httpx import AsyncClient, ASGITransport
from everstaff.core.config import FrameworkConfig
from everstaff.api import create_app


def _make_app(tmp_path):
    config = FrameworkConfig(
        sessions_dir=str(tmp_path),
        tools_dirs=[str(tmp_path / "tools")],
    )
    return create_app(config=config, sessions_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_create_tool_uses_decorator_template(tmp_path):
    """POST /tools must generate @tool decorator style, not class style."""
    app = _make_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/tools", json={"name": "my_tool"})

    assert resp.status_code == 201

    tool_file = tmp_path / "tools" / "my_tool.py"
    assert tool_file.exists()
    content = tool_file.read_text()

    # Must use decorator style
    assert "@tool(" in content
    assert "from everstaff.tools.native import tool" in content
    assert "TOOLS = [my_tool]" in content

    # Must NOT use old class style
    assert "class My_toolTool" not in content
    assert "ToolDefinition" not in content
    assert "async def execute" not in content


@pytest.mark.asyncio
async def test_create_tool_with_custom_content(tmp_path):
    """POST /tools with content uses provided content verbatim (if valid)."""
    app = _make_app(tmp_path)

    custom = '"""custom"""\nTOOLS = []\n'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/tools", json={"name": "custom_tool", "content": custom})

    assert resp.status_code == 201
    tool_file = tmp_path / "tools" / "custom_tool.py"
    assert tool_file.read_text() == custom


@pytest.mark.asyncio
async def test_create_tool_invalid_syntax_returns_400(tmp_path):
    """POST /tools with syntax error in content must return 400."""
    app = _make_app(tmp_path)

    bad_content = "def foo(\n  # unclosed paren\n"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/tools", json={"name": "bad_tool", "content": bad_content})

    assert resp.status_code == 400
    # File must NOT have been created
    assert not (tmp_path / "tools" / "bad_tool.py").exists()


@pytest.mark.asyncio
async def test_create_tool_missing_tools_variable_returns_400(tmp_path):
    """POST /tools with valid Python but no TOOLS variable must return 400."""
    app = _make_app(tmp_path)

    no_tools = 'def my_func():\n    return "hello"\n'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/tools", json={"name": "no_tools", "content": no_tools})

    assert resp.status_code == 400
    assert not (tmp_path / "tools" / "no_tools.py").exists()


@pytest.mark.asyncio
async def test_create_tool_load_error_returns_400(tmp_path):
    """POST /tools with valid syntax but exec error must return 400."""
    app = _make_app(tmp_path)

    bad_import = "import nonexistent_module_xyz_abc\nTOOLS = []\n"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/tools", json={"name": "bad_import_tool", "content": bad_import})

    assert resp.status_code == 400
    assert not (tmp_path / "tools" / "bad_import_tool.py").exists()


@pytest.mark.asyncio
async def test_update_tool_invalid_content_returns_400(tmp_path):
    """PUT /tools/{name} with invalid content must return 400."""
    app = _make_app(tmp_path)

    # First create a valid tool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/tools", json={"name": "valid_tool"})
        assert resp.status_code == 201

        # Then try to update it with invalid content
        resp = await client.put("/api/tools/valid_tool", json={"content": "def bad(\n"})
        assert resp.status_code == 400

    # Original file should still exist (not overwritten with bad content)
    assert (tmp_path / "tools" / "valid_tool.py").exists()
