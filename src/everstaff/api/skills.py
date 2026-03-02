"""Skills management API — thin layer over SkillManager."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from everstaff.skills.manager import SkillManager

logger = logging.getLogger(__name__)


class CreateSkillRequest(BaseModel):
    name: str
    content: str


class UpdateSkillRequest(BaseModel):
    content: str


class InstallSkillRequest(BaseModel):
    name: str


class UpdateSkillFileRequest(BaseModel):
    content: str


class CreateSkillFileRequest(BaseModel):
    path: str


def make_router(config) -> APIRouter:
    router = APIRouter(tags=["skills"], prefix="/skills")

    def _mgr() -> SkillManager:
        from pathlib import Path
        skills_dirs = list(config.skills_dirs)
        builtin: str | None = None
        try:
            import everstaff as _pkg
            builtin = str(Path(_pkg.__file__).parent / "builtin_skills")
        except Exception:
            pass
        # Keep builtin at the end so primary_dir() resolves to the first
        # user-writable directory (e.g. ./skills) rather than the package path.
        if builtin:
            user_dirs = [d for d in skills_dirs if d != builtin]
            skills_dirs = user_dirs + [builtin]
        else:
            user_dirs = skills_dirs
        # install_dirs excludes the package-injected builtin dir — skills
        # must only be installed into user-configured writable directories.
        return SkillManager(skills_dirs, install_dirs=user_dirs)

    @router.get("")
    async def list_skills() -> list[dict]:
        return [{"name": m.name, "description": m.description} for m in _mgr().list()]

    @router.get("/store")
    async def get_store_skills(query: str = "") -> list[dict]:
        return await _mgr().search_store(query)

    @router.post("/install")
    async def install_skill(body: InstallSkillRequest) -> dict:
        try:
            installed_paths = await _mgr().install(body.name)
            return {
                "name": body.name,
                "status": "installed",
                "paths": [str(p) for p in installed_paths],
            }
        except Exception as exc:
            raise HTTPException(500, f"Install failed: {exc}")

    @router.get("/{name}")
    async def get_skill(name: str) -> dict:
        try:
            content = _mgr().get(name)
            return {"name": name, "content": content.metadata.path.read_text(encoding="utf-8")}
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")

    @router.post("", status_code=201)
    async def create_skill(body: CreateSkillRequest) -> dict:
        try:
            path = _mgr().create(body.name, body.content)
            return {"name": body.name, "path": str(path)}
        except FileExistsError:
            raise HTTPException(409, f"Skill '{body.name}' already exists")
        except RuntimeError as e:
            raise HTTPException(500, str(e))

    @router.put("/{name}")
    async def update_skill(name: str, body: UpdateSkillRequest) -> dict:
        try:
            _mgr().update(name, body.content)
            return {"name": name, "updated": True}
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")

    @router.delete("/{name}", status_code=204)
    async def delete_skill(name: str) -> None:
        try:
            _mgr().delete(name)
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")

    @router.get("/{name}/files")
    async def list_skill_files(name: str) -> dict:
        try:
            content = _mgr().get(name)
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")
        skill_dir = content.metadata.path.parent
        files = []
        for p in skill_dir.rglob("*"):
            if p.is_file():
                files.append({"name": p.name, "path": str(p.relative_to(skill_dir))})
        return {"files": sorted(files, key=lambda x: x["path"])}

    @router.get("/{name}/files/{path:path}")
    async def get_skill_file(name: str, path: str) -> dict:
        try:
            content = _mgr().get(name)
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")
        skill_dir = content.metadata.path.parent
        target = (skill_dir / path).resolve()
        try:
            target.relative_to(skill_dir)
        except ValueError:
            raise HTTPException(400, "Invalid path")
        if not target.exists() or not target.is_file():
            raise HTTPException(404, "File not found")
        return {"name": target.name, "path": path, "content": target.read_text(encoding="utf-8")}

    @router.put("/{name}/files/{path:path}")
    async def update_skill_file(name: str, path: str, body: UpdateSkillFileRequest) -> dict:
        try:
            target = _mgr().write_file(name, path, body.content)
            return {"name": name, "path": path, "updated": True, "full_path": str(target)}
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(500, str(e))

    @router.post("/{name}/files")
    async def create_skill_file(name: str, body: CreateSkillFileRequest) -> dict:
        try:
            # Create an empty file
            target = _mgr().write_file(name, body.path, "")
            return {"name": name, "path": body.path, "created": True, "full_path": str(target)}
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(500, str(e))

    @router.delete("/{name}/files/{path:path}", status_code=204)
    async def delete_skill_file(name: str, path: str) -> None:
        try:
            _mgr().delete_file(name, path)
        except FileNotFoundError:
            raise HTTPException(404, f"Skill '{name}' not found")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(500, str(e))

    return router
