"""
LokiLinux — FastAPI request-scoped dependencies.

get_db and get_cache pull from app.state (populated in lifespan).
"""

from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.ch import ClickHouseStore
from lokilinux.object_storage import ObjectStorage


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a DB session; commit on success, rollback on error."""
    async with request.app.state.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_cache(request: Request) -> RedisCache:
    return request.app.state.cache


async def get_nats(request: Request):  # type: ignore[return]
    return request.app.state.nats


async def get_ch(request: Request) -> ClickHouseStore:
    return request.app.state.ch


async def get_storage(request: Request) -> ObjectStorage:
    return request.app.state.storage
