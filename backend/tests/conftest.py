"""
LokiLinux — shared test fixtures.

Spins up a real Postgres (TimescaleDB image, matching prod) via testcontainers,
runs alembic migrations once per session, then gives each test an isolated
SQLAlchemy session bound to a SAVEPOINT that's rolled back after the test.

DATABASE_URL is overridden via env var *before* any `lokilinux.*` import, since
`lokilinux.config.Settings()` is instantiated at several modules' import time.
"""

import contextlib
import os
import uuid
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio

# ── Point Settings at the test container before importing lokilinux.* ─────────
# Real values still required for other Settings fields (validated at import
# time) — backend/.env supplies them; only DATABASE_URL is swapped below.
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer

# This host resolves "localhost" via a DNS search suffix instead of 127.0.0.1
# (sandbox quirk) — testcontainers' default host detection hangs/fails as a
# result, so pin it explicitly.
DockerContainer.get_container_host_ip = lambda self: "127.0.0.1"

_pg = PostgresContainer("timescale/timescaledb:2.28.1-pg17", driver="psycopg")
_pg.start()
os.environ["DATABASE_URL"] = _pg.get_connection_url()


def _run_migrations() -> None:
    from alembic.config import Config as AlembicConfig

    from alembic import command

    cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "head")


_run_migrations()

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from lokilinux.api.v1 import router as api_v1_router
from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_cache, get_ch, get_db, get_nats


@pytest.fixture(scope="session", autouse=True)
def _stop_container():
    yield
    _pg.stop()


@pytest.fixture(scope="session")
def engine():
    eng = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    yield eng


class FakeCache:
    """In-memory stand-in for RedisCache — same interface, no network."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def get_cached(self, key: str) -> Any | None:
        return self._store.get(key)

    async def set_cached(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._store[key] = value

    async def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    async def incr(self, key: str, ttl: int) -> int:
        self._store[key] = int(self._store.get(key, 0)) + 1
        return self._store[key]

    async def invalidate_pattern(self, pattern: str) -> None:
        prefix = pattern.split("*")[0]
        for k in [k for k in self._store if k.startswith(prefix)]:
            self._store.pop(k, None)

    async def invalidate_agent(self, agent_id: str) -> None:
        await self.invalidate_pattern(f"agent:{agent_id}:*")
        await self.invalidate_pattern(f"vulnerability:{agent_id}:*")

    async def invalidate_cve_database(self) -> None:
        await self.invalidate_pattern("cve:*")
        await self.invalidate_pattern("vulnerability:*")


class FakeNats:
    """Records published messages instead of hitting a broker."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncIterator[AsyncSession]:
    """One SAVEPOINT per test — rolled back afterwards, DB stays clean."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
def fake_cache() -> FakeCache:
    return FakeCache()


@pytest.fixture
def fake_nats() -> FakeNats:
    return FakeNats()


@pytest.fixture
def current_user() -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "role": "ADMIN"}


@pytest_asyncio.fixture
async def client(db_session, fake_cache, fake_nats, current_user) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(api_v1_router, prefix="/api/v1")

    async def _get_db():
        yield db_session

    @contextlib.asynccontextmanager
    async def _session_factory():
        # Mirrors production's app.state.session_factory (set in main.py's
        # lifespan) — background tasks that reach into it directly (e.g.
        # policy_engine.py's ComplianceAsCode import, reports.py's report
        # generation) need it to exist here too, not just Depends(get_db).
        # Reuses the same per-test db_session so background-task writes land
        # in the same rollback-safe SAVEPOINT as everything else in the test.
        yield db_session

    app.state.session_factory = _session_factory

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_cache] = lambda: fake_cache
    app.dependency_overrides[get_nats] = lambda: fake_nats
    app.dependency_overrides[get_current_user] = lambda: current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
