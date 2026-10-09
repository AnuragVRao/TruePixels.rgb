"""HTTP response shapes for M2's endpoints.

This is the PUBLIC half of Contract C2 and nothing else. The ActivationBundle
never appears here: it is an in-process structure only (Contract C2 section
5.4), and serialising attention tensors to a browser would be both large and
pointless.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.shared.contracts.c2 import InferenceOutput
from app.shared.schemas import ErrorDetail


class PredictionResponse(BaseModel):
    """One prediction, as returned to a caller."""

    prediction_id: int = Field(
        description="D4 row id, committed before this response was sent.",
    )
    image_id: int
    user_id: int
    model_id: int = Field(
        description="D3 row of the fusion configuration active at inference.",
    )
    predicted_class: Literal["Real", "AI Generated"] = Field(
        description="Binary only - never 'uncertain', never a third class (AC-01)."
    )
    confidence_score: float = Field(
        description=(
            "Confidence IN predicted_class, not P(AI Generated). "
            "Measured from the decision threshold tau: 0.5 at tau, rising with the distance "
            "from it, never below 0.5. A margin, not a calibrated probability."
        )
    )
    semantic_score: float = Field(
        description=(
            "P(AI Generated) from the semantic branch - the pretrained "
            "SigLIP 2 fine-tune."
        )
    )
    frequency_score: float | None = Field(
        default=None,
        description=(
            "P(AI Generated) from the frequency branch - SPAI, a pretrained "
            "spectral detector reading the native-resolution image. Null when "
            "that branch had no evidence: it is switched off, or the image is "
            "under its 224px patch size. The verdict is then the semantic "
            "branch alone - treat null as 'not measured', never as zero."
        ),
    )
    fusion_score: float = Field(
        description="P(AI Generated) after fusing the two branch scores."
    )
    prediction_timestamp: datetime
    latency_ms: int = Field(
        description="Inference time only (both branches + fusion); excludes model "
                    "loading and explainability (see the X-XAI-Time-Ms header)."
    )
    xai_status: Literal["not_requested", "generated", "partial", "unavailable"] = Field(
        default="not_requested",
        description=(
            "Explainability outcome (SRS C.3). 'partial': one panel was produced "
            "(e.g. no frequency panel for an image under SPAI's 224px patch). "
            "'unavailable': none - the prediction itself is still valid."
        ),
    )
    xai_reasons: list[str] = Field(default_factory=list,
                                   description="Reason codes when xai_status is not 'generated'.")

    @classmethod
    def from_contract(cls, output: InferenceOutput, **extra) -> "PredictionResponse":
        """Project an InferenceOutput onto its public half."""
        return cls(**output.model_dump(exclude={"activations"}), **extra)


class ErrorResponse(BaseModel):
    """A failure, in the shared error envelope (Interface Contract 3.4).

    M2's own codes are the PRD2 section 11 INF_* set; M1's AUTH_* and IMG_*
    codes also reach this endpoint through its dependencies.
    """

    error: ErrorDetail
