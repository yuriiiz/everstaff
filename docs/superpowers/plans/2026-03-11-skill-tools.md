# Skill Tools Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `read_skill_resource` (auto-registered) and `update_skill` (opt-in) tools so agents can read skill resource files and update skill content.

**Architecture:** Both tools are created as methods on `SkillManager`, following the existing `create_use_skill_tool()` pattern. `read_skill_resource` is auto-registered in `get_tools()`. `update_skill` is registered in `agent_builder.py` when present in the agent's `tools:` list.

**Tech Stack:** Python, everstaff framework (NativeTool, ToolDefinition, ToolParameter, SkillManager)

**Spec:** `docs/superpowers/specs/2026-03-11-skill-tools-design.md`

---

## Chunk 1: read_skill_resource

### Task 1: Fix activate_skill to show relative paths

**Files:**
- Modify: `src/everstaff/skills/manager.py` (method `activate_skill`, around line 374-389)
- Test: `tests/test_skills/test_skills.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills/test_skills.py`:

```python
def test_activate_skill_shows_relative_resource_paths():
    """activate_skill() must list resource files as relative paths, not absolute."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\n# Instructions"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print('hello')")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )

        result = asyncio.run(manager.activate_skill("my-skill"))
        # Must contain relative path, not absolute
        assert "scripts/run.py" in result
        assert str(tmpdir) not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_skills/test_skills.py::test_activate_skill_shows_relative_resource_paths -v`
Expected: FAIL — the result contains absolute paths

- [ ] **Step 3: Fix activate_skill to use relative paths**

In `src/everstaff/skills/manager.py`, change the `activate_skill` method. Replace:

```python
            if content.resource_files:
                resource_list = "\n".join(f"  - {f}" for f in content.resource_files)
                instructions += f"\n\n## Bundled Resources\n{resource_list}"
```

With:

```python
            if content.resource_files:
                skill_dir = content.metadata.path.parent
                resource_list = "\n".join(
                    f"  - {f.relative_to(skill_dir)}" for f in content.resource_files
                )
                instructions += f"\n\n## Bundled Resources\n{resource_list}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_skills/test_skills.py::test_activate_skill_shows_relative_resource_paths -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_skills/test_skills.py src/everstaff/skills/manager.py
git commit -m "fix: show relative paths for skill resource files in activate_skill"
```

---

### Task 2: Implement read_skill_resource tool

**Files:**
- Modify: `src/everstaff/skills/manager.py` (add `create_read_skill_resource_tool` method, update `get_tools`)
- Test: `tests/test_skills/test_skills.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skills/test_skills.py`:

```python
def test_read_skill_resource_list_files():
    """read_skill_resource with empty file_path returns file listing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\n# Body"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print(1)")
        (skill_dir / "notes.txt").write_text("hello")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()
        assert tool is not None

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": ""}))
        assert "scripts/run.py" in result
        assert "notes.txt" in result
        # SKILL.md should not appear in listing
        assert "SKILL.md" not in result


def test_read_skill_resource_read_file():
    """read_skill_resource with a valid file_path returns file content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\n# Body"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print('hello world')")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": "scripts/run.py"}))
        assert "print('hello world')" in result


def test_read_skill_resource_nonexistent_file():
    """read_skill_resource returns error for nonexistent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": "no-such-file.txt"}))
        assert "Error" in result
        assert "not found" in result


def test_read_skill_resource_path_traversal():
    """read_skill_resource rejects path traversal attempts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")
        # Create a file outside skill dir
        (tmpdir / "secret.txt").write_text("secret data")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": "../secret.txt"}))
        assert "Error" in result
        assert "secret data" not in result


def test_read_skill_resource_inactive_skill():
    """read_skill_resource rejects requests for non-active skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "other-skill", "Other", "Body")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=[],
        )
        # No active skills -> no tool
        tool = manager.create_read_skill_resource_tool()
        assert tool is None


def test_get_tools_includes_read_skill_resource():
    """get_tools() returns both use_skill and read_skill_resource."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "My desc", "Body")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tools = manager.get_tools()
        names = [t.definition.name for t in tools]
        assert "use_skill" in names
        assert "read_skill_resource" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_skills/test_skills.py -k "read_skill_resource" -v`
Expected: FAIL — `create_read_skill_resource_tool` does not exist

- [ ] **Step 3: Implement create_read_skill_resource_tool and update get_tools**

In `src/everstaff/skills/manager.py`, add the following method after `create_use_skill_tool()` (after line 419):

```python
    def create_read_skill_resource_tool(self) -> NativeTool | None:
        """Create the read_skill_resource tool for reading files in skill directories."""
        if not self._active_metadata:
            return None
        manager = self

        async def read_skill_resource(skill_name: str, file_path: str = "") -> str:
            active_names = {m.name for m in manager._active_metadata}
            if skill_name not in active_names:
                return f"Error: Skill '{skill_name}' not available. Available: {sorted(active_names)}"

            try:
                content = manager.get(skill_name)
            except FileNotFoundError:
                return f"Error: Skill '{skill_name}' not found."

            skill_dir = content.metadata.path.parent

            if not file_path:
                # Return file listing (relative paths, excludes SKILL.md)
                if not content.resource_files:
                    return ""
                return "\n".join(
                    str(f.relative_to(skill_dir)) for f in content.resource_files
                )

            # Resolve and validate path
            target = (skill_dir / file_path).resolve()
            try:
                target.relative_to(skill_dir.resolve())
            except ValueError:
                return f"Error: Invalid path '{file_path}' — outside skill directory."

            if not target.exists():
                return f"Error: file not found: {file_path}"

            try:
                return target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return "Error: file appears to be binary and cannot be displayed as text."

        skills_detail = "\n".join(
            f'  - "{m.name}": {m.description}' for m in self._active_metadata
        )
        defn = ToolDefinition(
            name="read_skill_resource",
            description=(
                "Read a resource file from a skill directory. "
                "Pass an empty file_path to list all available files.\n\n"
                f"Available skills:\n{skills_detail}"
            ),
            parameters=[
                ToolParameter(
                    name="skill_name",
                    type="string",
                    description=f"One of: {', '.join(repr(m.name) for m in self._active_metadata)}",
                    required=True,
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Relative path to the file within the skill directory (e.g. 'scripts/run.py'). Leave empty to list all files.",
                    required=False,
                    default="",
                ),
            ],
            source="builtin",
        )
        return NativeTool(func=read_skill_resource, definition_=defn)
```

Update `get_tools()` (around line 370):

```python
    def get_tools(self) -> list[NativeTool]:
        tools = []
        use_skill = self.create_use_skill_tool()
        if use_skill is not None:
            tools.append(use_skill)
        read_resource = self.create_read_skill_resource_tool()
        if read_resource is not None:
            tools.append(read_resource)
        return tools
```

Also update the existing test `test_skill_manager_get_tools_returns_use_skill_tool` in `tests/test_skills/test_skills.py` — it asserts `len(tools) == 1` which will break now that `get_tools()` returns 2 tools. Replace:

```python
        assert len(tools) == 1
        assert tools[0].definition.name == "use_skill"
```

With:

```python
        names = [t.definition.name for t in tools]
        assert "use_skill" in names
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_skills/test_skills.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/everstaff/skills/manager.py tests/test_skills/test_skills.py
git commit -m "feat: add read_skill_resource tool for reading skill resource files"
```

---

## Chunk 2: update_skill

### Task 3: Implement update_skill tool

**Files:**
- Modify: `src/everstaff/skills/manager.py` (add `create_update_skill_tool` method)
- Test: `tests/test_skills/test_skills.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skills/test_skills.py`:

```python
def test_update_skill_tool_write_file():
    """update_skill with action=write creates/overwrites a file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)])
        tool = manager.create_update_skill_tool()
        assert tool is not None

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "write",
            "file_path": "scripts/run.py",
            "content": "print('new')",
        }))
        assert "Error" not in result
        assert (tmpdir / "my-skill" / "scripts" / "run.py").read_text() == "print('new')"


def test_update_skill_tool_write_skill_md():
    """update_skill with action=write can overwrite SKILL.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Old body")

        manager = SkillManager(skills_dirs=[str(tmpdir)])
        tool = manager.create_update_skill_tool()

        new_content = "---\nname: my-skill\ndescription: Updated\n---\n\n# New body"
        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "write",
            "file_path": "SKILL.md",
            "content": new_content,
        }))
        assert "Error" not in result
        assert "New body" in (tmpdir / "my-skill" / "SKILL.md").read_text()


def test_update_skill_tool_delete_file():
    """update_skill with action=delete removes a file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\nBody"
        )
        (skill_dir / "extra.txt").write_text("delete me")

        manager = SkillManager(skills_dirs=[str(tmpdir)])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "delete",
            "file_path": "extra.txt",
        }))
        assert "Error" not in result
        assert not (skill_dir / "extra.txt").exists()


def test_update_skill_tool_delete_skill_md_refused():
    """update_skill refuses to delete SKILL.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "delete",
            "file_path": "SKILL.md",
        }))
        assert "Error" in result
        assert (tmpdir / "my-skill" / "SKILL.md").exists()


def test_update_skill_tool_path_traversal():
    """update_skill rejects path traversal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "write",
            "file_path": "../evil.txt",
            "content": "hacked",
        }))
        assert "Error" in result
        assert not (tmpdir / "evil.txt").exists()


def test_update_skill_tool_invalid_action():
    """update_skill rejects unknown actions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "rename",
            "file_path": "x.txt",
        }))
        assert "Error" in result


def test_update_skill_tool_unknown_skill():
    """update_skill returns error for nonexistent skill."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        manager = SkillManager(skills_dirs=[str(tmpdir)])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "no-such-skill",
            "action": "write",
            "file_path": "test.txt",
            "content": "data",
        }))
        assert "Error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_skills/test_skills.py -k "update_skill" -v`
Expected: FAIL — `create_update_skill_tool` does not exist

- [ ] **Step 3: Implement create_update_skill_tool**

In `src/everstaff/skills/manager.py`, add the following method after `create_read_skill_resource_tool()`:

```python
    def create_update_skill_tool(self) -> NativeTool | None:
        """Create the update_skill tool for modifying skill files."""
        manager = self

        async def update_skill(skill_name: str, action: str, file_path: str, content: str = "") -> str:
            if action not in ("write", "delete"):
                return f"Error: Invalid action '{action}'. Must be 'write' or 'delete'."

            try:
                if action == "write":
                    manager.write_file(skill_name, file_path, content)
                    return f"Written: {file_path} (skill: {skill_name})"
                else:  # delete
                    manager.delete_file(skill_name, file_path)
                    return f"Deleted: {file_path} (skill: {skill_name})"
            except FileNotFoundError as e:
                return f"Error: {e}"
            except ValueError as e:
                return f"Error: {e}"

        all_skills = manager.discover()
        skills_list = ", ".join(repr(m.name) for m in all_skills) if all_skills else "(none discovered)"

        defn = ToolDefinition(
            name="update_skill",
            description=(
                "Update skill files. Use action 'write' to create or overwrite a file, "
                "or 'delete' to remove a file. Cannot delete SKILL.md.\n\n"
                f"Discovered skills: {skills_list}"
            ),
            parameters=[
                ToolParameter(
                    name="skill_name",
                    type="string",
                    description="Name of the skill to update",
                    required=True,
                ),
                ToolParameter(
                    name="action",
                    type="string",
                    description="'write' to create/overwrite a file, 'delete' to remove a file",
                    required=True,
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Relative path within the skill directory (e.g. 'SKILL.md', 'scripts/run.py')",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="File content (required for 'write', ignored for 'delete')",
                    required=False,
                    default="",
                ),
            ],
            source="builtin",
        )
        return NativeTool(func=update_skill, definition_=defn)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_skills/test_skills.py -k "update_skill" -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/everstaff/skills/manager.py tests/test_skills/test_skills.py
git commit -m "feat: add update_skill tool for modifying skill files"
```

---

### Task 4: Register update_skill in agent_builder

**Files:**
- Modify: `src/everstaff/builder/agent_builder.py` (around line 236 and line 208)
- Test: `tests/test_builder/test_framework_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_builder/test_framework_tools.py`:

```python
@pytest.mark.asyncio
async def test_update_skill_registered_when_in_tools(tmp_path):
    """update_skill is registered when listed in agent spec tools."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.schema.model_config import ModelMapping

    # Create a skill directory with a valid skill
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test\n---\n\nBody"
    )

    config = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="test-model")},
        skills_dirs=[str(skills_dir)],
    )
    spec = AgentSpec(agent_name="test", tools=["update_skill"])
    env = TestEnvironment(config=config)

    builder = AgentBuilder(spec, env, session_id="test-update-skill")
    runtime, ctx = await builder.build()

    tool_names = list(ctx.tool_registry._tools.keys())
    assert "update_skill" in tool_names


@pytest.mark.asyncio
async def test_update_skill_not_registered_when_not_in_tools(tmp_path):
    """update_skill is NOT registered when not listed in agent spec tools."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.schema.model_config import ModelMapping

    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test\n---\n\nBody"
    )

    config = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="test-model")},
        skills_dirs=[str(skills_dir)],
    )
    spec = AgentSpec(agent_name="test", tools=[])
    env = TestEnvironment(config=config)

    builder = AgentBuilder(spec, env, session_id="test-no-update-skill")
    runtime, ctx = await builder.build()

    tool_names = list(ctx.tool_registry._tools.keys())
    assert "update_skill" not in tool_names
```

First check the existing test file for imports and patterns:

Read `tests/test_builder/test_framework_tools.py` to match existing import style.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_builder/test_framework_tools.py -k "update_skill" -v`
Expected: FAIL — update_skill not in tool_names

- [ ] **Step 3: Register update_skill in agent_builder.py**

In `src/everstaff/builder/agent_builder.py`, make two changes:

**Change 1:** After the skill_provider tools registration (after line 236), add:

```python
        # Register update_skill if requested in agent tools
        if "update_skill" in spec_tools and hasattr(skill_provider, "create_update_skill_tool"):
            _update_skill_tool = skill_provider.create_update_skill_tool()
            if _update_skill_tool is not None:
                tool_registry.register_native(_update_skill_tool)
```

**Change 2:** In the `system_tool_names` section, **after** `spec_tools` is defined (after line 213: `spec_tools = set(getattr(self._spec, "tools", None) or [])`), add:

```python
        if "update_skill" in spec_tools:
            system_tool_names.add("update_skill")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_builder/test_framework_tools.py -k "update_skill" -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_skills/ tests/test_builder/test_framework_tools.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/everstaff/builder/agent_builder.py tests/test_builder/test_framework_tools.py
git commit -m "feat: register update_skill tool in agent builder when listed in tools"
```
