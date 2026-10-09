# Backend

The FastAPI service, on Python 3.13. Setup, configuration and run commands
are in the [repository README](../readme.md).

| Path | Contents |
|---|---|
| `app/m1_access/` | M1: accounts, sign-in and OTP challenges, throttling, upload validation, image storage |
| `app/m2_analysis/` | M2: the content detector (Community Forensics; SigLIP 2 pinned as rollback) and SPAI, fusion, explainability capture, model registry and quality gate |
| `app/m3_results/` | M3: results, history, PDF reports, administration, analytics, audit log |
| `app/shared/` | Configuration, database engine, proxy trust, errors, and the C1-C5 contracts between modules |
| `app/stubs/` | Fake M1/M2 used **only** by M3's test suite. Nothing under `app/` may import it. |
| `migrations/` | Alembic. The only way the schema is created or changed. |
| `scripts/` | `convert_spai_checkpoint.py`, `build_reference_set.py`, `migrate_sqlite_to_pg.py`, `verify_rotation.py` |
| `seed_admin.py` | Creates the first administrator |
| `tests/` | M2 and cross-module tests, plus M1's (`m1/`) and M3's (`m3/`) suites |
