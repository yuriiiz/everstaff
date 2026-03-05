"""Tests for MCP connection environment resolution via SecretStore."""
import pytest
from everstaff.core.secret_store import SecretStore
from everstaff.schema.agent_spec import MCPServerSpec
from everstaff.mcp_client.connection import MCPConnection


class TestMCPConnectionEnvResolution:
    def test_resolve_env_from_secret_store(self):
        """MCPServerSpec.env references should resolve from SecretStore."""
        store = SecretStore({"MY_TOKEN": "tok-123", "OTHER": "val"})
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"TOKEN": "${MY_TOKEN}"},
            transport="stdio",
        )
        conn = MCPConnection(spec, secret_store=store)
        resolved = conn._resolve_spec_env()
        assert resolved == {"TOKEN": "tok-123"}

    def test_resolve_env_literal_values_unchanged(self):
        """Literal env values (no ${}) should pass through unchanged."""
        store = SecretStore({"X": "y"})
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"LITERAL": "hello-world"},
            transport="stdio",
        )
        conn = MCPConnection(spec, secret_store=store)
        resolved = conn._resolve_spec_env()
        assert resolved == {"LITERAL": "hello-world"}

    def test_resolve_env_missing_secret_raises(self):
        """Referencing a missing secret should raise ValueError."""
        store = SecretStore({})
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"TOKEN": "${MISSING_KEY}"},
            transport="stdio",
        )
        conn = MCPConnection(spec, secret_store=store)
        with pytest.raises(ValueError, match="MISSING_KEY"):
            conn._resolve_spec_env()

    def test_no_secret_store_falls_back_to_spec_env(self):
        """Without SecretStore, use spec.env as-is (backward compat)."""
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"PLAIN": "value"},
            transport="stdio",
        )
        conn = MCPConnection(spec)  # no secret_store
        resolved = conn._resolve_spec_env()
        assert resolved == {"PLAIN": "value"}

    def test_empty_env_returns_none(self):
        """Empty spec.env should return None."""
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            transport="stdio",
        )
        conn = MCPConnection(spec)
        resolved = conn._resolve_spec_env()
        assert resolved is None
