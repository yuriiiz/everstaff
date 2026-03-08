from __future__ import annotations

import logging
from pathlib import Path

import uuid as _uuid
import yaml as _yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentWriteRequest(BaseModel):
    model_config = {"extra": "allow"}

    agent_name: str = ""
    uuid: str = ""


def _get_builtin_agents_dir() -> Path | None:
    try:
        from everstaff.core.config import _builtin_agents_path
        p = _builtin_agents_path()
        return Path(p) if p else None
    except Exception:
        return None

def _find_agent_path(agents_dir: Path, uuid: str) -> tuple[Path | None, bool]:
    """Find agent YAML by uuid. Tries {uuid}.yaml first (O(1)), then scans."""
    from everstaff.utils.yaml_loader import load_yaml

    # O(1) lookup: try {uuid}.yaml directly in user agents_dir
    if agents_dir.exists():
        direct = agents_dir / f"{uuid}.yaml"
        if direct.exists():
            return direct, False

    # Scan user agents_dir for backward compat (old name-based files)
    if agents_dir.exists():
        for f in agents_dir.glob("*.yaml"):
            try:
                if load_yaml(str(f)).get("uuid") == uuid:
                    return f, False
            except Exception:
                pass

    # Check builtin agents (also UUID-based filenames)
    builtin_dir = _get_builtin_agents_dir()
    if builtin_dir and builtin_dir.exists():
        direct_builtin = builtin_dir / f"{uuid}.yaml"
        if direct_builtin.exists():
            return direct_builtin, True
        # Scan for backward compat
        for f in builtin_dir.glob("*.yaml"):
            try:
                if load_yaml(str(f)).get("uuid") == uuid:
                    return f, True
            except Exception:
                pass
    return None, False


def make_router(config) -> APIRouter:
    agents_dir = Path(config.agents_dir).expanduser().resolve()
    router = APIRouter(tags=["agents"])

    @router.get("/agents")
    async def list_agents() -> list[dict]:
        from everstaff.utils.yaml_loader import load_yaml
        # Collect builtin agents first, then user agents (deduplicate by uuid)
        by_uuid: dict[str, dict] = {}
        builtin_dir = _get_builtin_agents_dir()
        if builtin_dir and builtin_dir.exists():
            for f in sorted(builtin_dir.glob("*.yaml")):
                try:
                    spec = load_yaml(str(f))
                    uid = spec.get("uuid", f.stem)
                    by_uuid[uid] = spec
                except Exception as exc:
                    logger.debug("Failed to load builtin agent spec %s: %s", f, exc)
        # User agents override builtins by uuid
        if agents_dir.exists():
            for f in sorted(agents_dir.glob("*.yaml")):
                try:
                    spec = load_yaml(str(f))
                    uid = spec.get("uuid", f.stem)
                    by_uuid[uid] = spec
                except Exception as exc:
                    logger.debug("Failed to load agent spec %s: %s", f, exc)
        return list(by_uuid.values())

    @router.get("/agents/{name}")
    async def get_agent(name: str) -> dict:
        from everstaff.utils.yaml_loader import load_yaml
        # Try as uuid first (O(1) lookup)
        uuid_path = (agents_dir / f"{name}.yaml").resolve()
        if uuid_path.is_relative_to(agents_dir) and uuid_path.exists():
            return load_yaml(str(uuid_path))
        # Fall back to scanning by agent_name inside YAML
        if agents_dir.exists():
            for f in agents_dir.glob("*.yaml"):
                try:
                    spec = load_yaml(str(f))
                    if spec.get("agent_name") == name:
                        return spec
                except Exception:
                    pass
        # Fall back to builtin agents — try {name}.yaml as UUID, then scan
        builtin_dir = _get_builtin_agents_dir()
        if builtin_dir and builtin_dir.exists():
            builtin_path = (builtin_dir / f"{name}.yaml").resolve()
            if builtin_path.is_relative_to(builtin_dir) and builtin_path.exists():
                return load_yaml(str(builtin_path))
            # Scan by agent_name inside YAML
            for f in builtin_dir.glob("*.yaml"):
                try:
                    spec = load_yaml(str(f))
                    if spec.get("agent_name") == name:
                        return spec
                except Exception:
                    pass
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    @router.post("/agents", status_code=201)
    async def create_agent(body: AgentWriteRequest) -> dict:
        name = body.agent_name
        if not name:
            raise HTTPException(status_code=400, detail="agent_name is required")

        # generate uuid if not provided
        if not body.uuid:
            body.uuid = str(_uuid.uuid4())

        # Filename = {uuid}.yaml
        path = (agents_dir / f"{body.uuid}.yaml").resolve()
        if not path.is_relative_to(agents_dir):
            raise HTTPException(status_code=400, detail="Invalid agent uuid")
        agents_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(_yaml.dump(body.model_dump(exclude_none=True), allow_unicode=True), encoding="utf-8")
        return {"name": name, "uuid": body.uuid}

    @router.put("/agents/{uuid}")
    async def update_agent(uuid: str, body: AgentWriteRequest) -> dict:
        if not body.agent_name:
            raise HTTPException(status_code=400, detail="agent_name is required")

        path, is_builtin = _find_agent_path(agents_dir, uuid)
        if not path:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Write to {uuid}.yaml (no rename needed when agent_name changes)
        target_path = (agents_dir / f"{uuid}.yaml").resolve()
        if not target_path.is_relative_to(agents_dir):
            raise HTTPException(status_code=400, detail="Invalid agent uuid")

        agents_dir.mkdir(parents=True, exist_ok=True)
        # If old file was name-based and different from uuid-based, remove old
        if path != target_path and path.exists() and not is_builtin:
            path.unlink()

        target_path.write_text(_yaml.dump(body.model_dump(exclude_none=True), allow_unicode=True), encoding="utf-8")
        # Daemon auto-reloads via agents_dir file watcher — no sync reload needed.

        return {"uuid": uuid, "updated": True}

    @router.delete("/agents/{uuid}", status_code=204)
    async def delete_agent(uuid: str) -> None:
        path, is_builtin = _find_agent_path(agents_dir, uuid)
        if not path:
            raise HTTPException(status_code=404, detail="Agent not found")
        if is_builtin:
            raise HTTPException(status_code=403, detail="Cannot delete built-in agents")

        path.unlink()

    return router
