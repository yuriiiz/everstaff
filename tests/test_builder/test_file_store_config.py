import pytest


def test_new_session_id_ignores_pinned_id(tmp_path):
    """session_id param is deprecated and ignored — new_session_id() always returns fresh UUIDs.
    Session pinning is now handled by AgentBuilder(session_id=...)."""
    from everstaff.builder.environment import CLIEnvironment

    pinned = "parent-session-uuid-1234"
    env = CLIEnvironment(sessions_dir=str(tmp_path), session_id=pinned)

    first = env.new_session_id()
    assert first != pinned, "session_id param should be ignored (deprecated)"

    second = env.new_session_id()
    assert second != pinned, "session_id param should be ignored (deprecated)"
    assert first != second, "Each call must return a different UUID"


def test_new_session_id_without_pinned_always_returns_unique(tmp_path):
    """When no session_id is pinned (normal fresh start), every call returns a unique UUID."""
    from everstaff.builder.environment import CLIEnvironment

    env = CLIEnvironment(sessions_dir=str(tmp_path))
    ids = {env.new_session_id() for _ in range(5)}
    assert len(ids) == 5, f"Expected 5 unique IDs, got {len(ids)}: {ids}"


def test_default_config_builds_local_file_store(tmp_path):
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.storage.local import LocalFileStore

    env = CLIEnvironment(sessions_dir=str(tmp_path))
    store = env.build_file_store()
    assert isinstance(store, LocalFileStore)


def test_cli_environment_build_memory_store_returns_compressible_store(tmp_path):
    """build_memory_store() always returns a CompressibleMemoryStore wrapping FileMemoryStore."""
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.memory.file_store import FileMemoryStore

    env = CLIEnvironment(sessions_dir=str(tmp_path))
    mem = env.build_memory_store()
    # Check by class name to avoid module-path aliasing issues (src.X vs X)
    assert type(mem).__name__ == "CompressibleMemoryStore"
    assert type(mem._store).__name__ == "FileMemoryStore"


def test_cli_environment_build_tracer_uses_config(tmp_path):
    """CLIEnvironment.build_tracer() delegates to factories, returns FileTracer for file-only config."""
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.core.config import FrameworkConfig, TracerConfig
    from everstaff.tracing.file_tracer import FileTracer

    cfg = FrameworkConfig(tracers=[TracerConfig(type="file")])
    env = CLIEnvironment(sessions_dir=str(tmp_path), config=cfg)
    tracer = env.build_tracer(session_id="test-session")
    assert isinstance(tracer, FileTracer)


def test_cli_environment_build_tracer_null_when_no_tracers(tmp_path):
    """CLIEnvironment.build_tracer() returns NullTracer when config has empty tracers list."""
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.core.config import FrameworkConfig
    from everstaff.nulls import NullTracer

    cfg = FrameworkConfig(tracers=[])
    env = CLIEnvironment(sessions_dir=str(tmp_path), config=cfg)
    tracer = env.build_tracer(session_id="test-session")
    assert isinstance(tracer, NullTracer)
