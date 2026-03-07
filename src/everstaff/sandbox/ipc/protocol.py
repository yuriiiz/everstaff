"""JSON-RPC 2.0 message models for sandbox IPC."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = {}
    id: int | str | None = None


class JsonRpcNotification(BaseModel):
    """Like JsonRpcRequest but id is always None (no response expected)."""
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = {}
    id: None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: Any | None = None
    error: JsonRpcError | None = None
    id: int | str | None = None


def make_request(method: str, params: dict[str, Any], msg_id: int | str) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, params=params, id=msg_id)


def make_notification(method: str, params: dict[str, Any]) -> JsonRpcNotification:
    return JsonRpcNotification(method=method, params=params)


def make_response(result: Any, msg_id: int | str) -> JsonRpcResponse:
    return JsonRpcResponse(result=result, id=msg_id)


def make_error_response(code: int, message: str, msg_id: int | str | None = None, data: Any = None) -> JsonRpcResponse:
    return JsonRpcResponse(error=JsonRpcError(code=code, message=message, data=data), id=msg_id)


def parse_message(raw: str) -> JsonRpcRequest | JsonRpcNotification | JsonRpcResponse:
    """Parse a JSON-RPC message from raw JSON string."""
    data = json.loads(raw)
    if "method" in data:
        if data.get("id") is not None:
            return JsonRpcRequest.model_validate(data)
        return JsonRpcNotification.model_validate(data)
    return JsonRpcResponse.model_validate(data)
