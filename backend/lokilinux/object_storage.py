"""
LokiLinux — Centralized S3-compatible object storage client.

Single vendor-neutral wrapper over boto3's S3 client: swapping RustFS for AWS
S3 / Cloudflare R2 / Wasabi is a config change (S3_ENDPOINT_URL), never a code
change. Business logic never imports boto3 directly — it goes through
lokilinux.services.storage_service, which is the only caller of this module.

boto3 is a sync client; every network call here is wrapped in
asyncio.to_thread, same rationale as lokilinux.ch.ClickHouseStore (no
maintained async S3 client pinned for this project). upload_fileobj /
download_fileobj use boto3's TransferConfig, which handles multipart
upload/download transparently above the configured threshold — there is no
hand-rolled multipart code here.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from typing import IO, Any, AsyncIterator

import boto3
import structlog
from boto3.s3.transfer import TransferConfig
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

logger = structlog.get_logger()

# Object keys are always our own construction (never taken verbatim from a
# client-supplied filename) — this still guards against a future caller
# passing an unsanitized key straight through.
_INVALID_KEY_RE = re.compile(r"(^/|(^|/)\.\.(/|$)|\x00)")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Strip any path components and replace unsafe characters — defends
    against path traversal and null-byte injection from a user-supplied
    original filename before it's used to build an object key."""
    name = name.replace("\x00", "")
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = _SAFE_FILENAME_RE.sub("_", name).strip("._") or "file"
    return name[:max_length]


def validate_key(key: str) -> None:
    """Raise ValueError if an object key attempts path traversal, is
    absolute, or contains a NUL byte."""
    if not key or _INVALID_KEY_RE.search(key):
        raise ValueError(f"invalid object key: {key!r}")


@dataclass
class ObjectMeta:
    key: str
    size_bytes: int
    content_type: str | None
    etag: str | None
    last_modified: datetime | None
    metadata: dict[str, str]


class ObjectStorage:
    """Thin async wrapper over an S3-compatible bucket."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        addressing_style: str = "path",
        public_endpoint_url: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.public_endpoint_url = public_endpoint_url or None
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(
                s3={"addressing_style": addressing_style},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        # Presigned URLs must be signed against the endpoint a browser can
        # actually reach — falls back to the internal endpoint_url when no
        # public one is configured (self-hosted RustFS on an internal network).
        self._presign_client = (
            boto3.client(
                "s3",
                endpoint_url=self.public_endpoint_url,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=BotoConfig(s3={"addressing_style": addressing_style}),
            )
            if self.public_endpoint_url
            else self._client
        )
        self._transfer_config = TransferConfig(
            multipart_threshold=8 * 1024 * 1024,
            max_concurrency=4,
            multipart_chunksize=8 * 1024 * 1024,
        )

    async def ensure_bucket(self) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self.bucket)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status != 404:
                raise
            await asyncio.to_thread(self._client.create_bucket, Bucket=self.bucket)
            logger.info("storage.bucket_created", bucket=self.bucket)

    async def put_stream(
        self,
        key: str,
        fileobj: IO[bytes],
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        validate_key(key)
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = metadata
        await asyncio.to_thread(
            self._client.upload_fileobj,
            fileobj,
            self.bucket,
            key,
            ExtraArgs=extra_args or None,
            Config=self._transfer_config,
        )

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        validate_key(key)
        obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        body = obj["Body"]

        async def _iter() -> AsyncIterator[bytes]:
            try:
                while True:
                    chunk = await asyncio.to_thread(body.read, 1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(body.close)

        return _iter()

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        validate_key(key)
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise

    async def head(self, key: str) -> ObjectMeta:
        validate_key(key)
        resp = await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
        return ObjectMeta(
            key=key,
            size_bytes=resp["ContentLength"],
            content_type=resp.get("ContentType"),
            etag=resp.get("ETag"),
            last_modified=resp.get("LastModified"),
            metadata=resp.get("Metadata", {}),
        )

    async def list(self, prefix: str, *, max_keys: int = 1000) -> list[ObjectMeta]:
        resp = await asyncio.to_thread(
            self._client.list_objects_v2, Bucket=self.bucket, Prefix=prefix, MaxKeys=max_keys
        )
        return [
            ObjectMeta(
                key=item["Key"],
                size_bytes=item["Size"],
                content_type=None,
                etag=item.get("ETag"),
                last_modified=item.get("LastModified"),
                metadata={},
            )
            for item in resp.get("Contents", [])
        ]

    async def presign_get(self, key: str, *, expires_in: int) -> str:
        validate_key(key)
        return await asyncio.to_thread(
            self._presign_client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def presign_put(
        self, key: str, *, expires_in: int, content_type: str | None = None
    ) -> str:
        validate_key(key)
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return await asyncio.to_thread(
            self._presign_client.generate_presigned_url,
            "put_object",
            Params=params,
            ExpiresIn=expires_in,
        )
