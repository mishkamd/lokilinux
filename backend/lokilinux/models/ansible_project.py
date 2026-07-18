"""
LokiLinux — Ansible Project ORM model.

Groups playbooks the way roles/<name>/projects/<name>/ organizes a real
Ansible tree on disk. default_agent_ids is the equivalent of a project's
inventory/ — since the fleet's live agents are already the inventory
(no static hosts files here), a project just remembers which agents its
playbooks default to targeting.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class AnsibleProject(Base):
    __tablename__ = "ansible_projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    default_agent_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
