"""FR-03 / FR-04 - Decision fusion, calibration and thresholding (DFD 0.4.3-0.4.4).

Where the two opinions are reconciled into a single verdict. The branches ask
different KINDS of question, and that is the whole argument for fusing them:

- the semantic branch (SigLIP 2 fine-tune) asks what the picture is of and
  whether it resembles the AI images it was trained on;
- the frequency branch (SPAI) asks whether the pixel grid carries the spectral
  signature of a synthesis pipeline, and ignores the content.

A generator that defeats one has no particular reason to have defeated the
other. This is PRD2 section 1.3's independence argument as originally made -
"learned visual semantics vs physical frequency-domain fingerprints" - now
realised with two pretrained models rather than two heads we trained.

w = 0.25 and tau = 0.7558 were selected on a validation split (2026-10-01):
configuration constants, not model weights - see shared/config.py. tau holds
the false-positive rate on genuine photographs at <= 10 %, so it sits above
even odds.

This module decides the VERDICT only. The number shown beside it - P(AI), for
both verdicts - and its certainty label come from calibration.py and never
change the verdict.
"""

from __future__ import annotations

import math
from typing import Literal

from app.m2_analysis.registry import FusionModelConfig
from app.shared.contracts.errors import InferenceError

PredictedClass = Literal["Real", "AI Generated"]


def apply_temperature(probability: float, temperature: float) -> float:
    """Temperature-scale a probability (PRD2 FR-04 calibration).

    Raw sigmoid outputs are not probabilities and are typically overconfident.
    PRD2 wants one scalar fitted on a validation split to correct that, with
    the resulting expected calibration error reported as MM2.5. Fitting is
    training, so T stays at 1.0 and this is a documented no-op.

    Scaling happens in logit space, which is where the temperature belongs.
    """
    if temperature == 1.0:
        return probability

    clamped = min(max(probability, 1e-7), 1 - 1e-7)
    logit = math.log(clamped / (1 - clamped))
    return 1.0 / (1.0 + math.exp(-logit / temperature))


def combine(
    semantic_score: float,
    frequency_score: float | None,
    model: FusionModelConfig,
) -> tuple[float, PredictedClass]:
    """Fuse the branch scores into a fused score and a verdict.

    Args:
        semantic_score: P(AI Generated) from the semantic branch (SigLIP 2).
        frequency_score: P(AI Generated) from the frequency branch (SPAI), or
            None when that branch is disabled. With None, fusion is an
            explicit passthrough of the semantic score - documented, not a
            silent degradation, and never a fabricated second opinion.
        model: the active fusion configuration.

    Returns:
        (fusion_score, predicted_class). fusion_score is a SCORE, higher = more
        AI-like; it is not a probability. The displayed P(AI) is
        calibration.calibrated(), applied after this and never altering it.
    """
    if model.strategy != "weighted_average":
        raise InferenceError(f"unsupported fusion strategy: {model.strategy!r}")

    if frequency_score is None:
        # Passthrough: one branch, so there is nothing to fuse.
        fused = semantic_score
    else:
        # PRD2 FR-03 strategy A: fusion = w * semantic + (1 - w) * frequency.
        fused = (
            model.weight * semantic_score
            + (1.0 - model.weight) * frequency_score
        )

    fusion_score = apply_temperature(fused, model.temperature)

    predicted_class: PredictedClass = (
        "AI Generated" if fusion_score >= model.tau else "Real"
    )
    return fusion_score, predicted_class


def legacy_confidence_score(fusion_score: float, tau: float, predicted_class: str) -> float:
    """DEPRECATED (2026-10-08) - kept ONLY to fill D4's legacy NOT NULL
    ``confidence_score`` column until the migration that drops it. It is not
    part of Contract C2 v2, no API returns it and nothing may display it: the
    user-facing number is P(AI) from calibration.py. Delete with the column.

    The rule it implements (2026-10-05, changes.md 6.21): 0.5 exactly at tau,
    rising linearly to 1.0 at the far end of the predicted side:

        AI Generated:  0.5 + 0.5 * (fusion - tau) / (1 - tau)
        Real:          0.5 + 0.5 * (tau - fusion) / tau

    Why not PRD2 FR-04's ``fusion`` / ``1 - fusion``: that rule assumes
    tau = 0.5. With the operating point tau = 0.7558 (chosen on a validation
    split to hold false positives down), every fused score in [0.5, tau) is
    called "Real" while ``1 - fusion`` is below 0.5 - a verdict displayed as
    e.g. "Real, 47.7 %", which contradicts itself. This formula can never
    fall below 0.5, is monotonic, and at tau = 0.5 reduces EXACTLY to the old
    rule (so FR-04's "0.08 -> Real at 0.92" still holds there).

    It is a margin from the threshold, fitted to no data.
    """
    if predicted_class == "AI Generated":
        margin = (fusion_score - tau) / (1.0 - tau) if tau < 1.0 else 1.0
    else:
        margin = (tau - fusion_score) / tau if tau > 0.0 else 1.0
    return min(1.0, max(0.5, 0.5 + 0.5 * margin))
