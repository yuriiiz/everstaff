from __future__ import annotations

import logging
from pathlib import Path

import yaml as _yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AgentWriteRequest(BaseModel):
    model_config = {"extra": "allow"}

    agent_name: str = ""


def make_router(config) -> APIRouter:
    agents_dir = Path(config.agents_dir).expanduser().resolve()
    router = APIRouter(tags=["agents"])

    @router.get("/agents")
    async def list_agents() -> list[dict]:
        specs = []
        if agents_dir.exists():
            for f in sorted(agents_dir.glob("*.yaml")):
                try:
                    from everstaff.utils.yaml_loader import load_yaml
                    specs.append(load_yaml(str(f)))
                except Exception as exc:
                    logger.debug("Failed to load agent spec %s: %s", f, exc)
        return specs

    @router.get("/agents/{name}")
    async def get_agent(name: str) -> dict:
        path = (agents_dir / f"{name}.yaml").resolve()
        if not path.is_relative_to(agents_dir):
            raise HTTPException(status_code=400, detail="Invalid agent name")
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        from everstaff.utils.yaml_loader import load_yaml
        return load_yaml(str(path))

    @router.post("/agents", status_code=201)
    async def create_agent(body: AgentWriteRequest) -> dict:
        name = body.agent_name
        if not name:
            raise HTTPException(status_code=400, detail="agent_name is required")
        path = (agents_dir / f"{name}.yaml").resolve()
        if not path.is_relative_to(agents_dir):
            raise HTTPException(status_code=400, detail="Invalid agent name")
        if path.exists():
            raise HTTPException(status_code=409, detail=f"Agent '{name}' already exists")
        agents_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(_yaml.dump(body.model_dump(exclude_none=True), allow_unicode=True), encoding="utf-8")
        return {"name": name}

    @router.put("/agents/{name}")
    async def update_agent(name: str, body: AgentWriteRequest) -> dict:
        if body.agent_name != name:
            raise HTTPException(status_code=400, detail="agent_name in body must match URL name")
        path = (agents_dir / f"{name}.yaml").resolve()
        if not path.is_relative_to(agents_dir):
            raise HTTPException(status_code=400, detail="Invalid agent name")
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        path.write_text(_yaml.dump(body.model_dump(exclude_none=True), allow_unicode=True), encoding="utf-8")
        return {"name": name, "updated": True}

    @router.delete("/agents/{name}", status_code=204)
    async def delete_agent(name: str) -> None:
        path = (agents_dir / f"{name}.yaml").resolve()
        if not path.is_relative_to(agents_dir):
            raise HTTPException(status_code=400, detail="Invalid agent name")
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        path.unlink()

    return router
