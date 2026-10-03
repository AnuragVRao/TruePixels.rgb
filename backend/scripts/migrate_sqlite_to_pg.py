"""Copy an existing TruePixels SQLite database into PostgreSQL. Read-only on the source.

    cd backend
    alembic upgrade head                                 # target schema first
    python scripts/migrate_sqlite_to_pg.py --source truepixels.db             # dry run
    python scripts/migrate_sqlite_to_pg.py --source truepixels.db --apply

The target is DATABASE_URL (backend/.env) unless --target is given. The
source SQLite file is opened read-only and never modified.

What it does, in one transaction on the target:

1. Refuses unless the target is at Alembic head and every table is EMPTY -
   it never merges into or overwrites existing data.
2. Copies D1 users, D3 models, D2 images, D4 predictions, D5 explainability,
   D6 logs, in foreign-key order, keeping every primary key.
3. Converts on the way: naive SQLite timestamps are UTC by construction (the
   app only ever writes datetime.now(timezone.utc)) and are marked as such;
   SQLite's 0/1 booleans become real booleans; JSON text becomes JSON.
4. Resets every id sequence to max(id) + 1, so the next insert does not
   collide with a copied row.
5. Checks the row count of every table matches the source.

File references (D2 file_reference, D5 visualization_reference) are copied
unchanged. Ones pointing at files that no longer exist are reported, never
dropped: the row is still a true record of what happened. (The deprecated
C1 tensor_ref was never stored in the database, so there is nothing of it to
migrate; any leftover storage/tensors/ folder is unused.)

The copy fails, and nothing is committed, if a row breaks a constraint the
SQLite file never enforced - foreign keys, case-insensitive email uniqueness
or one active model per type. Such rows need a decision, not a silent fix.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import Boolean, DateTime, JSON, func, insert, select, text  # noqa: E402

from app.shared import db  # noqa: E402

# Parents before children.
ORDER = ["users", "models", "images", "predictions", "explainability", "logs"]
FILE_COLUMNS = {"images": "file_reference", "explainability": "visualization_reference"}


def _convert(column, value):
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(column.type, Boolean):
        return bool(int(value))
    if isinstance(column.type, JSON):
        return json.loads(value) if isinstance(value, str) else value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="path to the SQLite file (opened read-only)")
    parser.add_argument("--target", help="target database URL (default: DATABASE_URL)")
    parser.add_argument("--apply", action="store_true", help="commit; without it, everything is rolled back")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    if not source_path.is_file():
        raise SystemExit(f"no such SQLite file: {source_path}")
    if args.target:
        db.configure_database(args.target)
    if db.engine.dialect.name != "postgresql":
        raise SystemExit(f"target must be PostgreSQL, got {db.engine.dialect.name}")
    db.import_all_models()
    db.check_schema_current()
    tables = {t.name: t for t in db.Base.metadata.sorted_tables}

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    present = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    print(f"source: {source_path} (read-only)")
    print(f"target: {db.engine.url.render_as_string(hide_password=True)}")

    counts: dict[str, int] = {}
    missing_files: list[str] = []
    with db.engine.connect() as target:
        transaction = target.begin()
        try:
            for name in ORDER:
                if target.execute(select(func.count()).select_from(tables[name])).scalar_one():
                    raise SystemExit(f"target table {name!r} is not empty; refusing to merge")

            for name in ORDER:
                table = tables[name]
                if name not in present:
                    counts[name] = 0
                    continue
                source_columns = {r[1] for r in source.execute(f"PRAGMA table_info({name})")}
                rows = []
                for raw in source.execute(f"SELECT * FROM {name} ORDER BY 1"):
                    row = {c.name: _convert(c, raw[c.name]) for c in table.columns if c.name in source_columns}
                    rows.append(row)
                    file_column = FILE_COLUMNS.get(name)
                    if file_column and row.get(file_column) and not Path(row[file_column]).is_file():
                        missing_files.append(f"{name}.{file_column}: {row[file_column]}")
                if rows:
                    target.execute(insert(table), rows)
                counts[name] = len(rows)
                not_copied = source_columns - {c.name for c in table.columns}
                note = f"  (source-only columns ignored: {sorted(not_copied)})" if not_copied else ""
                print(f"  {name:<15} {len(rows):>6} rows{note}")

            for name in ORDER:  # sequences: next id = max(id) + 1
                pk = list(tables[name].primary_key.columns)[0].name
                target.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', '{pk}'), "
                    f"COALESCE((SELECT MAX({pk}) FROM {name}), 0) + 1, false)"))

            for name in ORDER:  # verify
                copied = target.execute(select(func.count()).select_from(tables[name])).scalar_one()
                if copied != counts[name]:
                    raise SystemExit(f"row count mismatch in {name}: source {counts[name]}, target {copied}")

            if args.apply:
                transaction.commit()
            else:
                transaction.rollback()
        except BaseException:
            if transaction.is_active:
                transaction.rollback()
            raise
    source.close()

    if missing_files:
        print(f"\n{len(missing_files)} file reference(s) point at files that do not exist "
              "(copied unchanged, rows kept):")
        for line in missing_files:
            print(f"  {line}")
    print("\nrow counts verified; sequences reset to max(id) + 1")
    print("COMMITTED" if args.apply else "DRY RUN - rolled back. Re-run with --apply to commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
