# Backend

Python 3.11 FastAPI service for TruePixels.rgb. The backend is divided by the three product modules and a shared layer.

## Folders

- `app/`: application source code.
- `migrations/`: Alembic database migration scripts.
- `tests/`: backend-focused unit and API tests.

The module that owns a data store is the only module allowed to write to it. Cross-module data shapes belong in `app/shared/contracts`.