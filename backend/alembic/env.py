"""
Alembic migration environment — async (psycopg3 / asyncpg).

DATABASE_URL is read from the application Settings so migrations
always target the same database the app uses.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from lokilinux.config import Settings
from lokilinux.db import Base
import lokilinux.models  # noqa: F401 — registers all ORM models with Base.metadata

# Alembic Config object (access to alembic.ini values)
config = context.config

# Wire standard Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support
target_metadata = Base.metadata

# Override sqlalchemy.url from app settings (ignores alembic.ini placeholder)
_settings = Settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)


# ── Offline mode (generate SQL without DB connection) ─────────────────────────


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (async) ────────────────────────────────────────────────────────


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(
        config.get_main_option("sqlalchemy.url"),  # type: ignore[arg-type]
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
