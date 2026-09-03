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
from lokilinux.dependencies import get_cache, get_ch, get_db, get_nats, get_storage


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


class FakeCH:
    """Stand-in for ClickHouseStore — query() returns whatever a test primed
    onto queued_rows/queued_columns; insert()/command() just no-op (nothing
    in the router suite writes to ClickHouse directly)."""

    def __init__(self) -> None:
        self.queued_rows: list[list[Any]] = []
        self.queued_columns: list[str] = [
            "timestamp", "event_id", "tenant", "source", "type", "severity",
            "host_id", "service", "fingerprint", "schema_version", "payload",
        ]
        self.last_query: str | None = None
        self.last_params: dict[str, Any] | None = None
        self.inserted: list[tuple[str, list, list]] = []

    async def query(self, sql: str, parameters: dict[str, Any] | None = None) -> SimpleNamespace:
        self.last_query = sql
        self.last_params = parameters
        return SimpleNamespace(result_rows=self.queued_rows, column_names=self.queued_columns)

    async def insert(self, table: str, data: list, column_names: list) -> None:
        self.inserted.append((table, data, column_names))

    async def ping(self) -> bool:
        return True


class FakeObjectStorage:
    """In-memory stand-in for ObjectStorage — same method surface, no S3."""

    def __init__(self) -> None:
        self.bucket = "lokilinux-test"
        self._objects: dict[str, bytes] = {}

    async def ensure_bucket(self) -> None:
        pass

    async def put_stream(
        self,
        key: str,
        fileobj: Any,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._objects[key] = fileobj.read()

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        data = self._objects[key]

        async def _iter() -> AsyncIterator[bytes]:
            yield data

        return _iter()

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._objects

    async def presign_get(self, key: str, *, expires_in: int) -> str:
        return f"https://fake-presigned.test/{key}?expires_in={expires_in}"

    async def presign_put(
        self, key: str, *, expires_in: int, content_type: str | None = None
    ) -> str:
        return f"https://fake-presigned.test/{key}?expires_in={expires_in}&put=1"


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
def fake_ch() -> FakeCH:
    return FakeCH()


@pytest.fixture
def fake_storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
def current_user() -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "role": "ADMIN"}


@pytest_asyncio.fixture
async def client(
    db_session, fake_cache, fake_nats, fake_ch, fake_storage, current_user
) -> AsyncIterator[AsyncClient]:
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
    # Background tasks read request.app.state.storage directly (same
    # reasoning as session_factory above) — reports.py and policy_engine.py.
    app.state.storage = fake_storage

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_cache] = lambda: fake_cache
    app.dependency_overrides[get_nats] = lambda: fake_nats
    app.dependency_overrides[get_ch] = lambda: fake_ch
    app.dependency_overrides[get_storage] = lambda: fake_storage
    app.dependency_overrides[get_current_user] = lambda: current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
