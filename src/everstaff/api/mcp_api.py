"""MCP management API — templates CRUD, connection test, per-agent servers."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml as _yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from everstaff.utils.yaml_loader import load_yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AddMCPServerRequest(BaseModel):
    model_config = {"extra": "allow"}
    name: str | None = None
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    icon: str | None = None
    template: str | None = None  # If set, install from template


class UpdateMCPServerRequest(BaseModel):
    model_config = {"extra": "allow"}
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    icon: str | None = None


class TestConnectionRequest(BaseModel):
    name: str = "test"
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    icon: str | None = None


class CreateTemplateRequest(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    icon: str = ""
    category: str = "general"
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    required_env: list[dict] = Field(default_factory=list)


class UpdateTemplateRequest(BaseModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    icon: str = ""
    category: str = "general"
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    required_env: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def make_router(config) -> APIRouter:
    agents_dir = Path(config.agents_dir).expanduser().resolve()
    router = APIRouter(tags=["mcp"])

    # ------------------------------------------------------------------
    # Template manager helper
    # ------------------------------------------------------------------

    def _template_mgr():
        from everstaff.mcp_client.templates import MCPTemplateManager
        dirs = list(config.mcp_templates_dirs)
        # Resolve the builtin package path to compare against it explicitly
        builtin_path: str | None = None
        try:
            import everstaff as _pkg
            builtin_path = str(Path(_pkg.__file__).parent / "builtin_mcp_templates")
        except Exception:
            pass
        user_dir: str | None = None
        for d in dirs:
            if builtin_path and str(Path(d).expanduser().resolve()) == str(Path(builtin_path).resolve()):
                continue
            user_dir = d
            break
        return MCPTemplateManager(template_dirs=dirs, user_dir=user_dir)

    # ------------------------------------------------------------------
    # Templates endpoints
    # ------------------------------------------------------------------

    @router.get("/mcp/templates")
    async def list_templates() -> list[dict]:
        mgr = _template_mgr()
        items = mgr.list_with_source()
        return [
            {**item["template"].model_dump(), "source": item["source"]}
            for item in items
        ]

    @router.get("/mcp/templates/{name}")
    async def get_template(name: str) -> dict:
        mgr = _template_mgr()
        try:
            tpl = mgr.get(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
        return tpl.model_dump()

    @router.post("/mcp/templates", status_code=201)
    async def create_template(body: CreateTemplateRequest) -> dict:
        from everstaff.mcp_client.templates import MCPTemplate
        mgr = _template_mgr()
        tpl = MCPTemplate(**body.model_dump())
        try:
            path = mgr.create(tpl)
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Template '{body.name}' already exists")
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"name": body.name, "path": str(path)}

    @router.put("/mcp/templates/{name}")
    async def update_template(name: str, body: UpdateTemplateRequest) -> dict:
        from everstaff.mcp_client.templates import MCPTemplate
        mgr = _template_mgr()
        # Build template with the URL name as the canonical name
        data = body.model_dump()
        data["name"] = name
        tpl = MCPTemplate(**data)
        try:
            mgr.update(name, tpl)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"name": name, "updated": True}

    @router.delete("/mcp/templates/{name}", status_code=204)
    async def delete_template(name: str) -> None:
        mgr = _template_mgr()
        try:
            mgr.delete(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))

    # ------------------------------------------------------------------
    # Connection test endpoint
    # ------------------------------------------------------------------

    @router.post("/mcp/test")
    async def test_connection(body: TestConnectionRequest) -> dict:
        from everstaff.schema.agent_spec import MCPServerSpec
        from everstaff.mcp_client.connection import MCPConnection

        spec = MCPServerSpec(
            name=body.name,
            transport=body.transport,
            command=body.command,
            args=body.args,
            env=body.env,
            url=body.url,
            headers=body.headers,
        )
        conn = MCPConnection(spec)
        try:
            tools = await asyncio.wait_for(conn.connect(), timeout=15)
            tool_list = [
                {
                    "name": t.definition.name,
                    "description": t.definition.description,
                }
                for t in tools
            ]
            return {"success": True, "tools": tool_list, "tool_count": len(tool_list)}
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Connection timed out (15s)")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Connection failed: {e}")
        finally:
            await conn.disconnect()

    # ------------------------------------------------------------------
    # Per-agent MCP server management
    # ------------------------------------------------------------------

    def _load_agent_yaml(agent_name: str) -> tuple[dict, Path]:
        """Load agent YAML, return (data, path). Raises HTTPException on error."""
        path = (agents_dir / f"{agent_name}.yaml").resolve()
        if not path.is_relative_to(agents_dir):
            raise HTTPException(status_code=400, detail="Invalid agent name")
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        data = load_yaml(str(path))
        return data, path

    def _save_agent_yaml(data: dict, path: Path) -> None:
        """Write agent YAML back to disk."""
        path.write_text(
            _yaml.dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    @router.get("/agents/{agent_name}/mcp-servers")
    async def list_agent_mcp_servers(agent_name: str) -> list[dict]:
        data, _path = _load_agent_yaml(agent_name)
        return data.get("mcp_servers", [])

    @router.post("/agents/{agent_name}/mcp-servers", status_code=201)
    async def add_agent_mcp_server(agent_name: str, body: AddMCPServerRequest) -> dict:
        data, path = _load_agent_yaml(agent_name)
        servers: list[dict] = data.get("mcp_servers", [])

        if body.template:
            # Install from template
            mgr = _template_mgr()
            try:
                tpl = mgr.get(body.template)
            except FileNotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail=f"Template '{body.template}' not found",
                )
            spec = tpl.to_server_spec(env_overrides=body.env or None)
            server_dict = spec.model_dump()
        else:
            if not body.name:
                raise HTTPException(
                    status_code=400,
                    detail="'name' is required when not using a template",
                )
            server_dict = body.model_dump(exclude={"template"}, exclude_none=True)
            server_dict.setdefault("name", body.name)

        server_name = server_dict.get("name", "")
        # Check for duplicate name
        for existing in servers:
            if existing.get("name") == server_name:
                raise HTTPException(
                    status_code=409,
                    detail=f"MCP server '{server_name}' already exists on agent '{agent_name}'",
                )

        servers.append(server_dict)
        data["mcp_servers"] = servers
        _save_agent_yaml(data, path)
        return {"name": server_name, "agent": agent_name}

    @router.put("/agents/{agent_name}/mcp-servers/{server_name}")
    async def update_agent_mcp_server(
        agent_name: str, server_name: str, body: UpdateMCPServerRequest
    ) -> dict:
        data, path = _load_agent_yaml(agent_name)
        servers: list[dict] = data.get("mcp_servers", [])

        found_idx: int | None = None
        for i, s in enumerate(servers):
            if s.get("name") == server_name:
                found_idx = i
                break
        if found_idx is None:
            raise HTTPException(
                status_code=404,
                detail=f"MCP server '{server_name}' not found on agent '{agent_name}'",
            )

        updated = body.model_dump(exclude_none=True)
        updated.setdefault("name", body.name)
        servers[found_idx] = updated
        data["mcp_servers"] = servers
        _save_agent_yaml(data, path)
        return {"name": server_name, "agent": agent_name, "updated": True}

    @router.delete("/agents/{agent_name}/mcp-servers/{server_name}", status_code=204)
    async def delete_agent_mcp_server(agent_name: str, server_name: str) -> None:
        data, path = _load_agent_yaml(agent_name)
        servers: list[dict] = data.get("mcp_servers", [])

        new_servers = [s for s in servers if s.get("name") != server_name]
        if len(new_servers) == len(servers):
            raise HTTPException(
                status_code=404,
                detail=f"MCP server '{server_name}' not found on agent '{agent_name}'",
            )

        data["mcp_servers"] = new_servers
        _save_agent_yaml(data, path)

    return router
