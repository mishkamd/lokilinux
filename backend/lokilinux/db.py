"""
LokiLinux — Database layer (PostgreSQL, SQLAlchemy async)

Engine is created once at startup and stored in app.state.db_engine.
get_db is a FastAPI dependency that yields a session per request.
"""

from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = structlog.get_logger()


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def build_engine(database_url: str) -> AsyncEngine:
    """Create the async engine with production-grade pool settings."""
    return create_async_engine(
        database_url,
        echo=False,
        echo_pool=False,
        pool_size=20,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# ── FastAPI dependency ─────────────────────────────────────────────────────────

async def get_db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session; roll back on error, close always."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
