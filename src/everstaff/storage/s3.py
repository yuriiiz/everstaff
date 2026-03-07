"""S3FileStore — FileStore implementation backed by AWS S3 (or compatible)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class S3FileStore:
    """
    FileStore backed by S3. Paths are relative; stored as {prefix}/{path} in the bucket.

    boto3 is a lazy import (optional dependency).
    Credentials fall back to standard boto3 credential chain if not specified.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._region = region
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._client: Any = None  # lazy init
        self._botocore_exc: Any = None  # lazy init alongside client

    def _get_client(self):
        if self._client is None:
            import boto3
            import botocore.exceptions
            self._botocore_exc = botocore.exceptions
            kwargs: dict[str, Any] = {"region_name": self._region}
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            if self._access_key_id and self._secret_access_key:
                kwargs["aws_access_key_id"] = self._access_key_id
                kwargs["aws_secret_access_key"] = self._secret_access_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _key(self, path: str) -> str:
        return f"{self._prefix}/{path}" if self._prefix else path

    async def read(self, path: str) -> bytes:
        def _read() -> bytes:
            response = self._get_client().get_object(Bucket=self._bucket, Key=self._key(path))
            return response["Body"].read()
        return await asyncio.to_thread(_read)

    async def write(self, path: str, data: bytes) -> None:
        await asyncio.to_thread(
            self._get_client().put_object,
            Bucket=self._bucket,
            Key=self._key(path),
            Body=data,
        )

    async def append(self, path: str, data: bytes) -> None:
        """S3 has no native append — read-modify-write."""
        try:
            existing = await self.read(path)
        except Exception:
            existing = b""
        await self.write(path, existing + data)

    async def exists(self, path: str) -> bool:
        def _exists() -> bool:
            try:
                self._get_client().head_object(Bucket=self._bucket, Key=self._key(path))
                return True
            except self._botocore_exc.ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return False
                raise
        # Ensure client (and botocore_exc) is initialised before entering thread
        self._get_client()
        return await asyncio.to_thread(_exists)

    async def delete(self, path: str) -> None:
        await asyncio.to_thread(
            self._get_client().delete_object,
            Bucket=self._bucket,
            Key=self._key(path),
        )

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            full_prefix = self._key(prefix)
            paginator = self._get_client().get_paginator("list_objects_v2")
            results = []
            for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    rel = key[len(self._prefix) + 1:] if self._prefix else key
                    results.append(rel)
            return results
        return await asyncio.to_thread(_list)
