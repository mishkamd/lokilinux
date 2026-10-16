"""
LokiLinux — Object storage metadata (Centralized S3 Object Storage plan).

One row per object living in RustFS/S3. PostgreSQL holds only metadata and
the reference (bucket + object_key); file bytes never touch this table or
the container filesystem — see lokilinux.services.storage_service, the only
writer.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class StorageObject(Base):
    __tablename__ = "storage_objects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="s3")
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="AVAILABLE")
    # Better Auth user — no FK
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
