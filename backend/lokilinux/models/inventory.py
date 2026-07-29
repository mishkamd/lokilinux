"""
LokiLinux — Inventory Collector ORM models (Compliance module).

Content-addressable storage: inventory_blobs stores each unique normalized
per-domain document exactly once (keyed by BLAKE3 content_hash); inventory_
snapshots are cheap (agent_id, domain, content_hash) pointers. A golden-image
fleet of thousands of identical hosts costs one blob per domain, not one per
agent. See docs/compliance/01-DATA-MODEL.md §3 and 04-PROTOCOL.md for the
per-domain delta-sync protocol that populates these tables.

inventory_deltas is a TimescaleDB hypertable (space-partitioned on agent_id)
created directly in the migration via create_hypertable — SQLAlchemy just
needs to know the columns/PK to match what's actually on disk; Alembic
autogenerate should never be asked to "fix" this table's storage settings.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class InventoryBlob(Base):
    __tablename__ = "inventory_blobs"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    body: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    algo: Mapped[str] = mapped_column(String(20), default="blake3", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    ref_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), ForeignKey("inventory_blobs.content_hash"), nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class InventoryDelta(Base):
    """Hypertable — composite PK (time, agent_id, domain) matches the
    partitioning key required by TimescaleDB space partitioning on agent_id.
    """

    __tablename__ = "inventory_deltas"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    domain: Mapped[str] = mapped_column(String(50), primary_key=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    new_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    diff: Mapped[dict | None] = mapped_column(JSONB)
