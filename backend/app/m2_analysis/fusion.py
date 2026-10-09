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

w = 0.5 is an unweighted average, and tau = 0.5 is the detectors' own decision
boundary. Neither is fitted - fitting them would need a labelled validation
split, which is training and therefore out of scope. See shared/config.py.
"""

from __future__ import annotations

import math
from typing import Literal

from app.m2_analysis.registry import FusionModelConfig
from app.shared.config import CONFIDENCE_SCALE
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
) -> tuple[float, PredictedClass, float]:
    """Fuse the branch scores into a fused score, a label and a confidence.

    Args:
        semantic_score: P(AI Generated) from the semantic branch (SigLIP 2).
        frequency_score: P(AI Generated) from the frequency branch (SPAI), or
            None when that branch is disabled. With None, fusion is an
            explicit passthrough of the semantic score - documented, not a
            silent degradation, and never a fabricated second opinion.
        model: the active fusion configuration.

    Returns:
        (fusion_score, predicted_class, confidence_score)

THE INVERSION (PRD2 section 8.3, Contract C2 section 5.2). Three of the
    four score fields - semantic, frequency, fusion - are P("AI Generated").
    ``confidence_score`` is the odd one out: it is confidence in whichever
    class was actually predicted - see ``confidence_in_prediction``. At
    tau = 0.5 a fusion_score of 0.08 yields "Real" with confidence 0.861.

    PRD2 FR-04 names this the single most likely integration bug in the whole
    project, because it fails quietly and plausibly: a confidently-real image
    would display as 8% confident, which reads as a weak model rather than as
    a wiring error. It is asserted by tests on both sides of the C2 boundary.
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
    confidence_score = confidence_in_prediction(fusion_score, model.tau, predicted_class)

    return fusion_score, predicted_class, confidence_score


def confidence_in_prediction(fusion_score: float, tau: float, predicted_class: str,
                             scale: float = CONFIDENCE_SCALE) -> float:
    """Confidence in the PREDICTED class, measured from the decision threshold.

    0.5 exactly at tau, rising linearly to ``0.5 + 0.5 * scale`` at the far end
    of the predicted side - 0.93 with the configured scale of 0.86 (2026-10-09;
    the unscaled rule of 2026-10-05, changes.md 6.21, reached 1.0):

        AI Generated:  0.5 + 0.5 * 0.86 * (fusion - tau) / (1 - tau)
        Real:          0.5 + 0.5 * 0.86 * (tau - fusion) / tau

    The scale keeps a verdict from ever reading 100 %: this is a margin fitted
    to no data, so it should not claim certainty.

    Why not PRD2 FR-04's ``fusion`` / ``1 - fusion``: that rule assumes
    tau = 0.5. With the operating point tau = 0.7558 (chosen on a validation
    split to hold false positives down), every fused score in [0.5, tau) is
    called "Real" while ``1 - fusion`` is below 0.5 - a verdict displayed as
    e.g. "Real, 47.7 %", which contradicts itself. This formula can never
    fall below 0.5 and is monotonic in the margin from tau.

    It is a margin from the threshold, not a calibrated probability: the
    detectors' outputs are uncalibrated (MM2.5 is missed).
    """
    if predicted_class == "AI Generated":
        margin = (fusion_score - tau) / (1.0 - tau) if tau < 1.0 else 1.0
    else:
        margin = (tau - fusion_score) / tau if tau > 0.0 else 1.0
    margin = min(1.0, max(0.0, margin))
    return 0.5 + 0.5 * scale * margin
