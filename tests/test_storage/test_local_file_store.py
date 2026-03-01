import pytest

@pytest.mark.asyncio
async def test_write_and_read(tmp_path):
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(tmp_path)
    await store.write("foo/bar.txt", b"hello")
    result = await store.read("foo/bar.txt")
    assert result == b"hello"

@pytest.mark.asyncio
async def test_exists(tmp_path):
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(tmp_path)
    assert not await store.exists("foo.txt")
    await store.write("foo.txt", b"data")
    assert await store.exists("foo.txt")

@pytest.mark.asyncio
async def test_delete(tmp_path):
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(tmp_path)
    await store.write("del.txt", b"x")
    await store.delete("del.txt")
    assert not await store.exists("del.txt")

@pytest.mark.asyncio
async def test_list(tmp_path):
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(tmp_path)
    await store.write("sess-1/session.json", b"{}")
    await store.write("sess-2/session.json", b"{}")
    await store.write("sess-1/hitl.json", b"{}")
    items = await store.list("sess-1/")
    assert sorted(items) == ["sess-1/hitl.json", "sess-1/session.json"]

@pytest.mark.asyncio
async def test_write_creates_parent_dirs(tmp_path):
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(tmp_path)
    await store.write("deep/nested/file.txt", b"content")
    assert (tmp_path / "deep" / "nested" / "file.txt").exists()

@pytest.mark.asyncio
async def test_list_cannot_escape_base(tmp_path):
    """list() raises ValueError when prefix would escape base_dir."""
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(tmp_path / "subdir")
    with pytest.raises(ValueError, match="escapes base directory"):
        await store.list("../")
