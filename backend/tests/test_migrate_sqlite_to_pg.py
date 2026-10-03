"""backend/scripts/migrate_sqlite_to_pg.py, end to end (PostgreSQL only)."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.shared import db

pytestmark = pytest.mark.skipif(
    not db.DATABASE_URL.startswith("postgresql"),
    reason="needs PostgreSQL (TEST_DATABASE_URL)",
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_sqlite_to_pg.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_sqlite_to_pg", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_sqlite(path: Path, upload_ref: str) -> None:
    """A source shaped like the pre-Phase-2 app's database: naive timestamps,
    0/1 booleans, JSON stored as text."""
    db.import_all_models()
    legacy = create_engine(f"sqlite:///{path.as_posix()}")
    db.Base.metadata.create_all(legacy)
    legacy.dispose()
    con = sqlite3.connect(path)
    con.executescript(f"""
        INSERT INTO users VALUES (7, 'Legacy', 'legacy@example.com', 'h', 'User', 'active',
                                  '2026-10-01 17:36:47.790204', NULL, NULL, 1);
        INSERT INTO models VALUES (4, 'fusion', 'v1', 'fusion-configuration', 'cfg', NULL,
                                   '{{"tau": 0.7558}}', NULL, 1, '2026-10-01 17:00:00');
        INSERT INTO images VALUES (9, 7, '{upload_ref}', '{"a" * 64}', 'PNG', 10, 1, 1,
                                   '2026-10-01 17:40:00', 'valid', NULL);
        INSERT INTO predictions VALUES (11, 9, 4, '{{"semantic": 4}}', 'Real', 0.9, 0.1, NULL,
                                        0.1, 900, NULL, '2026-10-01 17:41:00');
        INSERT INTO logs VALUES (21, 7, 'authentication', 'login', 'info', NULL,
                                 '2026-10-01 17:42:00');
    """)
    con.commit()
    con.close()


def test_copies_converts_resets_sequences_and_reports_missing_files(tmp_path, monkeypatch, capsys):
    source = tmp_path / "legacy.db"
    missing = str(tmp_path / "gone.png")
    _legacy_sqlite(source, missing)
    before = source.read_bytes()

    monkeypatch.setattr(sys, "argv", ["migrate", "--source", str(source),
                                      "--target", db.DATABASE_URL, "--apply"])
    assert _load_script().main() == 0
    out = capsys.readouterr().out

    assert source.read_bytes() == before  # the source is never modified
    assert "COMMITTED" in out and "gone.png" in out and "rows kept" in out
    with db.engine.connect() as c:
        registered, verified = c.execute(text(
            "SELECT registered_at, is_email_verified FROM users WHERE user_id = 7")).one()
        assert registered.tzinfo is not None and registered.utcoffset() == timezone.utc.utcoffset(None)
        assert verified is True
        assert c.execute(text("SELECT hyperparameters->>'tau' FROM models")).scalar_one() == "0.7558"
        assert c.execute(text("SELECT file_reference FROM images")).scalar_one() == missing
        # Sequences continue after the copied ids instead of colliding with them.
        assert c.execute(text("SELECT nextval(pg_get_serial_sequence('predictions', 'prediction_id'))")).scalar_one() == 12
        assert c.execute(text("SELECT nextval(pg_get_serial_sequence('users', 'user_id'))")).scalar_one() == 8


def test_refuses_to_merge_into_a_non_empty_target(tmp_path, monkeypatch):
    source = tmp_path / "legacy.db"
    _legacy_sqlite(source, str(tmp_path / "x.png"))
    with db.engine.begin() as c:
        c.execute(text("INSERT INTO users (full_name, email, password_hash, role, account_status, "
                       "registered_at, is_email_verified) VALUES ('x', 'x@x.x', 'h', 'User', "
                       "'active', now(), true)"))
    monkeypatch.setattr(sys, "argv", ["migrate", "--source", str(source),
                                      "--target", db.DATABASE_URL, "--apply"])
    with pytest.raises(SystemExit, match="not empty"):
        _load_script().main()


def _empty_legacy(path: Path) -> sqlite3.Connection:
    db.import_all_models()
    legacy = create_engine(f"sqlite:///{path.as_posix()}")
    db.Base.metadata.create_all(legacy)
    legacy.dispose()
    con = sqlite3.connect(path)
    # The pre-Phase-2 schema had neither of Phase 2's new unique indexes, and
    # plain sqlite3 does not enforce foreign keys - so it could hold exactly
    # the rows the pre-checks exist to catch.
    con.executescript("DROP INDEX uq_users_email_lower; DROP INDEX uq_models_one_active_per_type;")
    return con


def test_many_rows_mixed_case_emails_and_id_gaps(tmp_path, monkeypatch, capsys):
    """250 users with mixed-case (but unique) emails and gapped ids, 400 logs:
    everything copied, case preserved, sequences continue after the max id."""
    source = tmp_path / "many.db"
    con = _empty_legacy(source)
    users = [(i * 3, f"User{i}@Example.COM") for i in range(1, 251)]  # ids 3, 6, ..., 750
    con.executemany(
        "INSERT INTO users VALUES (?, 'U', ?, 'h', 'User', 'active', '2026-10-01 10:00:00', NULL, NULL, 0)",
        users)
    con.executemany(
        "INSERT INTO logs VALUES (?, ?, 'authentication', 'x', 'info', NULL, '2026-10-01 10:00:00')",
        [(i * 2, users[i % 250][0]) for i in range(1, 401)])  # ids up to 800
    con.commit()
    con.close()

    monkeypatch.setattr(sys, "argv", ["m", "--source", str(source), "--target", db.DATABASE_URL, "--apply"])
    assert _load_script().main() == 0
    assert "0 problem(s)" in capsys.readouterr().out
    with db.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM users")).scalar_one() == 250
        assert c.execute(text("SELECT count(*) FROM logs")).scalar_one() == 400
        assert c.execute(text(
            "SELECT email FROM users WHERE lower(email) = 'user17@example.com'")).scalar_one() == "User17@Example.COM"
        assert c.execute(text("SELECT nextval(pg_get_serial_sequence('users', 'user_id'))")).scalar_one() == 751
        assert c.execute(text("SELECT nextval(pg_get_serial_sequence('logs', 'log_id'))")).scalar_one() == 801


def test_violations_are_all_reported_and_nothing_is_copied(tmp_path, monkeypatch, capsys):
    """Case-only duplicate emails, two active models of one type and an orphan
    row: refused before any insert, every finding listed."""
    source = tmp_path / "bad.db"
    con = _empty_legacy(source)
    con.executescript("""
        INSERT INTO users VALUES (1, 'A', 'Same@Example.com', 'h', 'User', 'active', '2026-10-01 10:00:00', NULL, NULL, 1);
        INSERT INTO users VALUES (2, 'B', 'same@example.COM', 'h', 'User', 'active', '2026-10-01 10:00:00', NULL, NULL, 1);
        INSERT INTO models VALUES (1, 'f', 'a', 'fusion-configuration', 'c', NULL, NULL, NULL, 1, '2026-10-01 10:00:00');
        INSERT INTO models VALUES (2, 'f', 'b', 'fusion-configuration', 'c', NULL, NULL, NULL, 1, '2026-10-01 10:00:00');
        INSERT INTO logs VALUES (1, 99, 'authentication', 'x', 'info', NULL, '2026-10-01 10:00:00');
    """)
    con.commit()
    con.close()

    monkeypatch.setattr(sys, "argv", ["m", "--source", str(source), "--target", db.DATABASE_URL, "--apply"])
    with pytest.raises(SystemExit, match="nothing was copied"):
        _load_script().main()
    out = capsys.readouterr().out
    assert "3 problem(s)" in out
    assert "equal apart from case" in out and "ACTIVE model" in out and "logs whose user" in out
    with db.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
