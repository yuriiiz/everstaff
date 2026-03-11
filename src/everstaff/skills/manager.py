"""Skill manager — CRUD + first-directory-wins discovery + runtime integration."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import urllib.request
from pathlib import Path

from everstaff.schema.tool_spec import ToolDefinition, ToolParameter
from everstaff.skills.loader import SkillLoader
from everstaff.skills.models import SkillContent, SkillMetadata
from everstaff.tools.native import NativeTool

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages skill files: discovery, CRUD, store install, and runtime integration."""

    def __init__(
        self,
        skills_dirs: list[str],
        active_skill_names: list[str] | None = None,
        install_dirs: list[str] | None = None,
    ) -> None:
        self._loader = SkillLoader(skills_dirs)
        self._dirs: list[Path] = self._loader._skills_dirs
        # Dirs to install into — defaults to all dirs when not specified.
        # Set this to the user-writable subset to exclude read-only package dirs.
        if install_dirs is not None:
            self._install_dirs: list[Path] = [Path(d).expanduser().resolve() for d in install_dirs]
        else:
            self._install_dirs = self._dirs
        self._index: dict[str, SkillMetadata] | None = None

        # Runtime: active skills for this agent instance
        all_meta = self.discover()
        if active_skill_names is not None:
            active_set = set(active_skill_names)
            self._active_metadata = [m for m in all_meta if m.name in active_set]
        else:
            self._active_metadata = []

        self._activated: dict[str, str] = {}  # name -> cached instructions

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[SkillMetadata]:
        """Scan all dirs with first-dir-wins dedup. Returns deduplicated list."""
        if self._index is not None:
            return list(self._index.values())
        self._index = {}
        for d in self._dirs:
            for meta in self._loader.scan_dir(d):
                if meta.name in self._index:
                    logger.debug(
                        "duplicate skill name=%s ignored=%s keeping=%s",
                        meta.name, meta.path, self._index[meta.name].path,
                    )
                    continue
                self._index[meta.name] = meta
        return list(self._index.values())

    def list(self) -> list[SkillMetadata]:
        return self.discover()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get(self, name: str) -> SkillContent:
        self.discover()
        meta = (self._index or {}).get(name)
        if meta is None:
            raise FileNotFoundError(f"Skill '{name}' not found")
        return self._loader.load_content(meta.path)

    def create(self, name: str, content: str) -> Path:
        primary = self.primary_dir()
        if primary is None:
            raise RuntimeError("No skills directories configured")
        target_dir = primary / name
        if target_dir.exists():
            raise FileExistsError(f"Skill '{name}' already exists")
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_md = target_dir / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")
        self._invalidate()
        return skill_md

    def update(self, name: str, content: str) -> None:
        self.discover()
        meta = (self._index or {}).get(name)
        if meta is None:
            raise FileNotFoundError(f"Skill '{name}' not found")
        meta.path.write_text(content, encoding="utf-8")
        self._invalidate()

    def delete(self, name: str) -> None:
        self.discover()
        meta = (self._index or {}).get(name)
        if meta is None:
            raise FileNotFoundError(f"Skill '{name}' not found")
        shutil.rmtree(meta.path.parent)
        self._invalidate()

    def write_file(self, name: str, rel_path: str, content: str) -> Path:
        """Write content to a file within the skill directory."""
        self.discover()
        meta = (self._index or {}).get(name)
        if meta is None:
            raise FileNotFoundError(f"Skill '{name}' not found")
        
        skill_dir = meta.path.parent
        target = (skill_dir / rel_path).resolve()
        
        # Security: Ensure target is within skill_dir
        try:
            target.relative_to(skill_dir)
        except ValueError:
            raise ValueError(f"Invalid path: {rel_path} is outside skill directory")
            
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info("Updated skill file: %s (skill: %s)", target, name)
        
        # If writing to SKILL.md, we might need to invalidate index if metadata changed
        if target == meta.path:
            self._invalidate()
            
        return target

    def delete_file(self, name: str, rel_path: str) -> None:
        """Delete a file within the skill directory."""
        self.discover()
        meta = (self._index or {}).get(name)
        if meta is None:
            raise FileNotFoundError(f"Skill '{name}' not found")
            
        skill_dir = meta.path.parent
        target = (skill_dir / rel_path).resolve()
        
        try:
            target.relative_to(skill_dir)
        except ValueError:
            raise ValueError(f"Invalid path: {rel_path} is outside skill directory")
            
        if target == meta.path:
            raise ValueError("Cannot delete SKILL.md via delete_file. Use delete() to remove the entire skill.")
            
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
                logger.info("Deleted skill directory: %s (skill: %s)", target, name)
            else:
                target.unlink()
                logger.info("Deleted skill file: %s (skill: %s)", target, name)

    def primary_dir(self) -> Path | None:
        """First writable install dir, or first discovery dir as fallback."""
        return self._install_dirs[0] if self._install_dirs else (self._dirs[0] if self._dirs else None)

    def _invalidate(self) -> None:
        self._index = None

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    async def install(self, skill_package: str) -> list[Path]:
        """Install a skill via npx into all configured skills_dirs.

        Returns the list of paths where skill directories were created.
        Read-only dirs (e.g. package builtin) are silently skipped.
        """
        import tempfile

        if not self._dirs:
            raise RuntimeError("No skills directories configured for install")

        npx_path = shutil.which("npx")
        if not npx_path:
            raise RuntimeError("npx not found. Please install Node.js/npm.")

        env = os.environ.copy()
        env["CI"] = "true"
        env["npm_config_yes"] = "true"

        installed: list[Path] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            process = await asyncio.create_subprocess_exec(
                npx_path, "--yes", "skills", "add", skill_package, "-y",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=tmp_dir,
            )
            try:
                _, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=90.0
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise RuntimeError(f"Skill installation timed out: {skill_package}")

            if process.returncode != 0:
                raise RuntimeError(
                    f"Skill installation failed: {stderr_bytes.decode(errors='replace')}"
                )

            skill_folders = [sm.parent for sm in Path(tmp_dir).rglob("SKILL.md")]
            for skill_folder in skill_folders:
                for target_base in self._install_dirs:
                    try:
                        target_base.mkdir(parents=True, exist_ok=True)
                        target_path = target_base / skill_folder.name
                        if target_path.exists():
                            shutil.rmtree(target_path)
                        shutil.copytree(skill_folder, target_path)
                        logger.info("Installed skill '%s' to %s", skill_folder.name, target_path)
                        installed.append(target_path)
                    except PermissionError:
                        logger.debug("Skipping read-only dir %s for skill install", target_base)
                    except Exception as exc:
                        logger.warning(
                            "Failed to install skill '%s' to %s: %s",
                            skill_folder.name, target_base, exc,
                        )

        self._invalidate()
        return installed

    async def search_store(self, query: str) -> list[dict]:
        if not query:
            return await self._fetch_awesome_skills()
        return await self._search_npx(query)

    async def _fetch_awesome_skills(self) -> list[dict]:
        url = "https://raw.githubusercontent.com/ComposioHQ/awesome-claude-skills/refs/heads/master/README.md"
        try:
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(url, timeout=10).read().decode("utf-8")
            )
            skills = []
            for line in content.splitlines():
                line = line.strip()
                if not line.startswith("- ["):
                    continue
                match = re.search(
                    r"^- \[(.*?)\]\((.*?)\) - (.*?)(?:\. \*By \[@(.*?)\].*?\*)?$", line
                )
                if not match:
                    match = re.search(r"^- \[(.*?)\]\((.*?)\) - (.*?)$", line)
                if match:
                    groups = match.groups()
                    name, link, desc = groups[0].strip(), groups[1].strip(), groups[2].strip()
                    author = groups[3].strip() if len(groups) > 3 and groups[3] else "Unknown"
                    if author == "Unknown" and " *By [" in desc:
                        parts = desc.split(" *By [")
                        desc = parts[0].strip()
                        auth_match = re.search(r"@(.*?)\b", parts[1])
                        if auth_match:
                            author = auth_match.group(1)
                    full_name = ""
                    if link.startswith("./"):
                        skill_id = link.lstrip("./").rstrip("/")
                        full_name = f"ComposioHQ/awesome-claude-skills@{skill_id}"
                        link = f"https://github.com/ComposioHQ/awesome-claude-skills/tree/master/{skill_id}"
                    elif "github.com" in link:
                        parts = link.rstrip("/").split("/")
                        if len(parts) >= 5:
                            full_name = f"{parts[3]}/{parts[4]}@{parts[-1]}"
                    skills.append({
                        "name": name,
                        "full_name": full_name or name,
                        "author": author,
                        "url": link,
                        "description": desc,
                    })
            return skills[:30]
        except Exception as e:
            logger.error("Failed to fetch awesome skills: %s", e)
            return []

    async def _search_npx(self, query: str) -> list[dict]:
        npx_path = shutil.which("npx")
        if not npx_path:
            raise RuntimeError("npx not found.")
        env = os.environ.copy()
        env["CI"] = "true"
        env["npm_config_yes"] = "true"
        process = await asyncio.create_subprocess_exec(
            npx_path, "--yes", "skills", "find", query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return []
        if process.returncode != 0:
            return []

        ansi_re = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        output = ansi_re.sub("", stdout.decode())
        results = []
        lines = output.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith("██") or line.startswith("Install with"):
                i += 1
                continue
            if "@" in line and "/" in line.split("@")[0]:
                try:
                    full_name_raw = line.split(" ")[0]
                    repo, skill_raw = full_name_raw.split("@")
                    url = ""
                    if i + 1 < len(lines) and "https://" in lines[i + 1]:
                        url = lines[i + 1].split("└")[-1].strip()
                        i += 1
                    results.append({
                        "name": skill_raw.strip(),
                        "full_name": full_name_raw,
                        "author": repo.split("/")[0],
                        "url": url,
                        "description": "",
                    })
                except Exception:
                    pass
            i += 1
            if len(results) >= 50:
                break
        return results

    # ------------------------------------------------------------------
    # Runtime integration (agent execution)
    # ------------------------------------------------------------------

    @property
    def active_skills(self) -> list[SkillMetadata]:
        return self._active_metadata

    def get_prompt_injection(self) -> str:
        if not self._active_metadata:
            return ""
        lines = [
            "## Skills",
            "",
            "You have access to the following skills. "
            "To use a skill, you MUST call the `use_skill` tool with the skill name. "
            "The tool will return detailed instructions for that skill.",
            "",
        ]
        for meta in self._active_metadata:
            lines.append(f"- **{meta.name}**: {meta.description}")
        return "\n".join(lines)

    def get_tools(self) -> list[NativeTool]:
        tools = []
        use_skill = self.create_use_skill_tool()
        if use_skill is not None:
            tools.append(use_skill)
        read_resource = self.create_read_skill_resource_tool()
        if read_resource is not None:
            tools.append(read_resource)
        update = self.create_update_skill_tool()
        if update is not None:
            tools.append(update)
        return tools

    async def activate_skill(self, skill_name: str) -> str:
        if skill_name in self._activated:
            return self._activated[skill_name]
        active_names = {m.name for m in self._active_metadata}
        if skill_name not in active_names:
            return f"Error: Skill '{skill_name}' not available. Available skills: {sorted(active_names)}"
        try:
            content = self.get(skill_name)
            instructions = content.instructions
            if content.resource_files:
                skill_dir = content.metadata.path.parent
                resource_list = "\n".join(
                    f"  - {f.relative_to(skill_dir)}" for f in content.resource_files
                )
                instructions += f"\n\n## Bundled Resources\n{resource_list}"
            self._activated[skill_name] = instructions
            return instructions
        except Exception as e:
            return f"Error loading skill '{skill_name}': {e}"

    def create_use_skill_tool(self) -> NativeTool | None:
        if not self._active_metadata:
            return None
        manager = self

        async def use_skill(skill_name: str) -> str:
            return await manager.activate_skill(skill_name)

        skills_detail = "\n".join(
            f'  - "{m.name}": {m.description}' for m in self._active_metadata
        )
        defn = ToolDefinition(
            name="use_skill",
            description=(
                "Activate a skill to load its detailed instructions and follow them. "
                "You MUST call this tool before attempting any skill-related task.\n\n"
                f"Available skills:\n{skills_detail}"
            ),
            parameters=[
                ToolParameter(
                    name="skill_name",
                    type="string",
                    description=f"One of: {', '.join(repr(m.name) for m in self._active_metadata)}",
                    required=True,
                )
            ],
            source="builtin",
        )
        return NativeTool(func=use_skill, definition_=defn)

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

    @staticmethod
    def _update_skill_definition(skills_suffix: str = "") -> ToolDefinition:
        """Shared definition for update_skill tool."""
        desc = (
            "Update skill files. Only use this tool when the user explicitly asks to update or modify skills. "
            "Use action 'write' to create or overwrite a file, "
            "or 'delete' to remove a file. Cannot delete SKILL.md."
        )
        if skills_suffix:
            desc += f"\n\n{skills_suffix}"
        return ToolDefinition(
            name="update_skill",
            description=desc,
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

    def create_update_skill_tool(self) -> NativeTool | None:
        """Create the update_skill tool for modifying skill files."""
        if not self._active_metadata:
            return None
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
        defn = self._update_skill_definition(f"Discovered skills: {skills_list}")
        return NativeTool(func=update_skill, definition_=defn)
