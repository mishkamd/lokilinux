from datetime import datetime, timezone
from uuid import uuid4

import pytest

from lokilinux.schemas.common import decode_cursor


def _ch_row(ts: datetime, event_id: str, **overrides):
    row = {
        "timestamp": ts, "event_id": event_id, "tenant": "default", "source": "agent",
        "type": "host.heartbeat.ok", "severity": "INFO", "host_id": "host-1", "service": "",
        "fingerprint": "a" * 32, "schema_version": 1, "payload": "{}",
    }
    row.update(overrides)
    columns = [
        "timestamp", "event_id", "tenant", "source", "type", "severity",
        "host_id", "service", "fingerprint", "schema_version", "payload",
    ]
    return [row[c] for c in columns]


# ── POST /api/v1/events ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_single_valid_event_is_accepted_and_published(client, fake_nats):
    resp = await client.post("/api/v1/events", json={"source": "agent", "type": "host.heartbeat.ok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"accepted": 1, "rejected": []}
    assert len(fake_nats.published) == 1
    subject, _payload = fake_nats.published[0]
    assert subject == "lokilinux.events.raw.agent"


@pytest.mark.asyncio
async def test_post_batch_mixed_validity(client, fake_nats):
    resp = await client.post(
        "/api/v1/events",
        json={"events": [
            {"source": "agent", "type": "host.heartbeat.ok"},
            {"source": "not-a-real-source", "type": "host.heartbeat.ok"},
        ]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 1
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["index"] == 1
    assert len(fake_nats.published) == 1


@pytest.mark.asyncio
async def test_post_batch_over_max_size_rejected(client):
    events = [{"source": "agent", "type": "host.heartbeat.ok"} for _ in range(101)]
    resp = await client.post("/api/v1/events", json={"events": events})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_non_object_event_rejected_without_crashing(client):
    resp = await client.post("/api/v1/events", json={"events": ["not-an-object"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 0
    assert body["rejected"] == [{"index": 0, "reason": "event must be an object"}]


@pytest.mark.asyncio
async def test_post_rate_limit_exceeded(client, monkeypatch):
    from types import SimpleNamespace

    import lokilinux.api.v1.routers.events as events_mod

    monkeypatch.setattr(events_mod, "get_settings", lambda: SimpleNamespace(event_rate_per_agent_per_min=1))

    first = await client.post("/api/v1/events", json={"source": "agent", "type": "host.heartbeat.ok"})
    assert first.status_code == 200
    second = await client.post("/api/v1/events", json={"source": "agent", "type": "host.heartbeat.ok"})
    assert second.status_code == 429


# ── GET /api/v1/events ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_events_empty(client):
    resp = await client.get("/api/v1/events")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


@pytest.mark.asyncio
async def test_get_events_returns_items_and_no_cursor_when_exactly_at_limit(client, fake_ch):
    ts = datetime.now(timezone.utc)
    fake_ch.queued_rows = [_ch_row(ts, str(uuid4()))]
    resp = await client.get("/api/v1/events?limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_get_events_returns_next_cursor_when_more_rows_exist(client, fake_ch):
    ts = datetime.now(timezone.utc)
    ids = [str(uuid4()) for _ in range(3)]
    fake_ch.queued_rows = [_ch_row(ts, i) for i in ids]  # repository asks for limit+1=3
    resp = await client.get("/api/v1/events?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    decoded = decode_cursor(body["next_cursor"])
    ts_str, cursor_id = decoded.rsplit(":", 1)
    assert cursor_id == ids[1]  # last item kept after truncating to `limit`


@pytest.mark.asyncio
async def test_get_events_cursor_round_trips_into_query_params(client, fake_ch):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_ch.queued_rows = [_ch_row(ts, "evt-1")]
    resp = await client.get(f"/api/v1/events?cursor={_encode(ts, 'evt-0')}")
    assert resp.status_code == 200
    assert fake_ch.last_params["before_ts"] == ts
    assert fake_ch.last_params["before_id"] == "evt-0"


def _encode(ts: datetime, event_id: str) -> str:
    from lokilinux.schemas.common import encode_cursor

    return encode_cursor(f"{ts.isoformat()}:{event_id}")
