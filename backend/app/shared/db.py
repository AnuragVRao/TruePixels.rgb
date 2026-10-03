"""Database engine, sessions and declarative base - the ONE place they are made.

PostgreSQL is the target (SRS 2.1, 3.4); SQLite still works for the fast test
suite and quick local runs. Select with ``DATABASE_URL``:

    postgresql+psycopg://truepixels:<password>@localhost:5433/truepixels
    sqlite:///C:/path/to/truepixels.db

INTEGRATION NOTE: M1 and M3 each shipped an almost identical copy of this file.
This is M1's (it owns D1/D2); M3's SQL_ECHO switch is kept alongside M1's
DEBUG switch so both teams' settings still work. See changes.md.

Single engine (Phase 2). Every database user in the app - request handlers
through ``get_db``, the D6 logger (``logging_service``) and the M2 pipeline -
draws sessions from the same ``SessionLocal``. ``configure_database`` rebinds
that one sessionmaker in place, so all of them follow it together; there is
no way for logging to write to one database while requests use another (the
"no such table: logs" split the test suite used to have).

Schema is owned by Alembic (``backend/migrations``). The app does not create
tables at startup any more; it checks the database is at the latest revision
and refuses to start otherwise (``check_schema_current``).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Explicit, so that DATABASE_URL from backend/.env applies no matter which
# module happens to be imported first (it used to depend on M1's config being
# imported before this file).
load_dotenv(BACKEND_DIR / ".env")

# Default: backend/truepixels.db, as before, but no longer relative to
# whatever directory the server was started from.
DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'truepixels.db').as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

# Connection pool (PostgreSQL; SQLite uses its own pooling).
#
# A prediction request holds its session for the whole of inference - about
# 1 s for an ordinary photo, ~9 s for a 16 MP one on the development GPU -
# because D4 is written through it at the end. Phase 7 moves inference off the
# event loop into a threadpool with GPU access bounded to one at a time, so
# several prediction requests can be waiting, each holding a connection, while
# other endpoints (history, results, admin) still need theirs. 5 + 10 overflow
# leaves room for that on one worker; pool_timeout turns exhaustion into a
# clear error after 30 s instead of an indefinite hang; pool_recycle avoids
# connections dropped by the server or a proxy after long idle periods.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))

_ECHO = (
    os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
    or os.getenv("SQL_ECHO", "false").lower() == "true"
)


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    """SQLite ignores foreign keys unless asked, per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str) -> Engine:
    """An engine for ``url`` with this project's settings."""
    kwargs: dict = {"pool_pre_ping": True, "echo": _ECHO}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Every session runs in UTC, so date() grouping and returned
        # timestamps never depend on the server's configured time zone.
        kwargs["connect_args"] = {"options": "-c timezone=UTC"}
        kwargs.update(
            pool_size=DB_POOL_SIZE,
            max_overflow=DB_MAX_OVERFLOW,
            pool_timeout=DB_POOL_TIMEOUT,
            pool_recycle=DB_POOL_RECYCLE,
        )
    new_engine = create_engine(url, **kwargs)
    if new_engine.dialect.name == "sqlite":
        event.listen(new_engine, "connect", _sqlite_pragmas)
    return new_engine


engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def configure_database(url: str) -> Engine:
    """Point the whole application at ``url``.

    Rebinds the shared ``SessionLocal`` in place - every module that imported
    it (requests, logging, pipeline) follows - and disposes the old engine.
    Used by the test suite and by scripts; the server configures itself from
    ``DATABASE_URL`` at import.
    """
    global engine, DATABASE_URL
    old = engine
    engine = make_engine(url)
    DATABASE_URL = url
    SessionLocal.configure(bind=engine)
    old.dispose()
    return engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def import_all_models() -> None:
    """Register every table (D1-D6) on ``Base.metadata``."""
    import app.m1_access.models  # noqa: F401  D1, D2
    import app.m2_analysis.models  # noqa: F401  D3, D4
    import app.m3_results.models  # noqa: F401  D5, D6


class SchemaNotCurrentError(RuntimeError):
    """The database is not at the latest Alembic revision."""


def check_schema_current() -> None:
    """Refuse to run against a database that is not at Alembic head.

    The schema is created and changed only by migrations. Run
    ``cd backend && alembic upgrade head`` to create or update it.
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    heads = set(script.get_heads())
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    if current != heads:
        raise SchemaNotCurrentError(
            f"database {engine.url.render_as_string(hide_password=True)} is at revision "
            f"{sorted(current) or 'none (empty database)'}, but the code needs {sorted(heads)}. "
            "Run:  cd backend && alembic upgrade head"
        )


SCRATCH_SUFFIXES = ("_test", "_regression")


def refuse_unless_scratch(url) -> None:
    """Raise unless ``url`` names a scratch database. Checked BEFORE connecting.

    PostgreSQL: the database name must end in _test or _regression.
    SQLite: anything but the default development file (backend/truepixels.db).
    """
    name = url.database or ""
    if url.get_backend_name() == "postgresql":
        if not name.endswith(SCRATCH_SUFFIXES):
            raise RuntimeError(f"refusing to reset {url.render_as_string(hide_password=True)}: "
                               f"not a scratch database (name must end in {SCRATCH_SUFFIXES})")
        return
    if name in ("", ":memory:"):
        return
    if Path(name).resolve() == (BACKEND_DIR / "truepixels.db").resolve():
        raise RuntimeError(f"refusing to reset the development SQLite database {name}")


def reset_scratch_database() -> None:
    """Drop EVERYTHING in the configured database, then migrate to head.

    For scratch databases only (the test suite, the regression harness) -
    callers guard the database name. On PostgreSQL the whole ``public``
    schema is dropped and recreated, which also removes non-table objects a
    table drop leaves behind (the 0002 trigger function); on SQLite every
    table is dropped (its triggers go with it).
    """
    from sqlalchemy import inspect, text

    refuse_unless_scratch(engine.url)
    import_all_models()
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        else:
            Base.metadata.drop_all(bind=connection)
            if inspect(connection).has_table("alembic_version"):
                connection.execute(text("DROP TABLE alembic_version"))
    migrate_to_head()


def migrate_to_head() -> None:
    """Run ``alembic upgrade head`` against the configured engine.

    For tests and scripts that build a fresh database; the server never
    migrates itself (see ``check_schema_current``).
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def init_db() -> None:
    """Startup check (kept under M1's name): the schema must be current."""
    import_all_models()
    check_schema_current()
