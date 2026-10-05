"""Shared test fixtures and path wiring.

Puts ``backend/`` on sys.path so ``app.*`` imports resolve the same way they do
when uvicorn is launched from that directory.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Must run before anything imports ``app``: the engine, M1's config and the
# shared storage root all read these at import time. Keeps every test - M1's,
# M2's and M3's - out of the developer's real database and storage tree. (The
# SPAI weights are not affected: config.MODELS_DIR ignores STORAGE_DIR.)
_SCRATCH = Path(tempfile.mkdtemp(prefix="truepixels-tests-"))

# The test database: SQLite in the scratch directory by default, or
# PostgreSQL via TEST_DATABASE_URL, e.g.
#   TEST_DATABASE_URL=postgresql+psycopg://truepixels:<pw>@127.0.0.1:5433/truepixels_test
# ASSIGNED, not setdefault: a DATABASE_URL in the shell or in backend/.env
# (the developer's real database) must never be the one the suite empties.
# A PostgreSQL test database must be named *_test, as a second guard.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", f"sqlite:///{(_SCRATCH / 'test.db').as_posix()}"
)
if TEST_DATABASE_URL.startswith("postgresql") and not TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0].endswith("_test"):
    raise RuntimeError(
        f"refusing to run the test suite against {TEST_DATABASE_URL.rsplit('@', 1)[-1]}: "
        "a PostgreSQL TEST_DATABASE_URL must name a database ending in '_test' "
        "(the suite empties every table after each test)"
    )
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("STORAGE_DIR", str(_SCRATCH / "storage"))
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("REQUIRE_2FA", "False")
os.environ.setdefault("WARMUP_ON_STARTUP", "False")  # models load lazily in tests


def make_image(width: int = 256, height: int = 256, seed: int = 7) -> Image.Image:
    """A deterministic synthetic RGB image."""
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    return Image.fromarray(pixels, mode="RGB")


def png_bytes(image: Image.Image) -> bytes:
    """Encode an image as PNG bytes."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def sample_png() -> bytes:
    """A deterministic PNG payload for upload tests."""
    return png_bytes(make_image())


@pytest.fixture
def image_file(tmp_path: Path) -> str:
    """A deterministic image written to disk, as the frequency branch reads it."""
    path = tmp_path / "sample.png"
    make_image().save(path)
    return str(path)


def assert_no_swallowed_log_writes() -> None:
    """Fail loudly if any D6 write was swallowed since the list was cleared.

    emit_log is non-throwing by design (a logging fault must never fail the
    request being logged), so in production a broken write only reaches
    stderr. In a test that silence would hide exactly the bug being tested
    for, so the failures emit_log records are turned into a test failure here.
    """
    from app.m3_results import logging_service

    failures = list(logging_service.WRITE_FAILURES)
    if failures:
        pytest.fail(
            f"{len(failures)} audit-log write(s) failed and were swallowed by emit_log:\n  "
            + "\n  ".join(failures),
            pytrace=False,
        )


@pytest.fixture
def strict_audit_log():
    """The test fails if any D6 write raised during it.

    Applied to every test by ``_strict_audit_log_everywhere``. A directory's
    conftest may override this fixture to exempt a test that writes a bad
    log row on purpose (M3's non-throwing test does).
    """
    from app.m3_results import logging_service

    logging_service.WRITE_FAILURES.clear()
    yield
    assert_no_swallowed_log_writes()


# --------------------------------------------------------------------------
# One test database for the whole run, built by the migrations
# --------------------------------------------------------------------------

def _reset_schema() -> None:
    """Drop everything, then build the schema with ``alembic upgrade head``.

    Building the test database through the migrations (not create_all) means
    every test run also exercises them.
    """
    from app.shared import db

    db.reset_scratch_database()  # guarded: TEST_DATABASE_URL must name a *_test database


def _empty_all_tables() -> None:
    """Remove every row; restart ids so each test starts from a clean state."""
    from sqlalchemy import text

    from app.shared import db

    tables = [t.name for t in reversed(db.Base.metadata.sorted_tables)]
    with db.engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # A session a test leaked would block TRUNCATE forever; fail instead.
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            connection.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        else:
            for name in tables:
                connection.execute(text(f"DELETE FROM {name}"))
            if connection.execute(
                text("SELECT name FROM sqlite_master WHERE name = 'sqlite_sequence'")
            ).first():
                connection.execute(text("DELETE FROM sqlite_sequence"))


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Point the whole app (requests, logging, pipeline) at the test database."""
    from app.shared import db

    db.configure_database(TEST_DATABASE_URL)
    _reset_schema()
    yield
    db.engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(_test_database):
    yield
    _empty_all_tables()


@pytest.fixture(autouse=True)
def _fresh_throttles():
    """Sign-in/OTP throttles are process-wide memory: start every test clean."""
    from app.m1_access import throttle

    throttle.reset()
    yield
    throttle.reset()


@pytest.fixture(autouse=True)
def _strict_audit_log_everywhere(strict_audit_log):
    """Every test fails if a D6 write was swallowed (see strict_audit_log)."""
    yield
