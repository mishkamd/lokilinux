"""
LokiLinux — ApprovalClaim ORM model (plan §6).

A signed approval bound cryptographically to one job: the claim JSON carries
job_id, job_hash, target, capabilities, expiry, nonce and the platform
Ed25519 signature. Agents verify it before executing require_approval
capabilities.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class ApprovalClaim(Base):
    __tablename__ = "approval_claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    approver_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    claim_json: Mapped[str] = mapped_column(Text(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ApprovalClaim {self.id} job={self.job_id}>"
