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
