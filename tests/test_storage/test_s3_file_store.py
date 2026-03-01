import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")


@pytest.fixture
def s3_store():
    from moto import mock_aws
    import boto3
    from everstaff.storage.s3 import S3FileStore
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield S3FileStore(bucket="test-bucket", prefix="sessions", region="us-east-1")


@pytest.mark.asyncio
async def test_s3_write_and_read(s3_store):
    await s3_store.write("sess-1/session.json", b'{"hello": "world"}')
    result = await s3_store.read("sess-1/session.json")
    assert result == b'{"hello": "world"}'


@pytest.mark.asyncio
async def test_s3_exists(s3_store):
    assert not await s3_store.exists("foo.json")
    await s3_store.write("foo.json", b"x")
    assert await s3_store.exists("foo.json")


@pytest.mark.asyncio
async def test_s3_delete(s3_store):
    await s3_store.write("del.json", b"x")
    await s3_store.delete("del.json")
    assert not await s3_store.exists("del.json")


@pytest.mark.asyncio
async def test_s3_list(s3_store):
    await s3_store.write("sess-a/session.json", b"{}")
    await s3_store.write("sess-a/hitl.json", b"{}")
    await s3_store.write("sess-b/session.json", b"{}")
    items = await s3_store.list("sess-a/")
    assert sorted(items) == ["sess-a/hitl.json", "sess-a/session.json"]
