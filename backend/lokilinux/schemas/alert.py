"""
LokiLinux — Alert Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AlertResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    title: str
    severity: str | None = None
    alert_type: str | None = None
    description: str | None = None
    context_data: dict | None = None
    agent_id: UUID | None = None
    cve_id: str | None = None
    job_id: UUID | None = None
    policy_id: UUID | None = None
    rule_id: UUID | None = None
    status: str
    acknowledged_by: UUID | None = None
    acknowledged_at: datetime | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    escalation_level: int
    escalated_at: datetime | None = None
    triggered_at: datetime
    created_at: datetime


class AlertRuleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    description: str | None = None
    conditions: dict
    alert_severity: str | None = None
    notification_channels: dict | None = None
    escalation_policy: UUID | None = None
    escalation_delay_minutes: int | None = None
    is_enabled: bool
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
