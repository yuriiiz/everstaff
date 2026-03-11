# Skill Tools: read_skill_resource + update_skill

## Problem

1. `use_skill` loads SKILL.md instructions and lists resource files, but agents cannot read those files
2. No agent-callable tool exists for updating skill content

## Solution

Two new tools in the skill system.

### read_skill_resource

**Registration**: Auto-registered alongside `use_skill` whenever an agent has skills configured. Created in `SkillManager.get_tools()`.

**Parameters**:
- `skill_name: str` (required) — must be one of the agent's active skills
- `file_path: str` (optional, default `""`) — relative path within the skill directory (e.g. `scripts/run.py`). If empty, returns a listing of all files.

**Behavior**:
- Validates `skill_name` is in the agent's active skills
- Validates `file_path` is within the skill directory (path traversal check via `Path.relative_to()`)
- When `file_path` is empty: returns a newline-separated list of relative file paths, recursively including all subdirectories
- When `file_path` is provided: reads and returns the file content as text
- Binary file handling: catches `UnicodeDecodeError` and returns `"Error: file appears to be binary and cannot be displayed as text."`

**Prerequisite change**: `activate_skill()` currently formats resource files as absolute paths. Must change to convert to relative paths at display time (in `activate_skill()` only, not in `SkillContent.resource_files` data model which stays as absolute `Path` objects). This way the agent sees `scripts/run.py` instead of `/absolute/path/to/scripts/run.py`, while `read_skill_resource` can still resolve relative paths back to absolute for file I/O.

**Edge cases**:
- Nonexistent `file_path`: return `"Error: file not found: {file_path}"`
- Empty skill directory (no resource files besides SKILL.md): listing returns empty string (matches existing `resource_files` behavior which excludes SKILL.md)
- `read_skill_resource` is auto-included in `system_tool_names` via `skill_provider.get_tools()`, same as `use_skill` — no extra handling needed

### update_skill

**Registration**: User-selectable. Added to `tools:` list in agent YAML config. Created by `SkillManager.create_update_skill_tool()`.

**Integration point**: In `agent_builder.py`, after `skill_provider` is built (line 168), check if `update_skill` is in the agent's `tools:` list. If so, call `skill_provider.create_update_skill_tool()` and register the result in `tool_registry`. This avoids `_split_framework_tools` which is restricted to `source=builtin` and runs before `SkillManager` exists.

Specifically, insert after line 236 (`skill_provider.get_tools()` registration):
```python
# Register update_skill if requested in agent tools
if "update_skill" in spec_tools and hasattr(skill_provider, "create_update_skill_tool"):
    update_tool = skill_provider.create_update_skill_tool()
    if update_tool is not None:
        tool_registry.register_native(update_tool)
```

Also add `"update_skill"` to `system_tool_names` when present (around line 208) so it bypasses user permission checks.

**Parameters**:
- `skill_name: str` (required) — any discovered skill (not limited to active skills)
- `action: str` (required) — `write` or `delete`
- `file_path: str` (required) — relative path within skill directory (e.g. `SKILL.md`, `scripts/run.py`)
- `content: str` (optional, default `""`) — file content, required when action is `write`, ignored for `delete`

**Behavior**:
- `write`: Creates or overwrites the file. Auto-creates parent directories. Works for any file including `SKILL.md`.
- `delete`: Deletes the file. Refuses to delete `SKILL.md`.
- Path traversal check on `file_path`. Skill name validated against all discovered skills.
- Delegates to existing `SkillManager.write_file()` and `SkillManager.delete_file()`.
- `update_skill` cannot create new skills from scratch — `skill_name` must already exist in the discovered index. Use `create_skill` bootstrap tool for that.

## Files Changed

| File | Change |
|------|--------|
| `src/everstaff/skills/manager.py` | Add `create_read_skill_resource_tool()`, `create_update_skill_tool()`. Update `get_tools()` to include read tool. Fix `activate_skill()` to display relative paths for resource files. |
| `src/everstaff/builder/agent_builder.py` | After skill_provider tools registration, check for `update_skill` in spec tools and register it. Add `update_skill` to `system_tool_names` when present. |

## Design Decisions

- `read_skill_resource` is auto-registered because it's a natural companion to `use_skill` — if you can activate a skill, you should be able to read its resources.
- `update_skill` is opt-in because mutation is a stronger capability that not all agents should have.
- `update_skill` is not limited to active skills — an agent tasked with managing skills should be able to edit any discovered skill, not just the ones it's currently using.
- Single `update_skill` tool with `action` parameter instead of separate tools — keeps agent config simple (one tool name).
- Only `write` and `delete` actions — `rename` is achievable via delete + write.
- Binary files return an error message instead of crashing.
- `update_skill` registered after `skill_provider` is built (not in `_split_framework_tools`) to ensure `SkillManager` instance is available and no `source=builtin` restriction.
