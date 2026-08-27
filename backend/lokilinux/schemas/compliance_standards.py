"""
LokiLinux — Compliance Standards Pydantic schemas (Enterprise Compliance
plan U8/KTD6). Pure aggregation over existing compliance_frameworks ->
versions -> controls -> rule_mappings + compliance_rules.check_source — no
new tables, no new import path.
"""

from pydantic import BaseModel


class StandardSummaryResponse(BaseModel):
    key: str
    name: str
    version: str
    publisher: str | None = None
    description: str | None = None
    status: str | None = None
    rules_total: int
    executable: int
    reference_only: int
    coverage_executable_pct: float


class StandardControlRuleResponse(BaseModel):
    id: str
    rule_key: str
    title: str
    severity: str
    check_source: str
    is_enabled: bool


class StandardControlResponse(BaseModel):
    control_id: str
    title: str
    description: str | None = None
    rules: list[StandardControlRuleResponse]


class StandardDetailResponse(BaseModel):
    key: str
    name: str
    version: str
    publisher: str | None = None
    description: str | None = None
    status: str | None = None
    controls: list[StandardControlResponse]
