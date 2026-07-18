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


class AnsibleRoleBase(BaseModel):
    name: str
    description: str | None = None
    files: dict[str, str]

    @field_validator("files")
    @classmethod
    def check_paths(cls, v: dict) -> dict:
        return _validate_paths(v)


class AnsibleRoleCreate(AnsibleRoleBase):
    pass


class AnsibleRoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    files: dict[str, str] | None = None
    is_enabled: bool | None = None

    @field_validator("files")
    @classmethod
    def check_paths(cls, v: dict | None) -> dict | None:
        return _validate_paths(v) if v is not None else None


class AnsibleRoleResponse(AnsibleRoleBase):
    id: UUID
    version: int
    is_enabled: bool
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
