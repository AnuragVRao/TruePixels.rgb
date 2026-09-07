# Database Migrations

Alembic migrations for PostgreSQL 15. Schemas must remain aligned with data-store ownership: M1 owns D1 and D2, M2 owns D3 and D4, and M3 owns D5 and D6.

Enable PostgreSQL `citext` for case-insensitive email uniqueness and preserve foreign-key relationships required by the PRDs.