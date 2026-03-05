"""Tests for SandboxEnvironment."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.environment import SandboxEnvironment
from everstaff.sandbox.proxy.memory_store import ProxyMemoryStore
from everstaff.sandbox.proxy.tracer import ProxyTracer
from everstaff.sandbox.proxy.file_store import ProxyFileStore


class TestSandboxEnvironment:
    def test_build_memory_store_returns_proxy(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore({"KEY": "val"})
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        store = env.build_memory_store()
        assert isinstance(store, ProxyMemoryStore)

    def test_build_tracer_returns_proxy(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore()
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        tracer = env.build_tracer(session_id="s1")
        assert isinstance(tracer, ProxyTracer)

    def test_build_file_store_returns_proxy(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore()
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        store = env.build_file_store()
        assert isinstance(store, ProxyFileStore)

    def test_working_dir_returns_workspace(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore()
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        assert env.working_dir("any-session") == tmp_path

    def test_secret_store_property(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore({"API_KEY": "secret123"})
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        assert env.secret_store.get("API_KEY") == "secret123"
