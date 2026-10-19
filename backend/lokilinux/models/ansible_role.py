"""
LokiLinux — Ansible Role ORM model.

A role is a named collection of files, e.g.
{"tasks/main.yml": "...", "defaults/main.yml": "..."}. Legacy rows keep that
map inline in `files` (JSONB, dual-read); new roles write the same map as a
single JSON object to object storage instead (Object Storage plan, migration
047) and carry content_object_id. file_count is a cheap denormalized column
so the roles list endpoint can show "N files" without a full S3 read per
row (files itself is deliberately NOT in the list response — see
ansible_roles.py). At execution time the agent materializes the files under
<tmpdir>/roles/<name>/ next to the playbook, where ansible-playbook resolves
them automatically.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class AnsibleRole(Base):
    __tablename__ = "ansible_roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    files: Mapped[dict | None] = mapped_column(JSONB)
    content_object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storage_objects.id")
    )
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
