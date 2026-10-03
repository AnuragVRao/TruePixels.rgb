"""Alembic environment for TruePixels.rgb.

The target database is the application's own: ``app.shared.db.engine``,
i.e. DATABASE_URL from backend/.env (or the environment). Tests and scripts
that call ``configure_database()`` first therefore migrate the database the
app will use. ``-x url=...`` overrides it for one command.

Schema ownership is unchanged by living in one migration history: M1 owns D1
and D2, M2 owns D3 and D4, M3 owns D5 and D6.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.shared import db

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

db.import_all_models()
target_metadata = db.Base.metadata


def _engine():
    url = context.get_x_argument(as_dictionary=True).get("url")
    return db.make_engine(url) if url else db.engine



def run_migrations_offline() -> None:
    context.configure(
        url=_engine().url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:  # handed in by a test or script
        _run(connectable)
        return
    with _engine().connect() as connection:
        _run(connection)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite cannot ALTER most things in place; batch mode rebuilds the
        # table instead, so later migrations work on both backends.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
