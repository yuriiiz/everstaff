"""Tools management API — thin layer over ToolManager."""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import sys
import tempfile
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from everstaff.tools.manager import ToolManager

logger = logging.getLogger(__name__)

_VALIDATE_TIMEOUT = 10  # seconds


class CreateToolRequest(BaseModel):
    name: str
    description: str = ""
    content: Optional[str] = None


class UpdateToolRequest(BaseModel):
    content: str


async def _validate_tool_content(content: str, name: str) -> str | None:
    """Validate tool content by loading it in an isolated subprocess.

    Steps:
    1. AST parse (fast, catches syntax errors).
    2. Spawn a short-lived subprocess that imports the temp file and checks
       for a ``TOOLS`` variable.  The subprocess is killed after a timeout
       so malicious code cannot hang the API server.
    """
    try:
        ast.parse(content)
    except SyntaxError as e:
        return f"Syntax error: {e}"

    # Write content to a temp file and validate in a subprocess
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=f"es-tool-{name}-", delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    # Subprocess script: import the module and check for TOOLS
    check_script = (
        "import importlib.util, sys, json, os\n"
        "spec = importlib.util.spec_from_file_location('_tool', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "tools = getattr(mod, 'TOOLS', None)\n"
        "if tools is None:\n"
        "    print(json.dumps({'error': 'Missing TOOLS variable'}))\n"
        "else:\n"
        "    print(json.dumps({'ok': True, 'count': len(tools)}))\n"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", check_script, tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_VALIDATE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return "Validation timed out (possible infinite loop or heavy import)"

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            # Truncate long tracebacks
            if len(err) > 500:
                err = err[:500] + "..."
            return f"Load error: {err}"

        result = json.loads(stdout.decode())
        if "error" in result:
            return result["error"]
        return None

    except Exception as e:
        return f"Validation error: {e}"
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def make_router(config) -> APIRouter:
    router = APIRouter(tags=["tools"], prefix="/tools")

    def _mgr() -> ToolManager:
        return ToolManager(config.tools_dirs)

    @router.get("")
    async def list_tools() -> list[dict]:
        return _mgr().list()

    @router.get("/lark")
    async def list_lark_tools(categories: str | None = None) -> dict:
        """Return available Feishu/Lark tool metadata by category."""
        from everstaff.tools.feishu.tools.registry import list_all_tools
        cats = [c.strip() for c in categories.split(",")] if categories else None
        return {"categories": list_all_tools(categories=cats)}

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
            if error := await _validate_tool_content(body.content, body.name):
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
        if error := await _validate_tool_content(body.content, name):
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
