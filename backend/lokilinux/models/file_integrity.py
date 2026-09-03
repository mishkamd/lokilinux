"""
LokiLinux — File Integrity Monitoring ORM models (Compliance module).

file_hashes is current-state-only (overwritten in place); file_changes is a
TimescaleDB hypertable, append-only history. Both created directly in
migration 017 — SQLAlchemy only needs to know the columns/PK to match what's
actually on disk, same convention as models/inventory.py and models/drift.py.
Written by lokilinux-compliance's Ingester
(services/compliance/internal/ingest/file_integrity.go), read here.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class FileHash(Base):
    __tablename__ = "file_hashes"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(1000), primary_key=True)
    algo: Mapped[str] = mapped_column(String(10), nullable=False, default="sha256")
    hash: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[int | None] = mapped_column(Integer)
    uid: Mapped[int | None] = mapped_column(Integer)
    gid: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FileChange(Base):
    __tablename__ = "file_changes"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), primary_key=True)
    old_hash: Mapped[str | None] = mapped_column(String(128))
    new_hash: Mapped[str | None] = mapped_column(String(128))
    change_kind: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # CREATED/MODIFIED/DELETED/PERMISSION_CHANGED/OWNER_CHANGED
    # Migration 025 — populated once the agent's FIM collector reports
    # mode/uid/gid (agent/internal/compliance/file_integrity_collector.go).
    old_mode: Mapped[int | None] = mapped_column(Integer)
    new_mode: Mapped[int | None] = mapped_column(Integer)
    old_uid: Mapped[int | None] = mapped_column(Integer)
    new_uid: Mapped[int | None] = mapped_column(Integer)
    old_gid: Mapped[int | None] = mapped_column(Integer)
    new_gid: Mapped[int | None] = mapped_column(Integer)


class FIMScope(Base):
    """Operator-configured file-integrity watch/ignore scope — GLOBAL (fleet
    default) or AGENT (per-server override). Delivered to the agent as a
    signed document over the heartbeat (fim_scope_service.signed_envelope,
    agent/internal/compliance/fimconfig.go). Not the same table as
    file_integrity_ignores (migration 017): that one is a GLOBAL-only,
    post-ingest filter applied server-side after the agent already scanned;
    this one controls what the agent scans in the first place, everywhere.
    """

    __tablename__ = "fim_scopes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)  # GLOBAL | AGENT
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    watch_paths: Mapped[list] = mapped_column(JSONB, nullable=False)
    ignore_paths: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
