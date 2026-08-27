"""
LokiLinux — Compliance Findings Pydantic schemas (Enterprise Compliance plan U4).

A finding is a read-model projection over rule_evaluations joined to
compliance_rules/agents (KTD1) — there is no findings table. `id` is an
opaque encoding of the evaluation's (agent_id, rule_id, time) key
(schemas.common.encode_cursor, same helper pagination cursors use), since
rule_evaluations has no single surrogate PK column to address a row by.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class FindingResponse(BaseModel):
    id: str
    time: datetime
    agent_id: UUID
    hostname: str | None = None
    rule_id: UUID
    rule_key: str
    title: str
    domain: str
    severity: str
    result: str
    exception_id: UUID | None = None
    acknowledged_by: UUID | None = None
    acknowledged_at: datetime | None = None


class FindingDetailResponse(FindingResponse):
    policy_set_id: UUID
    actual_value: Any | None = None
    expected_value: Any | None = None
    evidence: Any | None = None
    evidence_hash: str | None = None
    error_message: str | None = None
    source: str | None = None
    # Snapshot pointer (R1: "expected vs observed vs evidence vs snapshot")
    # — the InventorySnapshot for this agent+domain closest at-or-before
    # `time`, best-effort (None if none was ever taken).
    snapshot_id: UUID | None = None
    snapshot_taken_at: datetime | None = None
    snapshot_content_hash: str | None = None
    # Linked open drift event, if this agent+domain currently has one
    # (simplified agent+domain match — the plan's finer evidence-path-prefix
    # match is U2 scope, not bundled here).
    open_drift_event_id: UUID | None = None
