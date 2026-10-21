"""
LokiLinux — Named filter views (per user).

A saved view is a named set of list filters ("Prod / Critical / 7d"). The
filter state itself lives in the URL — this table only stores the *name* of a
URL plus its scope, so a view can be listed on another device.

`user_id` is the raw Better Auth id (a nanoid, not a UUID) stored as text —
see the note in `auth/dependencies.safe_user_uuid`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )

    __table_args__ = (Index("ix_saved_views_user_scope", "user_id", "scope"),)
