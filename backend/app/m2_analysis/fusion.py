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
    class was actually predicted. A fusion_score of 0.08 yields "Real" with
    confidence 0.92.

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
    confidence_score = (
        fusion_score if predicted_class == "AI Generated" else 1.0 - fusion_score
    )

    return fusion_score, predicted_class, confidence_score
