"""Alembic environment — runs migrations against the sync (psycopg) URL.

Deliberately a plain sync engine here even though the app talks to Postgres
async everywhere else: Alembic's autogenerate/offline machinery isn't built
around async engines, and a migration only ever runs one statement at a
time from a CLI invocation — there's no concurrency to gain from async here.
Same database, the right tool for this particular job.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from jobpilot_shared.config import settings
from jobpilot_shared.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.sync_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
