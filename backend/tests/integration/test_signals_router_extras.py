import uuid
from datetime import datetime, timezone

import pytest

from lokilinux.signals.models import Signal


async def _signal(db_session, tenant_id: str = "default") -> Signal:
    now = datetime.now(timezone.utc)
    sig = Signal(
        tenant_id=tenant_id, type="cpu.high", severity="HIGH", status="OPEN",
        fingerprint=f"fp-{uuid.uuid4()}", first_seen=now, last_seen=now,
    )
    db_session.add(sig)
    await db_session.commit()
    return sig


@pytest.mark.asyncio
async def test_foreign_tenant_signal_is_404(client, db_session):
    foreign = await _signal(db_session, "other")
    assert (await client.post(f"/api/v1/signals/{foreign.id}/resolve")).status_code == 404
    assert (await client.post(f"/api/v1/signals/{foreign.id}/suppress")).status_code == 404
    assert (await client.get(f"/api/v1/signals/{foreign.id}/occurrences")).status_code == 404


@pytest.mark.asyncio
async def test_occurrences_reads_signal_occurrences_for_this_signal(client, db_session, fake_ch):
    sig = await _signal(db_session)
    fake_ch.queued_columns = ["timestamp", "tenant", "signal_type", "severity", "host_id",
                              "service", "fingerprint", "value", "metadata"]
    fake_ch.queued_rows = [[datetime.now(timezone.utc), "default", "cpu.high", "HIGH", "", "",
                            sig.fingerprint, 97.0, "{}"]]

    resp = await client.get(f"/api/v1/signals/{sig.id}/occurrences", params={"limit": 5})

    assert resp.status_code == 200
    assert resp.json()["items"][0]["value"] == 97.0
    assert "signal_occurrences" in fake_ch.last_query
    assert fake_ch.last_params == {"tenant": "default", "fingerprint": sig.fingerprint}
