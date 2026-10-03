"""The Alembic history is the schema - and it matches the models exactly.

Runs against whichever database the suite uses (SQLite by default, PostgreSQL
with TEST_DATABASE_URL), so running the suite on both covers both. The test
database itself was built by ``alembic upgrade head`` (root conftest).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import IntegrityError

from app.m1_access.models import User
from app.m2_analysis.models import ModelRegistry
from app.shared import db


def _schema_diff() -> list:
    with db.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, db.Base.metadata)


def test_migrated_schema_equals_the_models():
    """Tests (built by migrations) and production (built by migrations) cannot
    drift from the SQLAlchemy models without this failing.

    One gap on SQLite only: it cannot reflect the expression index on
    lower(email), so Alembic skips that index there (with a warning). It is
    compared on PostgreSQL, and its effect is asserted on both backends by
    test_email_uniqueness_is_case_insensitive_and_enforced.
    """
    diff = _schema_diff()
    assert diff == [], f"schema drift between migrations and models: {diff}"


def test_database_is_at_head():
    db.check_schema_current()  # raises SchemaNotCurrentError otherwise


def test_downgrade_to_base_and_back_up(tmp_path):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(db.BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "base")
    tables = set(inspect(db.engine).get_table_names()) - {"alembic_version"}
    assert tables == set()
    with pytest.raises(db.SchemaNotCurrentError):
        db.check_schema_current()
    db.migrate_to_head()
    assert _schema_diff() == []


def test_email_uniqueness_is_case_insensitive_and_enforced():
    session = db.SessionLocal()
    try:
        common = dict(full_name="Case Test", password_hash="x", role="User",
                      account_status="active", is_email_verified=True)
        session.add(User(email="Case.Test@example.com", **common))
        session.commit()
        session.add(User(email="case.test@EXAMPLE.com", **common))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        found = session.query(User).filter(
            func.lower(User.email) == "case.test@example.com").one()
        assert found.email == "Case.Test@example.com"
    finally:
        session.close()


def test_login_lookup_uses_the_lower_email_index():
    if db.engine.dialect.name != "postgresql":
        pytest.skip("EXPLAIN check is PostgreSQL-specific")
    with db.engine.begin() as connection:
        # Tiny tables are cheaper to scan; forbid that so the plan shows
        # whether the index is usable for this predicate at all.
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(r[0] for r in connection.execute(text(
            "EXPLAIN SELECT * FROM users WHERE lower(email) = 'a@b.c'")))
    assert "uq_users_email_lower" in plan, plan


def test_only_one_active_model_per_type():
    session = db.SessionLocal()
    try:
        for version in ("a", "b"):
            session.add(ModelRegistry(model_name="dup", model_version=version,
                                      model_type="fusion-configuration",
                                      artifact_ref="t", is_active=True))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(ModelRegistry(model_name="dup", model_version="c",
                                  model_type="fusion-configuration",
                                  artifact_ref="t", is_active=False))
        session.add(ModelRegistry(model_name="dup", model_version="d",
                                  model_type="fusion-configuration",
                                  artifact_ref="t", is_active=False))
        session.commit()  # any number of INACTIVE rows is fine
    finally:
        session.close()


def test_timestamps_round_trip_as_the_same_instant_on_postgresql():
    """timestamptz on PostgreSQL: an aware value in any zone comes back aware,
    as the same instant, in UTC (sessions are pinned to UTC in db.py)."""
    if db.engine.dialect.name != "postgresql":
        pytest.skip("SQLite has no timezone-aware storage; the app always writes UTC")
    india = timezone(timedelta(hours=5, minutes=30))
    written = datetime(2026, 10, 3, 9, 30, tzinfo=india)
    session = db.SessionLocal()
    try:
        user = User(full_name="TZ", email="tz@example.com", password_hash="x", role="User",
                    account_status="active", is_email_verified=True,
                    registered_at=written, otp_expires_at=written)
        session.add(user)
        session.commit()
        session.expire_all()
        read = session.get(User, user.user_id)
        for value in (read.registered_at, read.otp_expires_at):
            assert value.tzinfo is not None
            assert value == written
            assert value.utcoffset() == timedelta(0)
        kinds = dict(session.execute(text(
            "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type LIKE 'timestamp%'")).all())
        assert kinds and set(kinds.values()) == {"timestamp with time zone"}, kinds
        day = session.execute(text("SELECT date(registered_at) FROM users")).scalar_one()
        assert str(day) == "2026-10-03"  # 04:00 UTC, the same calendar day in UTC
    finally:
        session.close()


def test_server_refuses_to_start_on_a_database_behind_head(tmp_path, monkeypatch):
    """init_db() (the startup check) names the fix instead of creating tables."""
    from sqlalchemy.orm import sessionmaker

    empty = db.make_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    monkeypatch.setattr(db, "engine", empty)
    with pytest.raises(db.SchemaNotCurrentError, match="alembic upgrade head"):
        db.init_db()
    empty.dispose()
