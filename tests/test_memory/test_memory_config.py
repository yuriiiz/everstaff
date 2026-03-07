"""Tests for MemoryConfig and migration from memory_dir."""
import pytest
from everstaff.core.config import FrameworkConfig, MemoryConfig


def test_memory_config_defaults():
    cfg = MemoryConfig()
    assert cfg.enabled is False
    assert cfg.model_kind == "fast"
    assert cfg.embedding_model == "text-embedding-3-small"
    assert cfg.vector_store == "faiss"
    assert cfg.vector_store_path == ".agent/memory/vectors"
    assert cfg.search_top_k == 10
    assert cfg.search_threshold == 0.3


def test_framework_config_has_memory():
    cfg = FrameworkConfig()
    assert isinstance(cfg.memory, MemoryConfig)
    assert cfg.memory.enabled is False


def test_framework_config_no_memory_dir():
    """memory_dir field should no longer exist."""
    assert not hasattr(FrameworkConfig(), "memory_dir")
