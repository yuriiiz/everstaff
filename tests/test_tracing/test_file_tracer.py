import json
from pathlib import Path
import pytest
from everstaff.protocols import TraceEvent


def make_event(kind: str, session_id: str = "s1") -> TraceEvent:
    return TraceEvent(kind=kind, session_id=session_id, data={"x": 1})


def test_file_tracer_writes_to_session_file(tmp_path):
    from everstaff.tracing.file_tracer import FileTracer
    session_path = tmp_path / "s1" / "traces.jsonl"
    global_path = tmp_path / "traces.jsonl"
    tracer = FileTracer(session_path=session_path, global_path=global_path)
    tracer.on_event(make_event("tool_start"))

    assert session_path.exists()
    lines = session_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "tool_start"


def test_file_tracer_writes_to_global_file(tmp_path):
    from everstaff.tracing.file_tracer import FileTracer
    session_path = tmp_path / "s1" / "traces.jsonl"
    global_path = tmp_path / "traces.jsonl"
    tracer = FileTracer(session_path=session_path, global_path=global_path)
    tracer.on_event(make_event("llm_end", session_id="s1"))
    tracer.on_event(make_event("llm_end", session_id="s2"))

    lines = global_path.read_text().strip().splitlines()
    assert len(lines) == 2


def test_file_tracer_appends_multiple_events(tmp_path):
    from everstaff.tracing.file_tracer import FileTracer
    sp = tmp_path / "s1" / "traces.jsonl"
    gp = tmp_path / "traces.jsonl"
    tracer = FileTracer(session_path=sp, global_path=gp)
    tracer.on_event(make_event("session_start"))
    tracer.on_event(make_event("session_end"))
    lines = sp.read_text().strip().splitlines()
    assert len(lines) == 2


def test_composite_tracer_fans_out(tmp_path):
    from everstaff.tracing.composite import CompositeTracer
    received = []

    class SpyTracer:
        def on_event(self, event):
            received.append(event.kind)

    ct = CompositeTracer([SpyTracer(), SpyTracer()])
    ct.on_event(make_event("tool_start"))
    assert received == ["tool_start", "tool_start"]


def test_composite_tracer_continues_on_backend_error(tmp_path):
    from everstaff.tracing.composite import CompositeTracer
    received = []

    class BrokenTracer:
        def on_event(self, event):
            raise RuntimeError("boom")

    class GoodTracer:
        def on_event(self, event):
            received.append(event.kind)

    ct = CompositeTracer([BrokenTracer(), GoodTracer()])
    ct.on_event(make_event("tool_start"))   # should not raise
    assert received == ["tool_start"]       # good tracer still ran


def test_file_tracer_global_write_survives_session_write_failure(tmp_path):
    """If session path write fails, global path should still be written."""
    from everstaff.tracing.file_tracer import FileTracer

    # Use an invalid session path (a file as a directory component)
    bad_session_path = tmp_path / "not_a_dir.txt" / "s1" / "traces.jsonl"
    bad_session_path.parent.parent.touch()  # make "not_a_dir.txt" a file so mkdir fails

    global_path = tmp_path / "traces.jsonl"
    tracer = FileTracer(session_path=bad_session_path, global_path=global_path)
    tracer.on_event(TraceEvent(kind="test_event", session_id="s1"))

    # Global file should still be written even though session write failed
    assert global_path.exists()
    lines = global_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "test_event"


def test_cli_environment_build_tracer_returns_file_tracer(tmp_path):
    """With default single-file config, factory returns FileTracer directly (no CompositeTracer wrapping)."""
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.tracing.file_tracer import FileTracer
    env = CLIEnvironment(sessions_dir=str(tmp_path))  # default config uses file tracer
    tracer = env.build_tracer("sess-xyz")
    assert isinstance(tracer, FileTracer)


@pytest.mark.asyncio
async def test_file_tracer_accepts_file_store(tmp_path):
    """FileTracer works with FileStore injection."""
    from everstaff.storage.local import LocalFileStore
    from everstaff.tracing.file_tracer import FileTracer
    from everstaff.protocols import TraceEvent

    store = LocalFileStore(tmp_path)
    tracer = FileTracer(
        store=store,
        session_path="sess-123/traces.jsonl",
        global_path="traces.jsonl",
    )
    event = TraceEvent(kind="test_event", session_id="sess-123", data={})
    tracer.on_event(event)
    await tracer.aflush()  # force async flush

    content = (await store.read("sess-123/traces.jsonl")).decode()
    assert "test_event" in content


@pytest.mark.asyncio
async def test_file_tracer_flushes_after_time_threshold(tmp_path):
    """FileTracer must flush buffer when last flush was more than 10 seconds ago."""
    import time
    from everstaff.storage.local import LocalFileStore
    from everstaff.tracing.file_tracer import FileTracer
    from everstaff.protocols import TraceEvent

    store = LocalFileStore(tmp_path)
    tracer = FileTracer(
        store=store,
        session_path="sess/traces.jsonl",
        global_path="traces.jsonl",
        flush_interval=100,  # high threshold so count alone won't trigger
    )

    # Backdate the last flush time to simulate 11 seconds elapsed
    tracer._last_flush_time = time.monotonic() - 11

    event = TraceEvent(kind="time_triggered", session_id="sess", data={})
    tracer.on_event(event)

    # Give any scheduled task a chance to run
    import asyncio
    await asyncio.sleep(0.05)

    content = (await store.read("sess/traces.jsonl")).decode()
    assert "time_triggered" in content, "Buffer was not flushed despite 10s time threshold"
