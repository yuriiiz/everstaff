"""Tests for JSON-RPC protocol models."""
import pytest
from everstaff.sandbox.ipc.protocol import (
    JsonRpcRequest,
    JsonRpcNotification,
    JsonRpcResponse,
    JsonRpcError,
    make_request,
    make_notification,
    make_response,
    make_error_response,
    parse_message,
)


class TestJsonRpcModels:
    def test_make_request(self):
        msg = make_request("memory.save", {"session_id": "s1"}, msg_id=1)
        assert msg.jsonrpc == "2.0"
        assert msg.method == "memory.save"
        assert msg.params == {"session_id": "s1"}
        assert msg.id == 1

    def test_make_notification(self):
        msg = make_notification("tracer.event", {"kind": "llm_start"})
        assert msg.jsonrpc == "2.0"
        assert msg.method == "tracer.event"
        assert msg.id is None

    def test_make_response(self):
        msg = make_response({"messages": []}, msg_id=1)
        assert msg.result == {"messages": []}
        assert msg.id == 1
        assert msg.error is None

    def test_make_error_response(self):
        msg = make_error_response(-32601, "Method not found", msg_id=1)
        assert msg.error is not None
        assert msg.error.code == -32601
        assert msg.error.message == "Method not found"
        assert msg.id == 1

    def test_parse_request(self):
        raw = '{"jsonrpc":"2.0","method":"auth","params":{"token":"abc"},"id":1}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcRequest)
        assert msg.method == "auth"

    def test_parse_notification(self):
        raw = '{"jsonrpc":"2.0","method":"tracer.event","params":{"kind":"x"}}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcNotification)
        assert msg.method == "tracer.event"

    def test_parse_response(self):
        raw = '{"jsonrpc":"2.0","result":{"ok":true},"id":1}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcResponse)
        assert msg.result == {"ok": True}

    def test_serialization_roundtrip(self):
        req = make_request("test.method", {"key": "val"}, msg_id=42)
        raw = req.model_dump_json()
        parsed = parse_message(raw)
        assert isinstance(parsed, JsonRpcRequest)
        assert parsed.method == "test.method"
        assert parsed.id == 42
