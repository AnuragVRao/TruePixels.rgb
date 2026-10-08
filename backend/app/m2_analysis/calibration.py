"""P(AI) shown to the user, and its certainty label (2026-10-08).

The verdict is decided elsewhere and is NOT touched here: "AI Generated" iff
the combined score S >= tau (fusion.combine). tau sits where it does to hold
the false-positive rate on genuine photographs at <= 10 %, not at even odds,
so S = tau is not a coin toss: on validation, P(AI | S = tau) = 0.70.

This module turns S into the number displayed beside the verdict - the
likelihood that the image is AI-generated, for BOTH verdicts:

    P(AI) = clip(sigmoid(a * logit(S) + b + log(prior / (1 - prior))), 0.01, 0.99)

a and b are two constants per map, fitted on the validation split by
ml/calibration/fit_calibration.py and stored in shared/config.py. No model
weight is involved. Two maps:

- fused: S = w * semantic + (1 - w) * frequency. On validation this map is
  close to the identity (a = 0.93, b = -0.22): the combined score at w = 0.25
  was already approximately calibrated there, and the map adds no measurable
  gain. What it adds is the cap and the provenance check.
- semantic-only: SPAI had no evidence (image under 224 px), so S is the
  semantic score alone - a weaker, differently distributed score (AUC 0.67 on
  validation). Its own map is much flatter, and its certainty is ALWAYS
  "inconclusive" (see ``calibrated``).

Both are measured on unprocessed images (pristine camera TIFFs vs 2022-23
generators). They say nothing about resized images, on which SPAI misses far
more fakes: a low P(AI) on a resized image is not evidence that it is real.

Null, not a guess: a map is used only with the configuration it was fitted on
(``applies``). With anything else active - another fusion weight, an uploaded
head, a different SPAI sign or resize setting - P(AI) and certainty are None.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from app.m2_analysis.registry import ActiveModelSet
from app.shared import config

Certainty = Literal["confident", "inconclusive"]

WEIGHT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Calibrated:
    p_ai: float | None
    certainty: Certainty | None
    ref: str | None  # which fitted map produced p_ai (config.CALIBRATION_*_REF)


NOT_CALIBRATED = Calibrated(p_ai=None, certainty=None, ref=None)


def _logit(p: float) -> float:
    eps = config.CALIBRATION_LOGIT_EPS
    clamped = min(max(p, eps), 1.0 - eps)
    return math.log(clamped / (1.0 - clamped))


def _sigmoid(x: float) -> float:
    # Both branches are overflow-safe for any finite x.
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def p_ai(score: float, *, semantic_only: bool, prior: float | None = None) -> float:
    """Map a score to the displayed P(AI), in [CALIBRATION_P_MIN, CALIBRATION_P_MAX].

    Args:
        score: the combined score S, or the semantic score when ``semantic_only``.
        semantic_only: use the semantic-only map (SPAI had no evidence).
        prior: prior probability of AI among submitted images. Default
            config.CALIBRATION_PRIOR (0.5, the balance of the fitting split,
            which adds nothing). Any other value adds log(prior / (1 - prior))
            to the logit - and voids the validated certainty figures, which
            were measured at 0.5. Not exposed in the UI.
    """
    if semantic_only:
        a, b = config.CALIBRATION_SEMANTIC_ONLY_A, config.CALIBRATION_SEMANTIC_ONLY_B
    else:
        a, b = config.CALIBRATION_FUSED_A, config.CALIBRATION_FUSED_B
    prior = config.CALIBRATION_PRIOR if prior is None else prior
    if not 0.0 < prior < 1.0:
        raise ValueError(f"prior must be in (0, 1), got {prior}")
    z = a * _logit(score) + b + math.log(prior / (1.0 - prior))
    return min(config.CALIBRATION_P_MAX, max(config.CALIBRATION_P_MIN, _sigmoid(z)))


def certainty(p: float) -> Certainty:
    """'confident' iff P(AI) >= CERTAINTY_CONFIDENT_P or <= 1 - it (both inclusive)."""
    band = config.CERTAINTY_CONFIDENT_P
    return "confident" if p >= band or p <= 1.0 - band else "inconclusive"


def applies(models: ActiveModelSet, *, semantic_only: bool) -> bool:
    """Was the relevant map fitted on exactly this configuration?

    Compared by the D3 rows' artifact_sha256, never by a "published" flag. A
    missing hash counts as a mismatch.
    """
    semantic_ok = (models.primary.artifact_sha256 is not None
                   and models.primary.artifact_sha256 == config.CALIBRATION_FIT_SEMANTIC_SHA256)
    if semantic_only:
        return semantic_ok
    freq = models.frequency_detector
    return (semantic_ok and freq is not None
            and abs(models.fusion.weight - config.CALIBRATION_FIT_WEIGHT) <= WEIGHT_TOLERANCE
            and freq.artifact_sha256 is not None
            and freq.artifact_sha256 == config.CALIBRATION_FIT_FREQUENCY_SHA256
            and freq.ai_is_positive == config.CALIBRATION_FIT_FREQUENCY_AI_IS_POSITIVE
            and freq.resize_to == config.CALIBRATION_FIT_FREQUENCY_RESIZE_TO)


def calibrated(models: ActiveModelSet, fusion_score: float, *, semantic_only: bool) -> Calibrated:
    """P(AI), certainty and map reference for one prediction - or all None if no map applies."""
    if not applies(models, semantic_only=semantic_only):
        return NOT_CALIBRATED
    p = p_ai(fusion_score, semantic_only=semantic_only)
    if semantic_only:
        # Forced, not computed. The map would call a semantic score <= ~6e-5 or
        # >= ~0.9999 "confident", but every validation semantic score lies in
        # 0.0032-0.9997, so those band edges are outside anything measured and
        # no accuracy figure exists for a confident semantic-only result. On
        # validation the map put 0 of 396 images outside the band, and the
        # tau-verdict on the semantic score alone was right on 0.593 of them.
        return Calibrated(p_ai=p, certainty="inconclusive", ref=config.CALIBRATION_SEMANTIC_ONLY_REF)
    return Calibrated(p_ai=p, certainty=certainty(p), ref=config.CALIBRATION_FUSED_REF)
