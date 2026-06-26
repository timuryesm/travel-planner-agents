"""
Alembic environment configuration.

The application uses asyncpg for all runtime queries. Alembic's migration
runner is synchronous, so env.py strips "+asyncpg" from DATABASE_URL and
falls back to psycopg2 for migration connections only.

Requirements:
    pip install psycopg2-binary   # migration-time only; asyncpg handles runtime
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import Base and all models so autogenerate can see every table.
# The `noqa` suppresses "imported but unused" — the import is intentional:
# it registers the ORM models on Base.metadata.
from src.db.base import Base
import src.db.models  # noqa: F401

# ── Alembic config ────────────────────────────────────────────────────────────

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Strip asyncpg driver for the sync migration connection.
# postgresql+asyncpg://...  →  postgresql://...  (uses psycopg2 by default)
_async_url: str = os.environ["DATABASE_URL"]
_sync_url: str = _async_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", _sync_url)

target_metadata = Base.metadata


# ── Offline mode (generate SQL without connecting) ────────────────────────────

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


# ── Online mode (connect and apply) ───────────────────────────────────────────

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()