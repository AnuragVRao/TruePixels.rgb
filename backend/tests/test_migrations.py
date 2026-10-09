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


# --------------------------------------------------------------------------
# Migration 0002: the immutability trigger (invisible to compare_metadata)
# --------------------------------------------------------------------------

def _trigger_present() -> bool:
    with db.engine.connect() as c:
        if db.engine.dialect.name == "postgresql":
            sql = "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_models_immutable'"
        else:
            sql = ("SELECT count(*) FROM sqlite_master WHERE type = 'trigger' "
                   "AND name = 'trg_models_immutable'")
        return c.execute(text(sql)).scalar() == 1


def _function_present() -> bool:
    if db.engine.dialect.name != "postgresql":
        return False
    with db.engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM pg_proc WHERE proname = 'models_immutable'")).scalar() == 1


def test_immutability_trigger_exists_and_refuses_update_and_referenced_delete():
    from sqlalchemy.exc import DBAPIError

    from app.m2_analysis.models import ModelActivation

    assert _trigger_present()
    session = db.SessionLocal()
    try:
        row = ModelRegistry(model_name="imm", model_version="1", model_type="fusion-configuration",
                            artifact_ref="t", is_active=False)
        session.add(row)
        session.flush()
        session.add(ModelActivation(model_type="fusion-configuration", model_id=row.model_id,
                                    action="activate", forced=False))
        session.commit()
        model_id = row.model_id
    finally:
        session.close()
    with pytest.raises(DBAPIError, match="immutable"):
        with db.engine.begin() as c:
            c.execute(text("UPDATE models SET artifact_ref = 'x' WHERE model_id = :i"), {"i": model_id})
    with pytest.raises((DBAPIError, IntegrityError)):  # referenced by an activation: RESTRICT
        with db.engine.begin() as c:
            c.execute(text("DELETE FROM models WHERE model_id = :i"), {"i": model_id})
    with db.engine.begin() as c:  # is_active alone may change
        c.execute(text("UPDATE models SET is_active = :a WHERE model_id = :i"), {"a": False, "i": model_id})


def test_downgrade_of_0002_drops_trigger_and_function_cleanly():
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(db.BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0001")
    assert not _trigger_present() and not _function_present()
    assert "model_activations" not in inspect(db.engine).get_table_names()
    db.migrate_to_head()
    assert _trigger_present() and (_function_present() or db.engine.dialect.name != "postgresql")
    assert _schema_diff() == []


def test_scratch_reset_refuses_the_development_databases():
    from sqlalchemy.engine import make_url

    for url in ("postgresql+psycopg://u:p@127.0.0.1:5433/truepixels",
                "postgresql+psycopg://u:p@127.0.0.1:5433/truepixels_prod",
                f"sqlite:///{(db.BACKEND_DIR / 'truepixels.db').as_posix()}"):
        with pytest.raises(RuntimeError, match="refusing to reset"):
            db.refuse_unless_scratch(make_url(url))
    for url in ("postgresql+psycopg://u:p@127.0.0.1:5433/truepixels_test",
                "postgresql+psycopg://u:p@127.0.0.1:5433/truepixels_regression",
                "sqlite:///C:/tmp/scratch.db"):
        db.refuse_unless_scratch(make_url(url))  # does not raise


def test_0004_recomputes_confidence_from_the_threshold_and_downgrades_exactly():
    """Stored confidences follow the new rule after 0004; 0003 restores the old one."""
    from alembic import command
    from alembic.config import Config

    from app.m1_access.models import Image
    from app.m2_analysis.models import Prediction

    s = db.SessionLocal()
    try:
        user = User(full_name="Mig", email="mig-0004@example.com", password_hash="x", role="User",
                    account_status="active", is_email_verified=True)
        s.add(user)
        s.flush()
        image = Image(user_id=user.user_id, file_reference="uploads/m.png", content_sha256="2" * 64,
                      file_format="PNG", file_size=1, width=64, height=64, validation_status="valid")
        model = ModelRegistry(model_name="mig fusion", model_version="t0004", model_type="fusion-configuration",
                              artifact_ref="test", is_active=False,
                              hyperparameters={"strategy": "weighted_average", "weight_semantic": 0.25,
                                               "weight_frequency": 0.75, "tau": 0.7558, "temperature": 1.0})
        s.add_all([image, model])
        s.flush()
        cases = [(0.5233, "Real"), (0.10, "Real"), (0.80, "AI Generated"), (0.99, "AI Generated")]
        ids = []
        for fusion, cls in cases:
            old = fusion if cls == "AI Generated" else 1.0 - fusion
            p = Prediction(image_id=image.image_id, model_id=model.model_id, predicted_class=cls,
                           confidence_score=old, semantic_score=fusion, frequency_score=fusion,
                           fusion_score=fusion, latency_ms=1)
            s.add(p)
            s.flush()
            ids.append(p.prediction_id)
        s.commit()
    finally:
        s.close()

    cfg = Config(str(db.BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False

    def confidences():
        with db.engine.connect() as c:
            rows = c.execute(text("SELECT prediction_id, confidence_score FROM predictions")).fetchall()
        return {pid: conf for pid, conf in rows if pid in ids}

    with db.engine.begin() as connection:  # back to 0003 = the old rule
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0003")
    old = confidences()
    assert old[ids[0]] == pytest.approx(1 - 0.5233)  # the reported "Real, 47.7 %"
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0005")  # through 0004: margin from tau, unscaled
    new = confidences()
    tau = 0.7558
    margins = {}
    for pid, (fusion, cls) in zip(ids, cases):
        margins[pid] = (fusion - tau) / (1 - tau) if cls == "AI Generated" else (tau - fusion) / tau
        assert new[pid] == pytest.approx(0.5 + 0.5 * margins[pid])
        assert new[pid] >= 0.5
    assert new[ids[0]] == pytest.approx(0.6538, abs=1e-3)

    # 0006c (2026-10-09): the same margin scaled by 0.86, so 0.5 - 0.93.
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0006c")
    scaled = confidences()
    for pid in ids:
        assert scaled[pid] == pytest.approx(0.5 + 0.5 * 0.86 * min(1.0, margins[pid]))
        assert 0.5 <= scaled[pid] <= 0.93
    # 0007 (2026-10-10) removes the scale again: back to 0004's rule ...
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0007")
    assert confidences() == pytest.approx(new)
    # ... and each step reverts exactly.
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0006c")
    assert confidences() == pytest.approx(scaled)
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0005")
    assert confidences() == pytest.approx(new)
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")  # back to head for the tests that follow
