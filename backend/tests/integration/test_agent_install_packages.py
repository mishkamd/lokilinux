"""Integration tests for agent package distribution (/api/v1/agent/packages,
/download-direct, /download-sig) — covers the Object Storage plan's move of
agent packages from a bind-mounted agent/bin directory to deterministic S3
keys (system/agent-packages/<version>/<filename>).
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_packages_reports_unavailable_when_nothing_uploaded(client: AsyncClient):
    resp = await client.get("/api/v1/agent/packages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "0.1.0"
    assert body["available"]["tar.gz"]["amd64"] is False
    assert body["available"]["deb"]["amd64"] is False
    assert body["available"]["rpm"]["amd64"] is False


@pytest.mark.asyncio
async def test_download_direct_503_when_not_built(client: AsyncClient):
    resp = await client.get(
        "/api/v1/agent/download-direct", params={"os": "tar.gz", "arch": "amd64"}
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_download_direct_streams_uploaded_package(client: AsyncClient, fake_storage):
    key = "system/agent-packages/0.1.0/lokilinux-agent_0.1.0_linux_amd64.tar.gz"
    import io

    await fake_storage.put_stream(key, io.BytesIO(b"fake tarball bytes"))

    resp = await client.get(
        "/api/v1/agent/download-direct", params={"os": "tar.gz", "arch": "amd64"}
    )
    assert resp.status_code == 200
    assert resp.content == b"fake tarball bytes"

    packages_resp = await client.get("/api/v1/agent/packages")
    assert packages_resp.json()["available"]["tar.gz"]["amd64"] is True
    assert packages_resp.json()["available"]["tar.gz"]["arm64"] is False


@pytest.mark.asyncio
async def test_download_sig_404_when_not_provisioned(client: AsyncClient, fake_storage):
    import io

    key = "system/agent-packages/0.1.0/lokilinux-agent_0.1.0_linux_amd64.tar.gz"
    await fake_storage.put_stream(key, io.BytesIO(b"fake tarball bytes"))

    resp = await client.get(
        "/api/v1/agent/download-sig", params={"pkg_os": "tar.gz", "arch": "amd64"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_sig_streams_when_present(client: AsyncClient, fake_storage):
    import io

    tarball_key = "system/agent-packages/0.1.0/lokilinux-agent_0.1.0_linux_amd64.tar.gz"
    sig_key = tarball_key + ".sig"
    await fake_storage.put_stream(tarball_key, io.BytesIO(b"fake tarball bytes"))
    await fake_storage.put_stream(sig_key, io.BytesIO(b"fake signature bytes"))

    resp = await client.get(
        "/api/v1/agent/download-sig", params={"pkg_os": "tar.gz", "arch": "amd64"}
    )
    assert resp.status_code == 200
    assert resp.content == b"fake signature bytes"


@pytest.mark.asyncio
async def test_unsupported_os_arch_is_400(client: AsyncClient):
    resp = await client.get("/api/v1/agent/download-direct", params={"os": "msi", "arch": "amd64"})
    assert resp.status_code == 400
