"""Regression guard for the ClickHouse event-store DDL — no live ClickHouse
required. Locks in the schema shape (TTL/partition/order-by) so an accidental
edit can't silently drop retention or change the sort key.
"""

import pytest

from lokilinux.ch import _events_ddl, _incident_evidence_ddl, _signal_occurrences_ddl


def test_events_ddl_has_ttl_partition_and_order():
    ddl = _events_ddl(30)
    assert "CREATE TABLE IF NOT EXISTS events" in ddl
    assert "ENGINE = MergeTree" in ddl
    assert "PARTITION BY toDate(timestamp)" in ddl
    assert "ORDER BY (tenant, type, timestamp)" in ddl
    assert "TTL toDateTime(timestamp) + INTERVAL 30 DAY" in ddl


def test_signal_occurrences_ddl_has_ttl_partition_and_order():
    ddl = _signal_occurrences_ddl(90)
    assert "CREATE TABLE IF NOT EXISTS signal_occurrences" in ddl
    assert "ORDER BY (tenant, signal_type, timestamp)" in ddl
    assert "TTL toDateTime(timestamp) + INTERVAL 90 DAY" in ddl


def test_incident_evidence_ddl_has_ttl_partition_and_order():
    ddl = _incident_evidence_ddl(180)
    assert "CREATE TABLE IF NOT EXISTS incident_evidence" in ddl
    assert "ORDER BY (tenant, incident_id, timestamp)" in ddl
    assert "TTL toDateTime(timestamp) + INTERVAL 180 DAY" in ddl


def test_non_int_retention_days_raises_instead_of_interpolating_raw():
    """Guards against SQL injection via a non-int retention value — the DDL
    builders cast with int() before interpolating into the TTL clause, so a
    malicious/malformed value raises instead of ever reaching the SQL string."""
    with pytest.raises(ValueError):
        _events_ddl("30; DROP TABLE events")  # type: ignore[arg-type]
