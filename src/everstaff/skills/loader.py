"""Skill loader — pure filesystem reader."""
from __future__ import annotations

import logging
from pathlib import Path

from everstaff.skills.models import SkillContent, SkillMetadata
from everstaff.utils.yaml_loader import parse_yaml_frontmatter

logger = logging.getLogger(__name__)


class SkillLoader:
    """Pure filesystem reader for skill directories."""

    def __init__(self, skills_dirs: list[str | Path]) -> None:
        self._skills_dirs = [Path(d).expanduser().resolve() for d in skills_dirs]

    def scan_dir(self, directory: Path) -> list[SkillMetadata]:
        """Scan one directory for SKILL.md files. No dedup. Skips malformed."""
        results: list[SkillMetadata] = []
        if not directory.exists():
            return results
        for skill_md in sorted(directory.glob("*/SKILL.md")):
            try:
                results.append(self._parse_metadata(skill_md))
            except Exception:
                logger.debug("Skipping malformed skill at %s", skill_md, exc_info=True)
        return results

    def load_content(self, skill_md_path: Path) -> SkillContent:
        """Load full skill content given the SKILL.md path directly."""
        metadata = self._parse_metadata(skill_md_path)
        text = skill_md_path.read_text(encoding="utf-8")
        _, body = parse_yaml_frontmatter(text)

        skill_dir = skill_md_path.parent
        resource_files = [f for f in skill_dir.iterdir() if f.is_file() and f.name != "SKILL.md"]
        for subdir in skill_dir.iterdir():
            if subdir.is_dir():
                resource_files.extend(f for f in subdir.rglob("*") if f.is_file())

        return SkillContent(metadata=metadata, instructions=body, resource_files=sorted(resource_files))

    def _parse_metadata(self, skill_md: Path) -> SkillMetadata:
        text = skill_md.read_text(encoding="utf-8")
        frontmatter, _ = parse_yaml_frontmatter(text)
        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")
        if not name:
            raise ValueError(f"SKILL.md missing 'name' in frontmatter: {skill_md}")
        if not description:
            raise ValueError(f"SKILL.md missing 'description' in frontmatter: {skill_md}")
        return SkillMetadata(name=name, description=description, path=skill_md)
