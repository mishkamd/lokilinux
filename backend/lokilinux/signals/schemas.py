"""
LokiLinux — Signal / CorrelationRule Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from lokilinux.correlation.suppression import _parse_point
from lokilinux.schemas.common import CursorPage

_GROUP_BY_KEYS = {"host_id"}


class SignalResponse(BaseModel):
    id: UUID
    tenant_id: str
    type: str
    severity: str
    status: str
    host_id: UUID | None = None
    hostname: str | None = None  # transient — filled by the router from the owning agent
    service: str | None = None
    fingerprint: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


SignalListResponse = CursorPage[SignalResponse]


class CorrelationRuleResponse(BaseModel):
    id: UUID
    tenant_id: str
    name: str
    enabled: bool
    window_seconds: int
    group_by: list[str]
    conditions: list[dict]
    threshold_score: int
    incident_type: str
    incident_severity: str
    # Surfaced so an editor can round-trip it: the PATCH used to overwrite
    # the stored list with the schema default, silently dropping the
    # operator's maintenance windows on every save.
    suppressions: list[dict] = []
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


CorrelationRuleListResponse = CursorPage[CorrelationRuleResponse]


class CorrelationRuleCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    enabled: bool = True
    window_seconds: int
    group_by: list[str]
    conditions: list[dict]
    threshold_score: int
    incident_type: str
    incident_severity: str
    suppressions: list[dict] = []

    @field_validator("window_seconds")
    @classmethod
    def _window_in_range(cls, v: int) -> int:
        if not (30 <= v <= 3600):
            raise ValueError("window_seconds must be between 30 and 3600")
        return v

    @field_validator("threshold_score")
    @classmethod
    def _threshold_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("threshold_score must be > 0")
        return v

    @field_validator("group_by")
    @classmethod
    def _group_by_supported(cls, v: list[str]) -> list[str]:
        # The evaluator only builds group values for host_id; any other key would
        # silently collapse every group into one.
        unsupported = [k for k in v if k not in _GROUP_BY_KEYS]
        if unsupported:
            allowed = sorted(_GROUP_BY_KEYS)
            raise ValueError(f"unsupported group_by key(s) {unsupported}; allowed: {allowed}")
        return v

    @field_validator("suppressions")
    @classmethod
    def _suppressions_shape(cls, v: list[dict]) -> list[dict]:
        for window in v:
            try:
                _parse_point(window["from"])
                _parse_point(window["to"])
            except (KeyError, ValueError, IndexError, TypeError, AttributeError):
                raise ValueError("each suppression needs 'from'/'to' like 'Sat 22:00'") from None
        return v

    @field_validator("conditions")
    @classmethod
    def _conditions_shape(cls, v: list[dict]) -> list[dict]:
        if not v:
            raise ValueError("conditions must have at least one entry")
        for entry in v:
            if "signal" not in entry or not isinstance(entry["signal"], str) or not entry["signal"]:
                raise ValueError("each condition needs a non-empty 'signal' string")
            weight = entry.get("weight")
            if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
                raise ValueError("each condition needs an integer 'weight' > 0")
        return v
