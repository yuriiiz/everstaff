"""Memories API — read-only endpoints for querying mem0 memories."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "default"


def _resolve_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is not None:
        return user.user_id
    return DEFAULT_USER_ID


def _get_mem0_client(request: Request):
    return getattr(request.app.state, "mem0_client", None)


def _merge_memories(user_results: list[dict], default_results: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for m in user_results:
        by_id[m["id"]] = m
    for m in default_results:
        if m["id"] not in by_id:
            by_id[m["id"]] = m
    return list(by_id.values())


def _merge_search_results(user_results: list[dict], default_results: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for m in user_results:
        by_id[m["id"]] = m
    for m in default_results:
        mid = m["id"]
        if mid not in by_id or m.get("score", 0) > by_id[mid].get("score", 0):
            by_id[mid] = m
    return list(by_id.values())


async def _list_merged(client, user_id: str, limit: int, **scope) -> list[dict]:
    if user_id == DEFAULT_USER_ID:
        return await client.get_all(user_id=DEFAULT_USER_ID, limit=limit, **scope)
    user_results, default_results = await asyncio.gather(
        client.get_all(user_id=user_id, limit=limit, **scope),
        client.get_all(user_id=DEFAULT_USER_ID, limit=limit, **scope),
    )
    return _merge_memories(user_results, default_results)


async def _search_merged(client, query: str, user_id: str, limit: int, **scope) -> list[dict]:
    if user_id == DEFAULT_USER_ID:
        return await client.search(query, user_id=DEFAULT_USER_ID, top_k=limit, **scope)
    user_results, default_results = await asyncio.gather(
        client.search(query, user_id=user_id, top_k=limit, **scope),
        client.search(query, user_id=DEFAULT_USER_ID, top_k=limit, **scope),
    )
    return _merge_search_results(user_results, default_results)


def make_router() -> APIRouter:
    router = APIRouter(tags=["memories"])

    @router.get("/memories")
    async def list_memories(
        request: Request,
        limit: int = Query(default=100, le=100, ge=1),
    ) -> dict:
        client = _get_mem0_client(request)
        if client is None:
            return {"memories": []}
        user_id = _resolve_user_id(request)
        memories = await _list_merged(client, user_id, limit)
        return {"memories": memories}

    @router.get("/memories/search")
    async def search_memories(
        request: Request,
        q: str = Query(...),
        limit: int = Query(default=10, le=100, ge=1),
    ) -> dict:
        client = _get_mem0_client(request)
        if client is None:
            return {"memories": []}
        user_id = _resolve_user_id(request)
        memories = await _search_merged(client, q, user_id, limit)
        return {"memories": memories}

    @router.get("/agents/{agent_uuid}/memories")
    async def list_agent_memories(
        request: Request,
        agent_uuid: str,
        limit: int = Query(default=100, le=100, ge=1),
    ) -> dict:
        client = _get_mem0_client(request)
        if client is None:
            return {"memories": []}
        user_id = _resolve_user_id(request)
        memories = await _list_merged(client, user_id, limit, agent_id=agent_uuid)
        return {"memories": memories}

    @router.get("/agents/{agent_uuid}/memories/search")
    async def search_agent_memories(
        request: Request,
        agent_uuid: str,
        q: str = Query(...),
        limit: int = Query(default=10, le=100, ge=1),
    ) -> dict:
        client = _get_mem0_client(request)
        if client is None:
            return {"memories": []}
        user_id = _resolve_user_id(request)
        memories = await _search_merged(client, q, user_id, limit, agent_id=agent_uuid)
        return {"memories": memories}

    return router
