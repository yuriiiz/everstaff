"""Tests for mem0 wiring in DefaultEnvironment."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_default_env_builds_truncation_when_mem0_disabled(tmp_path):
    from everstaff.builder.environment import DefaultEnvironment
    from everstaff.core.config import FrameworkConfig, MemoryConfig
    from everstaff.memory.strategies import TruncationStrategy

    config = FrameworkConfig(memory=MemoryConfig(enabled=False))
    env = DefaultEnvironment(sessions_dir=str(tmp_path), config=config)
    store = env.build_memory_store()
    assert isinstance(store._strategy, TruncationStrategy)


def test_default_env_builds_mem0_strategy_when_enabled(tmp_path):
    from everstaff.builder.environment import DefaultEnvironment
    from everstaff.core.config import FrameworkConfig, MemoryConfig
    from everstaff.schema.model_config import ModelMapping
    from everstaff.memory.strategies import Mem0ExtractionStrategy

    config = FrameworkConfig(
        memory=MemoryConfig(enabled=True, model_kind="fast"),
        model_mappings={"fast": ModelMapping(model_id="openai/gpt-4.1-nano")},
    )

    with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
        MockMemory.from_config.return_value = MagicMock()
        env = DefaultEnvironment(sessions_dir=str(tmp_path), config=config)
        store = env.build_memory_store()
        assert isinstance(store._strategy, Mem0ExtractionStrategy)


def test_default_env_build_mem0_provider_returns_none_when_disabled(tmp_path):
    from everstaff.builder.environment import DefaultEnvironment
    from everstaff.core.config import FrameworkConfig, MemoryConfig

    config = FrameworkConfig(memory=MemoryConfig(enabled=False))
    env = DefaultEnvironment(sessions_dir=str(tmp_path), config=config)
    assert env.build_mem0_provider() is None


def test_default_env_build_mem0_provider_returns_provider_when_enabled(tmp_path):
    from everstaff.builder.environment import DefaultEnvironment
    from everstaff.core.config import FrameworkConfig, MemoryConfig
    from everstaff.schema.model_config import ModelMapping
    from everstaff.memory.mem0_provider import Mem0Provider

    config = FrameworkConfig(
        memory=MemoryConfig(enabled=True, model_kind="fast"),
        model_mappings={"fast": ModelMapping(model_id="openai/gpt-4.1-nano")},
    )

    with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
        MockMemory.from_config.return_value = MagicMock()
        env = DefaultEnvironment(sessions_dir=str(tmp_path), config=config)
        provider = env.build_mem0_provider(user_id="u1", agent_id="a1")
        assert isinstance(provider, Mem0Provider)


def test_default_env_mem0_client_is_singleton(tmp_path):
    from everstaff.builder.environment import DefaultEnvironment
    from everstaff.core.config import FrameworkConfig, MemoryConfig
    from everstaff.schema.model_config import ModelMapping

    config = FrameworkConfig(
        memory=MemoryConfig(enabled=True, model_kind="fast"),
        model_mappings={"fast": ModelMapping(model_id="openai/gpt-4.1-nano")},
    )

    with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
        MockMemory.from_config.return_value = MagicMock()
        env = DefaultEnvironment(sessions_dir=str(tmp_path), config=config)
        c1 = env._get_or_create_mem0_client()
        c2 = env._get_or_create_mem0_client()
        assert c1 is c2
