"""Load both detectors at startup, so no user request pays for it.

Both branches load lazily (NF.4). Without a warm-up the first prediction after
a boot also downloads/reads the checkpoints, verifies the SPAI digest and
initialises CUDA - about 20 s on the development laptop against roughly 1 s
warm - and that time was being recorded as that request's ``latency_ms``.

The warm-up runs one forward pass per branch on a fixed synthetic image, which
also gets CUDA kernel initialisation out of the way. It never stops the
server from starting: a failure is logged and the affected branch falls back to
loading on first use, reporting INF_MODEL_UNAVAILABLE there if it really
cannot load - exactly the behaviour without a warm-up.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from app.m2_analysis import detectors, frequency_detector
from app.shared import config

# uvicorn's logger, so the lines appear in the server console without extra
# logging configuration.
logger = logging.getLogger("uvicorn.error")

# 448x448 so SPAI scores more than one 224 px patch, as a real image would.
_SIZE = 448


def warm_up() -> dict[str, float | str]:
    """Load and exercise each enabled branch once. Returns seconds per branch.

    A branch that fails maps to the error text instead of a duration.
    """
    timings: dict[str, float | str] = {}
    with tempfile.TemporaryDirectory(prefix="truepixels-warmup-") as scratch:
        path = Path(scratch) / "warmup.png"
        pixels = np.random.default_rng(0).integers(0, 256, size=(_SIZE, _SIZE, 3), dtype=np.uint8)
        Image.fromarray(pixels, mode="RGB").save(path)

        branches = [("semantic", detectors.primary)]
        if config.DETECTOR_FREQUENCY_ENABLED:
            branches.append(("frequency", frequency_detector.frequency))

        for name, branch in branches:
            started = time.perf_counter()
            try:
                branch.score(str(path))
            except Exception as exc:  # noqa: BLE001 - never block startup
                timings[name] = f"failed: {exc}"
                logger.warning("warm-up of the %s branch failed; it will load on first use: %s",
                               name, exc)
                continue
            timings[name] = round(time.perf_counter() - started, 3)
            logger.info("warm-up: %s branch ready in %.1f s", name, timings[name])
    return timings
