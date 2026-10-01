"""Exported FastAPI dependencies for authentication and role-based access control.

Imported by Module M2 and Module M3 across the system boundary (Contract C3).

INTEGRATION NOTE: this is M1's file unchanged. M3 shipped a mock version of it
(an in-memory ACTIVE_SESSIONS table of fixed test tokens); that mock now lives
only in backend/tests/m3/conftest.py, where it overrides this dependency for
M3's own test suite. See changes.md.
"""
from app.m1_access.security import current_session, require_role

__all__ = ["current_session", "require_role"]
