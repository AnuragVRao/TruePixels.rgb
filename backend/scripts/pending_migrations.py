"""Which Alembic migrations are pending on the configured database? (read-only)

    python scripts/pending_migrations.py        # from backend/

Prints one JSON object for start.ps1:

    {"current": "0005", "head": "0007", "dialect": "postgresql", "database": "truepixels",
     "sqlite_path": null,
     "pending": [{"revision": "0006", "attended_only": false, "title": "..."},
                 {"revision": "0007", "attended_only": true,  "title": "..."}]}

A migration is ATTENDED-ONLY when its module sets ``ATTENDED_ONLY = True``:
one that destroys data or cannot be cleanly undone (a contract step that drops
a column). start.ps1 never applies such a migration on its own; it stops and
says how to apply it by hand. Every pending migration, attended or not, is
preceded by a pg_dump that must succeed.

``dialect`` / ``database`` / ``sqlite_path`` name the database Alembic WILL
migrate (DATABASE_URL), so the backup is of that database and no other.

TRUEPIXELS_MIGRATIONS_DIR (tests only) points at another versions directory.

Exit status: 0 on success (pending may be empty), 1 if the database cannot be
read. Nothing is written.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def pending() -> dict:
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.shared import db

    cfg = Config(str(BACKEND / "alembic.ini"))
    if os.getenv("TRUEPIXELS_MIGRATIONS_DIR"):
        cfg.set_main_option("version_locations", os.environ["TRUEPIXELS_MIGRATIONS_DIR"])
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    with db.engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    revisions = list(script.iterate_revisions(head, current))  # newest first, current excluded
    out = []
    for rev in reversed(revisions):
        doc = (rev.doc or "").strip().splitlines()
        out.append({"revision": rev.revision,
                    "attended_only": bool(getattr(rev.module, "ATTENDED_ONLY", False)),
                    "title": doc[0] if doc else ""})
    url = db.engine.url
    sqlite_path = None
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        sqlite_path = str(Path(url.database).resolve())
    return {"current": current, "head": head, "dialect": url.get_backend_name(), "database": url.database,
            "sqlite_path": sqlite_path, "pending": out}


def main() -> int:
    import logging

    logging.disable(logging.CRITICAL)  # keep stdout pure JSON
    try:
        result = pending()
    except Exception as exc:  # noqa: BLE001 - report, never guess
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
