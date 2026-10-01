"""Database session management and declarative base.

Supports both SQLite (for local testing & development) and PostgreSQL (for production).

INTEGRATION NOTE: M1 and M3 each shipped an almost identical copy of this file.
This is M1's (it owns D1/D2 and ships init_db); M3's SQL_ECHO switch is kept
alongside M1's DEBUG switch so both teams' settings still work. See changes.md.
"""
import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./truepixels.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=(
        os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
        or os.getenv("SQL_ECHO", "false").lower() == "true"
    ),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Creates database tables if they do not exist.

    Imports every module that declares tables first, so that all of D1-D6 are
    registered on ``Base.metadata`` regardless of which router was imported
    first.
    """
    import app.m1_access.models  # noqa: F401  D1, D2
    import app.m2_analysis.models  # noqa: F401  D3, D4
    import app.m3_results.models  # noqa: F401  D5, D6

    Base.metadata.create_all(bind=engine)
