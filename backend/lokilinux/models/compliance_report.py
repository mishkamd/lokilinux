"""
LokiLinux — Reporting Engine ORM model (Compliance module, Phase 5).

`body` (BYTEA) is the legacy inline-storage path — see migration 019's
docstring for why it existed before object storage did. New reports are
written to storage_objects instead (Object Storage plan, migration 046);
`storage_object_id` is nullable so old rows keep reading from `body`
(dual-read, see services/report_service.py and
routers/compliance/reports.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class ComplianceReport(Base):
    __tablename__ = "compliance_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    report_type: Mapped[str] = mapped_column(String(30), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    artifact_uri: Mapped[str | None] = mapped_column(String(1000))
    body: Mapped[bytes | None] = mapped_column(BYTEA)
    storage_object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storage_objects.id")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
