"""
LokiLinux — Common Pydantic schemas: cursor pagination, error response.
"""

import base64
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


# ── Cursor helpers ────────────────────────────────────────────────────────────

def encode_cursor(value: str) -> str:
    """Encode an opaque cursor value as URL-safe base64."""
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> str:
    """Decode a cursor produced by encode_cursor."""
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc
