"""Test extra_permissions persistence in FileMemoryStore."""
import json
import pytest


@pytest.fixture
def tmp_memory(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(str(tmp_path))
    return FileMemoryStore(store)


@pytest.mark.asyncio
async def test_save_and_load_extra_permissions(tmp_memory):
    from everstaff.protocols import Message
    sid = "test-session-001"
    msgs = [Message(role="user", content="hello")]
    await tmp_memory.save(sid, msgs, extra_permissions=["Bash", "Write"])

    raw = await tmp_memory._session_store.read(f"{sid}/session.json")
    data = json.loads(raw.decode())
    assert data.get("extra_permissions") == ["Bash", "Write"]


@pytest.mark.asyncio
async def test_extra_permissions_preserved_on_re_save(tmp_memory):
    from everstaff.protocols import Message
    sid = "test-session-002"
    msgs = [Message(role="user", content="hello")]
    await tmp_memory.save(sid, msgs, extra_permissions=["Bash"])
    await tmp_memory.save(sid, msgs)  # no extra_permissions kwarg

    raw = await tmp_memory._session_store.read(f"{sid}/session.json")
    data = json.loads(raw.decode())
    assert data.get("extra_permissions") == ["Bash"]
