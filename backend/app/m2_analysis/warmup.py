"""Load both detectors at startup, so no user request pays for it.

Both branches load lazily (NF.4). Without a warm-up the first prediction after
a boot also downloads/reads the checkpoints, verifies the SPAI digest and
initialises CUDA - about 20 s on the development laptop against roughly 1 s
warm - and that time was being recorded as that request's ``latency_ms``.

The warm-up runs one forward pass per branch on a fixed synthetic image, which
also gets CUDA kernel initialisation out of the way. It never stops the
server from starting: a failure is logged at ERROR (console and D6) and the
affected branch falls back to loading on first use, reporting
INF_MODEL_UNAVAILABLE there if it really cannot load.

Readiness: ``STATE`` records the outcome, and ``GET /ready`` answers 200 only
when it is ``ok`` (or ``disabled``, where lazy loading is the configured
behaviour) - so a load balancer or a deploy script can tell a server that
started from one that is actually able to classify.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image

from app.m2_analysis import detectors, frequency_detector
from app.shared import config

# uvicorn's logger, so the lines appear in the server console without extra
# logging configuration.
logger = logging.getLogger("uvicorn.error")

# 448x448 so SPAI scores more than one 224 px patch, as a real image would.
_SIZE = 448

Status = Literal["pending", "ok", "failed", "disabled"]
STATE: dict = {"status": "pending", "branches": {}}


def mark_disabled() -> None:
    STATE.update(status="disabled", branches={})


def _active_content_detector():
    """The content detector the ACTIVE D3 semantic row names (what requests will
    run); the config baseline if the registry cannot be read yet."""
    try:
        from app.m2_analysis import registry
        from app.shared.db import SessionLocal

        with SessionLocal() as db:
            return detectors.semantic(registry.active(db).primary.checkpoint)
    except Exception as exc:  # noqa: BLE001 - warm-up never blocks startup
        logger.warning("warm-up: could not read the active content detector (%s); warming the baseline", exc)
        return detectors.primary


def warm_up() -> dict[str, float | str]:
    """Load and exercise each enabled branch once. Returns seconds per branch.

    A branch that fails maps to the error text instead of a duration, and the
    overall ``STATE["status"]`` becomes ``failed``.
    """
    STATE.update(status="pending", branches={})
    timings: dict[str, float | str] = {}
    with tempfile.TemporaryDirectory(prefix="truepixels-warmup-") as scratch:
        path = Path(scratch) / "warmup.png"
        pixels = np.random.default_rng(0).integers(0, 256, size=(_SIZE, _SIZE, 3), dtype=np.uint8)
        Image.fromarray(pixels, mode="RGB").save(path)

        branches = [("semantic", _active_content_detector())]
        if config.DETECTOR_FREQUENCY_ENABLED:
            branches.append(("frequency", frequency_detector.frequency))

        for name, branch in branches:
            started = time.perf_counter()
            try:
                branch.score(str(path))
            except Exception as exc:  # noqa: BLE001 - never block startup
                timings[name] = f"failed: {exc}"
                logger.error("warm-up of the %s branch FAILED; the server is not ready and the "
                             "branch will try again on first use: %s", name, exc)
                _audit_failure(name, exc)
                continue
            timings[name] = round(time.perf_counter() - started, 3)
            logger.info("warm-up: %s branch ready in %.1f s", name, timings[name])

    failed = any(isinstance(v, str) for v in timings.values())
    STATE.update(status="failed" if failed else "ok", branches=dict(timings))
    return timings


def _audit_failure(branch: str, exc: Exception) -> None:
    """Also record the failure in D6, where admins look. Never raises."""
    try:
        from app.shared.logging import emit

        emit("error", f"Model warm-up failed for the {branch} branch: {type(exc).__name__}: {exc}",
             severity="error")
    except Exception:  # noqa: BLE001
        pass
