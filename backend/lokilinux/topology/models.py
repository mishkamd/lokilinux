"""
LokiLinux — TopologyNode / TopologyEdge ORM models (Phase E).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class TopologyNode(Base):
    __tablename__ = "topology_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text(), nullable=False, server_default="default")
    kind: Mapped[str] = mapped_column(Text(), nullable=False)  # HOST|SERVICE|APPLICATION|EXTERNAL
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class TopologyEdge(Base):
    __tablename__ = "topology_edges"

    from_node: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topology_nodes.id", ondelete="CASCADE"), primary_key=True)
    to_node: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topology_nodes.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text(), nullable=False, server_default="DEPENDS_ON")
