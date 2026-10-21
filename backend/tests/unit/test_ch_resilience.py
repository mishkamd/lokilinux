"""Regression guards for the ClickHouse store's operational properties:
degradation instead of dying (MIS-138), bounded execution (MIS-140) and the
dedicated thread pool (MIS-141). No live ClickHouse required.
"""

import asyncio
from typing import Any

import pytest

from lokilinux.ch import ClickHouseStore, ClickHouseUnavailable


def _store() -> ClickHouseStore:
    return ClickHouseStore(
        url="http://clickhouse:8123", user="default", password="", database="lokilinux"
    )


@pytest.mark.asyncio
async def test_connect_failure_does_not_raise_and_leaves_store_degraded(monkeypatch: Any) -> None:
    """MIS-138: an unreachable ClickHouse must not take the API down."""
    import lokilinux.ch as ch_mod

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr(ch_mod.clickhouse_connect, "get_client", boom)
    store = _store()
    await store.connect()  # must not raise
    assert await store.ping() is False
    with pytest.raises(ClickHouseUnavailable):
        await store.command("SELECT 1")
    with pytest.raises(ClickHouseUnavailable):
        await store.query("SELECT 1")
    with pytest.raises(ClickHouseUnavailable):
        await store.insert("events", [[1]], ["a"])


@pytest.mark.asyncio
async def test_store_reconnects_lazily_after_an_outage(monkeypatch: Any) -> None:
    """A CH outage at boot must not leave the API permanently degraded: the
    next call retries the connection."""
    import lokilinux.ch as ch_mod

    calls = {"n": 0}

    class FakeClient:
        def command(self, sql: str) -> str:
            return "ok"

    def fake_get_client(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection refused")
        return FakeClient()

    monkeypatch.setattr(ch_mod.clickhouse_connect, "get_client", fake_get_client)
    store = _store()
    await store.connect()
    assert await store.ping() is False
    # First call reconnects (attempt #2 succeeds) and then runs the query.
    assert await store.command("SELECT 1") == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_client_receives_timeouts(monkeypatch: Any) -> None:
    """MIS-140: connect/read timeouts are passed to the driver."""
    import lokilinux.ch as ch_mod

    captured: dict[str, Any] = {}

    class FakeClient:
        def command(self, sql: str) -> str:
            return "ok"

    def fake_get_client(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setattr(ch_mod.clickhouse_connect, "get_client", fake_get_client)
    store = _store()
    await store.connect()
    assert captured["connect_timeout"] == ch_mod._CONNECT_TIMEOUT_S
    assert captured["send_receive_timeout"] == ch_mod._SEND_RECEIVE_TIMEOUT_S


@pytest.mark.asyncio
async def test_query_and_insert_carry_max_execution_time(monkeypatch: Any) -> None:
    """MIS-140: the server-side query is bounded too."""
    import lokilinux.ch as ch_mod

    seen: dict[str, Any] = {}

    class FakeClient:
        def command(self, sql: str) -> str:
            return "ok"

        def query(self, sql: str, parameters: Any = None, settings: Any = None) -> str:
            seen["query_settings"] = settings
            return "rows"

        def insert(self, table: str, data: Any, column_names: Any = None, settings: Any = None) -> None:
            seen["insert_settings"] = settings

    monkeypatch.setattr(ch_mod.clickhouse_connect, "get_client", lambda *a, **k: FakeClient())
    store = _store()
    await store.connect()
    await store.query("SELECT 1")
    await store.insert("events", [[1]], ["a"])
    assert seen["query_settings"] == {"max_execution_time": ch_mod._MAX_EXECUTION_TIME_S}
    assert seen["insert_settings"] == {"max_execution_time": ch_mod._MAX_EXECUTION_TIME_S}


@pytest.mark.asyncio
async def test_calls_run_on_the_dedicated_pool(monkeypatch: Any) -> None:
    """MIS-141: CH calls must not occupy the default executor."""
    import lokilinux.ch as ch_mod

    assert ch_mod._CH_POOL._max_workers == 4

    class FakeClient:
        def command(self, sql: str) -> str:
            return "ok"

    monkeypatch.setattr(ch_mod.clickhouse_connect, "get_client", lambda *a, **k: FakeClient())
    store = _store()
    await store.connect()
    # The call must complete on the CH pool's thread, not the default one.
    loop = asyncio.get_running_loop()
    default_thread = await loop.run_in_executor(None, lambda: __import__("threading").current_thread().name)
    ch_thread = await loop.run_in_executor(ch_mod._CH_POOL, lambda: __import__("threading").current_thread().name)
    assert ch_thread != default_thread
    assert ch_thread.startswith("ch")
