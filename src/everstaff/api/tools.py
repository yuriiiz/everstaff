"""Tools management API — thin layer over ToolManager."""
from __future__ import annotations

import ast
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from everstaff.tools.manager import ToolManager

logger = logging.getLogger(__name__)


class CreateToolRequest(BaseModel):
    name: str
    description: str = ""
    content: Optional[str] = None


class UpdateToolRequest(BaseModel):
    content: str


def _validate_tool_content(content: str, name: str) -> str | None:
    try:
        ast.parse(content)
    except SyntaxError as e:
        return f"Syntax error: {e}"
    exec_globals: dict = {}
    try:
        exec(compile(content, f"{name}.py", "exec"), exec_globals)
    except Exception as e:
        return f"Load error: {e}"
    if "TOOLS" not in exec_globals:
        return "Missing TOOLS variable"
    return None


def make_router(config) -> APIRouter:
    router = APIRouter(tags=["tools"], prefix="/tools")

    def _mgr() -> ToolManager:
        return ToolManager(config.tools_dirs)

    @router.get("")
    async def list_tools() -> list[dict]:
        return _mgr().list()

    @router.get("/{name}")
    async def get_tool(name: str) -> dict:
        try:
            return {"name": name, "content": _mgr().get_source(name)}
        except FileNotFoundError:
            raise HTTPException(404, f"Tool '{name}' not found")

    @router.post("", status_code=201)
    async def create_tool(body: CreateToolRequest) -> dict:
        mgr = _mgr()
        if mgr.primary_dir() is None:
            raise HTTPException(500, "No tools directories configured")
        if body.content:
            if error := _validate_tool_content(body.content, body.name):
                raise HTTPException(400, f"Tool validation failed: {error}")
        try:
            path = mgr.create(body.name, body.description, body.content)
        except FileExistsError:
            raise HTTPException(409, f"Tool '{body.name}' already exists")
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        return {"name": body.name, "file": str(path)}

    @router.put("/{name}")
    async def update_tool(name: str, body: UpdateToolRequest) -> dict:
        if error := _validate_tool_content(body.content, name):
            raise HTTPException(400, f"Tool validation failed: {error}")
        try:
            _mgr().update(name, body.content)
        except FileNotFoundError:
            raise HTTPException(404, f"Tool '{name}' not found")
        return {"name": name, "updated": True}

    @router.delete("/{name}", status_code=204)
    async def delete_tool(name: str) -> None:
        try:
            _mgr().delete(name)
        except FileNotFoundError:
            raise HTTPException(404, f"Tool '{name}' not found")

    return router
