"""How a prediction's P(AI) is shown - one source for the results view, the
history list and the PDF, so the three can never word it differently.

C2 v2 (2026-10-08) replaced "confidence in the predicted class" and its
High / Moderate / Low bands (PRD3: 85 / 65 cutoffs, no empirical basis) with:

- p_ai: the likelihood that the image is AI-generated, for EITHER verdict,
  stored in D4 by M2 and capped to [1 %, 99 %] - 400 validation images cannot
  support finer figures, so the ends read "≤ 1 %" / "≥ 99 %";
- certainty: 'confident' (p_ai >= 90 % or <= 10 %) or 'inconclusive',
  thresholds measured on the validation split, not chosen by eye.

The verdict itself is unchanged and still comes from the threshold
(fusion_score >= tau). Because tau sits above even odds to keep false alarms
on genuine photographs at <= 10 %, a "Real" verdict can carry p_ai > 50 %;
that is said plainly ("leans AI, below the detection threshold") rather than
hidden. p_ai is NULL when the model configuration that ran is not the one the
figure was calibrated for: no number is invented then.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# A STORED row: the configuration that produced it is what matters, not what
# is active now. (M2's live POST response speaks of the active configuration.)
NOT_CALIBRATED = ("Likelihood not available: not calibrated for the model configuration used for "
                  "this prediction.")
LEANS_AI = "Leans AI, below detection threshold."
SEMANTIC_ONLY = ("Low reliability: this image is smaller than the frequency detector's 224-pixel "
                 "patch, so the verdict rests on the semantic detector alone, which "
                 "separates AI-generated from real images far less reliably. Treat this result as a "
                 "weak signal; it is always shown as inconclusive.")
CERTAINTY_LABEL = {"confident": "Confident", "inconclusive": "Inconclusive"}


@dataclass(frozen=True)
class Likelihood:
    p_ai: float | None
    p_ai_percentage: int | None  # whole percent; the [1, 99] cap makes finer digits meaningless
    p_ai_display: str | None  # "12 %", "≤ 1 %", "≥ 99 %"
    certainty: Literal["confident", "inconclusive"] | None
    certainty_label: str | None
    semantic_only: bool
    leans_ai_below_threshold: bool
    headline: str  # one line: "12 % likelihood AI-generated", or the not-calibrated sentence
    calibration_ref: str | None = None  # which fitted map produced p_ai (D4); None with p_ai
    notes: list[str] = field(default_factory=list)


def describe(prediction) -> Likelihood:
    """The display fields for one D4 row (or anything with the same attributes)."""
    p = prediction.p_ai
    semantic_only = prediction.frequency_score is None
    notes = [SEMANTIC_ONLY] if semantic_only else []
    if p is None:
        return Likelihood(p_ai=None, p_ai_percentage=None, p_ai_display=None, certainty=None,
                          certainty_label=None, semantic_only=semantic_only,
                          leans_ai_below_threshold=False, headline=NOT_CALIBRATED, calibration_ref=None,
                          notes=notes)
    if p <= 0.01:
        display = "≤ 1 %"
    elif p >= 0.99:
        display = "≥ 99 %"
    else:
        display = f"{round(p * 100)} %"
    leans = prediction.predicted_class == "Real" and p > 0.5
    if leans:
        notes = [LEANS_AI, *notes]
    return Likelihood(p_ai=p, p_ai_percentage=round(p * 100), p_ai_display=display,
                      certainty=prediction.certainty, certainty_label=CERTAINTY_LABEL.get(prediction.certainty),
                      semantic_only=semantic_only, leans_ai_below_threshold=leans,
                      headline=f"{display} likelihood AI-generated",
                      calibration_ref=getattr(prediction, "calibration_ref", None), notes=notes)
