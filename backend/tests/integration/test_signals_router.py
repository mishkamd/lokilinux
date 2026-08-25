from datetime import datetime, timezone

import pytest

from lokilinux.events.fingerprint import fingerprint
from lokilinux.signals.models import Signal


async def _make_signal(db_session, *, sig_type: str = "cpu.high", status: str = "OPEN") -> Signal:
    now = datetime.now(timezone.utc)
    sig = Signal(
        tenant_id="default", type=sig_type, severity="HIGH", status=status,
        fingerprint=fingerprint("default", "host-1", sig_type, None),
        first_seen=now, last_seen=now,
    )
    db_session.add(sig)
    await db_session.flush()
    await db_session.commit()
    return sig


@pytest.mark.asyncio
async def test_list_signals_empty(client):
    resp = await client.get("/api/v1/signals")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None, "total": None}


@pytest.mark.asyncio
async def test_list_signals_returns_created_row(client, db_session):
    sig = await _make_signal(db_session)
    resp = await client.get("/api/v1/signals")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(sig.id)


@pytest.mark.asyncio
async def test_filter_by_type(client, db_session):
    await _make_signal(db_session, sig_type="cpu.high")
    await _make_signal(db_session, sig_type="memory.high")
    resp = await client.get("/api/v1/signals", params={"type": "memory.high"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "memory.high"


@pytest.mark.asyncio
async def test_resolve_signal(client, db_session):
    sig = await _make_signal(db_session)
    resp = await client.post(f"/api/v1/signals/{sig.id}/resolve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "RESOLVED"


@pytest.mark.asyncio
async def test_suppress_signal(client, db_session):
    sig = await _make_signal(db_session)
    resp = await client.post(f"/api/v1/signals/{sig.id}/suppress")
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUPPRESSED"


@pytest.mark.asyncio
async def test_resolve_nonexistent_signal_404s(client):
    from uuid import uuid4

    resp = await client.post(f"/api/v1/signals/{uuid4()}/resolve")
    assert resp.status_code == 404
