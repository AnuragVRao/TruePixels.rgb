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
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_SCRATCH / 'test.db').as_posix()}")
os.environ.setdefault("STORAGE_DIR", str(_SCRATCH / "storage"))
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("REQUIRE_2FA", "False")


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
    """Opt-in: the test fails if any D6 write raised during it.

    Opt-in for now because several suites still point the logger at a
    database without a ``logs`` table (M1's conftest sets an in-memory
    DATABASE_URL); Phase 2 fixes the test database wiring and can make this
    autouse.
    """
    from app.m3_results import logging_service

    logging_service.WRITE_FAILURES.clear()
    yield
    assert_no_swallowed_log_writes()
