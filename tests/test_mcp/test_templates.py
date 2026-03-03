"""Tests for MCP template model and manager."""
import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_template_yaml(directory, name, **overrides):
    """Write a minimal template YAML file into *directory* and return the path."""
    data = {"name": name, "command": "echo", "args": ["hello"], **overrides}
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# MCPTemplate model tests
# ---------------------------------------------------------------------------

def test_template_model_from_dict():
    """Construct MCPTemplate from a plain dict."""
    from everstaff.mcp_client.templates import MCPTemplate

    data = {
        "name": "test-server",
        "display_name": "Test Server",
        "description": "A test server",
        "icon": "test",
        "category": "testing",
        "transport": "stdio",
        "command": "echo",
        "args": ["hello"],
        "env": {"FOO": "bar"},
        "required_env": [
            {"key": "SECRET", "label": "Secret Key", "description": "A secret", "secret": True}
        ],
    }

    tpl = MCPTemplate(**data)

    assert tpl.name == "test-server"
    assert tpl.display_name == "Test Server"
    assert tpl.description == "A test server"
    assert tpl.icon == "test"
    assert tpl.category == "testing"
    assert tpl.transport == "stdio"
    assert tpl.command == "echo"
    assert tpl.args == ["hello"]
    assert tpl.env == {"FOO": "bar"}
    assert len(tpl.required_env) == 1
    assert tpl.required_env[0].key == "SECRET"
    assert tpl.required_env[0].secret is True


def test_template_model_defaults():
    """MCPTemplate uses sensible defaults for optional fields."""
    from everstaff.mcp_client.templates import MCPTemplate

    tpl = MCPTemplate(name="minimal")

    assert tpl.display_name == ""
    assert tpl.category == "general"
    assert tpl.transport == "stdio"
    assert tpl.command is None
    assert tpl.args == []
    assert tpl.env == {}
    assert tpl.url is None
    assert tpl.headers == {}
    assert tpl.required_env == []


def test_template_to_mcp_server_spec():
    """to_server_spec() creates an MCPServerSpec with merged env overrides."""
    from everstaff.mcp_client.templates import MCPTemplate

    tpl = MCPTemplate(
        name="gh",
        command="npx",
        args=["-y", "@mcp/server-github"],
        env={"TOKEN": ""},
        transport="stdio",
    )

    spec = tpl.to_server_spec(env_overrides={"TOKEN": "ghp_abc123"})

    assert spec.name == "gh"
    assert spec.command == "npx"
    assert spec.args == ["-y", "@mcp/server-github"]
    assert spec.env == {"TOKEN": "ghp_abc123"}
    assert spec.transport == "stdio"


def test_template_to_mcp_server_spec_no_overrides():
    """to_server_spec() without overrides keeps original env."""
    from everstaff.mcp_client.templates import MCPTemplate

    tpl = MCPTemplate(name="test", command="echo", env={"A": "1"})
    spec = tpl.to_server_spec()

    assert spec.env == {"A": "1"}


def test_template_to_mcp_server_spec_sse():
    """to_server_spec() works for SSE transport with url and headers."""
    from everstaff.mcp_client.templates import MCPTemplate

    tpl = MCPTemplate(
        name="remote",
        transport="sse",
        url="http://localhost:8080/sse",
        headers={"Authorization": "Bearer tok"},
    )

    spec = tpl.to_server_spec()

    assert spec.transport == "sse"
    assert spec.url == "http://localhost:8080/sse"
    assert spec.headers == {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------------------
# MCPTemplateManager tests
# ---------------------------------------------------------------------------

def test_template_manager_discovers_from_dirs(tmp_path):
    """Manager scans directories and finds template YAML files."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    d = tmp_path / "templates"
    d.mkdir()
    _write_template_yaml(d, "alpha", display_name="Alpha")
    _write_template_yaml(d, "beta", display_name="Beta")

    mgr = MCPTemplateManager(template_dirs=[str(d)])
    templates = mgr.list()

    names = {t.name for t in templates}
    assert names == {"alpha", "beta"}


def test_template_manager_user_overrides_builtin(tmp_path):
    """First-dir-wins: user dir templates shadow builtin dir templates."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()

    _write_template_yaml(user_dir, "shared", display_name="User Version")
    _write_template_yaml(builtin_dir, "shared", display_name="Builtin Version")

    # user_dir listed first -> user version wins
    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir), str(builtin_dir)],
        user_dir=str(user_dir),
    )
    templates = mgr.list()

    assert len(templates) == 1
    assert templates[0].display_name == "User Version"


def test_template_manager_get(tmp_path):
    """get() returns the correct template by name."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    d = tmp_path / "templates"
    d.mkdir()
    _write_template_yaml(d, "target", display_name="The Target")

    mgr = MCPTemplateManager(template_dirs=[str(d)])
    tpl = mgr.get("target")

    assert tpl.name == "target"
    assert tpl.display_name == "The Target"


def test_template_manager_get_not_found(tmp_path):
    """get() raises FileNotFoundError for unknown templates."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    d = tmp_path / "templates"
    d.mkdir()

    mgr = MCPTemplateManager(template_dirs=[str(d)])

    with pytest.raises(FileNotFoundError, match="not found"):
        mgr.get("nonexistent")


def test_template_manager_create(tmp_path):
    """create() writes a new template YAML into user_dir."""
    from everstaff.mcp_client.templates import MCPTemplate, MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()

    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir)],
        user_dir=str(user_dir),
    )

    tpl = MCPTemplate(name="new-server", command="python", args=["-m", "server"])
    path = mgr.create(tpl)

    assert path.exists()
    assert path.parent == user_dir
    assert path.name == "new-server.yaml"

    # Should be discoverable now
    found = mgr.get("new-server")
    assert found.name == "new-server"
    assert found.command == "python"


def test_template_manager_create_duplicate(tmp_path):
    """create() raises FileExistsError if template name already exists."""
    from everstaff.mcp_client.templates import MCPTemplate, MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    _write_template_yaml(user_dir, "dup")

    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir)],
        user_dir=str(user_dir),
    )

    tpl = MCPTemplate(name="dup", command="echo")

    with pytest.raises(FileExistsError, match="already exists"):
        mgr.create(tpl)


def test_template_manager_update(tmp_path):
    """update() modifies an existing user template in place."""
    from everstaff.mcp_client.templates import MCPTemplate, MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    _write_template_yaml(user_dir, "editable", display_name="Original")

    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir)],
        user_dir=str(user_dir),
    )

    updated = MCPTemplate(name="editable", command="echo", display_name="Updated")
    mgr.update("editable", updated)

    result = mgr.get("editable")
    assert result.display_name == "Updated"


def test_template_manager_update_builtin_creates_shadow(tmp_path):
    """update() on a builtin creates a shadow copy in user_dir."""
    from everstaff.mcp_client.templates import MCPTemplate, MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()

    _write_template_yaml(builtin_dir, "builtin-tpl", display_name="Builtin Original")

    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir), str(builtin_dir)],
        user_dir=str(user_dir),
    )

    updated = MCPTemplate(name="builtin-tpl", command="echo", display_name="User Override")
    mgr.update("builtin-tpl", updated)

    # Shadow copy should exist in user_dir
    shadow = user_dir / "builtin-tpl.yaml"
    assert shadow.exists()

    # Re-fetch should get the user version (user_dir listed first)
    result = mgr.get("builtin-tpl")
    assert result.display_name == "User Override"


def test_template_manager_delete(tmp_path):
    """delete() removes a user template file."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    path = _write_template_yaml(user_dir, "removable")

    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir)],
        user_dir=str(user_dir),
    )

    assert path.exists()
    mgr.delete("removable")
    assert not path.exists()

    with pytest.raises(FileNotFoundError):
        mgr.get("removable")


def test_template_manager_delete_builtin_raises(tmp_path):
    """delete() refuses to delete a builtin template with PermissionError."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()

    _write_template_yaml(builtin_dir, "protected")

    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir), str(builtin_dir)],
        user_dir=str(user_dir),
    )

    with pytest.raises(PermissionError, match="Cannot delete builtin"):
        mgr.delete("protected")


def test_template_list_includes_source(tmp_path):
    """list_with_source() includes 'builtin' and 'user' source labels."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()

    _write_template_yaml(user_dir, "user-tpl", display_name="User Template")
    _write_template_yaml(builtin_dir, "builtin-tpl", display_name="Builtin Template")

    mgr = MCPTemplateManager(
        template_dirs=[str(user_dir), str(builtin_dir)],
        user_dir=str(user_dir),
    )

    items = mgr.list_with_source()
    by_name = {item["template"].name: item["source"] for item in items}

    assert by_name["user-tpl"] == "user"
    assert by_name["builtin-tpl"] == "builtin"


def test_template_manager_skips_malformed_yaml(tmp_path):
    """Manager skips YAML files that cannot be parsed as templates."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    d = tmp_path / "templates"
    d.mkdir()

    # Write a valid template
    _write_template_yaml(d, "good")

    # Write an invalid YAML file (not a mapping)
    bad = d / "bad.yaml"
    bad.write_text("just a string", encoding="utf-8")

    mgr = MCPTemplateManager(template_dirs=[str(d)])
    templates = mgr.list()

    assert len(templates) == 1
    assert templates[0].name == "good"


def test_template_manager_nonexistent_dir(tmp_path):
    """Manager handles non-existent directories gracefully."""
    from everstaff.mcp_client.templates import MCPTemplateManager

    mgr = MCPTemplateManager(template_dirs=[str(tmp_path / "does-not-exist")])
    templates = mgr.list()

    assert templates == []
