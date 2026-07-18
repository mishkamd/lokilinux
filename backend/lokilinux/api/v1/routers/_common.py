"""LokiLinux — shared helpers for /servers-scoped routers."""

from uuid import UUID

from fastapi import HTTPException


def parse_agent_pk(agent_id: str) -> UUID:
    """Route param is the agents.id PK (what /servers list links use), not agent_id."""
    try:
        return UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Server not found")
