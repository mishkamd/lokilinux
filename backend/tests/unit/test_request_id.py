"""X-Request-ID: a client's plain token is kept; anything else is replaced (ROADMAP P2, logging)."""

import re

import pytest
from httpx import ASGITransport, AsyncClient

from lokilinux.main import app


@pytest.mark.asyncio
async def test_plain_request_id_is_echoed():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health", headers={"X-Request-ID": "trace-abc_123.4"})
    assert resp.headers["X-Request-ID"] == "trace-abc_123.4"


@pytest.mark.asyncio
async def test_unsafe_request_id_is_replaced():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health", headers={"X-Request-ID": "not a token!"})
    assert re.fullmatch(r"[0-9a-f]{32}", resp.headers["X-Request-ID"])


@pytest.mark.asyncio
async def test_missing_request_id_is_generated():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", resp.headers["X-Request-ID"])
