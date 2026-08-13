"""
LokiLinux — Resource -> rule dependency index (docs/compliance §40).

Populated at rule import/curation time so incremental evaluation
(services/compliance/internal/ingest — a file_integrity snapshot touching
/etc/ssh/sshd_config) can look up exactly which rules that path affects
instead of re-evaluating an agent's entire domain rule set on every change.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class ComplianceRuleResource(Base):
    __tablename__ = "compliance_rule_resources"
    __table_args__ = (UniqueConstraint("rule_id", "resource_type", "resource_path", name="uq_rule_resources_rule_type_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_rules.id", ondelete="CASCADE"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)  # FILE/PACKAGE/SERVICE/SYSCTL_KEY/...
    resource_path: Mapped[str] = mapped_column(String(1000), nullable=False)
