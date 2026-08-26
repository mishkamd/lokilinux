import pytest


@pytest.mark.asyncio
async def test_pipeline_snapshot_shape(client):
    resp = await client.get("/api/v1/observability/pipeline")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "events_received", "events_dropped", "signals_detected", "incidents_created",
        "clickhouse_insert_errors", "buffer_depth", "correlation_duration",
        "clickhouse_operation_duration",
    ):
        assert key in body
        assert isinstance(body[key], list)


@pytest.mark.asyncio
async def test_pipeline_snapshot_reflects_incremented_counters(client):
    from lokilinux.metrics import signals_detected_total

    signals_detected_total.labels(type="cpu.high").inc()
    resp = await client.get("/api/v1/observability/pipeline")
    samples = resp.json()["signals_detected"]
    total_values = [s["value"] for s in samples if s["name"].endswith("_total")]
    assert any(v >= 1 for v in total_values)
