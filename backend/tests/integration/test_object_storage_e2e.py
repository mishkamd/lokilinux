"""E2E test for the object-storage layer against a REAL S3-compatible server
(RustFS) — the unit/integration suite only ever sees FakeObjectStorage, so the
multipart path (boto3 TransferConfig above the threshold) was never exercised
end to end (MIS-149).

Skipped unless the server is configured:

    S3_E2E_ENDPOINT   e.g. http://127.0.0.1:9000
    S3_E2E_ACCESS_KEY / S3_E2E_SECRET_KEY / S3_E2E_BUCKET (optional, default
    "lokilinux-e2e")

The upload deliberately exceeds the multipart threshold (8 MB) so boto3
really does a multipart upload, then the object is read back, verified by
SHA-256 and deleted.
"""

import hashlib
import os
from io import BytesIO
from typing import Any

import pytest

from lokilinux.object_storage import ObjectStorage

_ENDPOINT = os.environ.get("S3_E2E_ENDPOINT")
pytestmark = pytest.mark.skipif(
    not _ENDPOINT, reason="S3_E2E_ENDPOINT not set — real-object-storage test skipped"
)

# Comfortably above the 8 MB multipart threshold in ObjectStorage.
_PAYLOAD_SIZE = 12 * 1024 * 1024


@pytest.fixture
async def storage() -> Any:
    store = ObjectStorage(
        endpoint_url=_ENDPOINT or "",
        region=os.environ.get("S3_E2E_REGION", "us-east-1"),
        access_key=os.environ.get("S3_E2E_ACCESS_KEY", ""),
        secret_key=os.environ.get("S3_E2E_SECRET_KEY", ""),
        bucket=os.environ.get("S3_E2E_BUCKET", "lokilinux-e2e"),
        addressing_style="path",
    )
    await store.ensure_bucket()
    return store


@pytest.mark.asyncio
async def test_multipart_upload_download_verify_delete(storage: Any) -> None:
    payload = bytes(range(256)) * (_PAYLOAD_SIZE // 256)
    digest = hashlib.sha256(payload).hexdigest()
    key = "uploads/e2e/multipart.bin"

    await storage.put_stream(
        key, BytesIO(payload), content_type="application/octet-stream", metadata={"sha256": digest}
    )

    # The object is there and its size matches.
    meta = await storage.head(key)
    assert meta.size_bytes == len(payload)

    # Read it back and check the bytes.
    stream = await storage.get_stream(key)
    read_back = b""
    async for chunk in stream:
        read_back += chunk
    assert hashlib.sha256(read_back).hexdigest() == digest

    # The listing sees it.
    listed = await storage.list("uploads/e2e")
    assert any(o.key == key for o in listed)

    # Deleting works and the object is really gone.
    await storage.delete(key)
    assert not await storage.exists(key)
    assert not any(o.key == key for o in await storage.list("uploads/e2e"))
