"""
LokiLinux — Ansible Role Pydantic schemas.

files = map of relative path → file content, e.g.
{"tasks/main.yml": "...", "defaults/main.yml": "..."}.
Paths are validated against traversal (no "..", no absolute paths) —
the agent writes them under a temp dir at execution time.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


def _validate_paths(files: dict) -> dict:
    for path in files:
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"Invalid role file path: {path!r}")
    return files


class AnsibleRoleCreate(BaseModel):
    name: str
    description: str | None = None
    files: dict[str, str]

    @field_validator("files")
    @classmethod
    def check_paths(cls, v: dict) -> dict:
        return _validate_paths(v)


class AnsibleRoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    files: dict[str, str] | None = None
    is_enabled: bool | None = None

    @field_validator("files")
    @classmethod
    def check_paths(cls, v: dict | None) -> dict | None:
        return _validate_paths(v) if v is not None else None


class AnsibleRoleResponse(BaseModel):
    """Full detail — GET/POST/PATCH single-item responses. `files` is
    resolved explicitly by the router (legacy column or object storage), so
    this is never built via `.model_validate(role)` alone."""

    id: UUID
    name: str
    description: str | None = None
    files: dict[str, str]
    version: int
    is_enabled: bool
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class AnsibleRoleListItem(BaseModel):
    """List endpoint response — omits `files` so listing roles never
    triggers an object-storage read per row; file_count is a denormalized
    column set on every create/update instead (see
    AnsibleRoleService / routers/ansible_roles.py)."""

    id: UUID
    name: str
    description: str | None = None
    file_count: int
    version: int
    is_enabled: bool
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
