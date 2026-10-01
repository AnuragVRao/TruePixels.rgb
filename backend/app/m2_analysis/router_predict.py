"""HTTP endpoints for FR-01 to FR-05 (PRD2 section 10.1).

The client first uploads through M1 (``POST /api/v1/images``), which validates,
sanitises and stores the image and commits the D2 row. It then asks for a
prediction by ``image_id``. The image is resolved through M1's
``prepare_model_input`` - the in-process Contract C1 hand-off (PRD4 section
4.1) - and M2 writes the D4 row before responding.

Until the M1/M3 integration this endpoint took a multipart upload through a
temporary intake shim, with no authentication. Both are gone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.m1_access.models import Image as DBImage
from app.m1_access.preprocess import prepare_model_input
from app.m2_analysis import pipeline
from app.m2_analysis.schemas import ErrorResponse, PredictionResponse
from app.shared.contracts.errors import InferenceError
from app.shared.db import get_db
from app.shared.deps import current_session
from app.shared.errors import AppException, ImgNotFoundException
from app.shared.logging import emit
from app.shared.schemas import SessionContext

router = APIRouter(prefix="/api/v1", tags=["predictions"])


class PredictionRequest(BaseModel):
    """PRD2 section 10.1 request body."""

    image_id: int = Field(description="D2 id returned by POST /api/v1/images.")
    xai: bool = Field(
        default=False,
        description=(
            "Request explainability. Accepted and plumbed through the "
            "pipeline; the ActivationBundle is populated in Step 6 (M2.5) and "
            "is never included in this response - it is in-process only."
        ),
    )


@router.post(
    "/predictions",
    response_model=PredictionResponse,
    status_code=201,
    summary="Classify an uploaded image as Real or AI Generated",
    responses={
        401: {"model": ErrorResponse, "description": "AUTH_TOKEN_INVALID"},
        404: {"model": ErrorResponse, "description": "IMG_NOT_FOUND"},
        500: {"model": ErrorResponse, "description": "INF_FAILED"},
        503: {"model": ErrorResponse, "description": "INF_MODEL_UNAVAILABLE"},
        504: {"model": ErrorResponse, "description": "INF_TIMEOUT"},
    },
)
async def create_prediction(
    body: PredictionRequest,
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
) -> PredictionResponse:
    """Run both pretrained detectors over one of the caller's images and fuse the result.

    Scores come from third-party checkpoints already fine-tuned for AI-vs-real
    classification; nothing here is trained by this project and no randomly
    initialised layer is involved.

    What we do NOT claim: an accuracy figure for this system. No benchmark has
    been run on a labelled test set. Both detectors were also trained largely
    on generators that existed at their training time, so behaviour on newer
    ones is unknown - exactly the gap PRD2's MM2.2 exists to measure. See
    CLAUDE.md for the full limitations list.
    """
    # Owner only. Not-found and not-yours are deliberately indistinguishable
    # (same code, same status), as in M1's GET /images/{id}, so ids cannot be
    # probed.
    image = db.query(DBImage).filter(DBImage.image_id == body.image_id).first()
    if image is None or image.user_id != session.user_id:
        raise ImgNotFoundException(f"Image with id {body.image_id} not found.")

    prepared = prepare_model_input(body.image_id, db, session)

    try:
        result = await pipeline.run_detection(prepared, db, xai_requested=body.xai)
    except InferenceError as exc:
        emit(
            "error",
            f"Prediction failed for image_id={body.image_id}: {exc.code}",
            severity="error",
            user_id=session.user_id,
        )
        raise AppException(
            code=exc.code, message=exc.detail, status_code=exc.http_status
        ) from exc

    emit(
        "prediction-request",
        f"Prediction {result.prediction_id} for image_id={body.image_id}: "
        f"{result.predicted_class} (confidence {result.confidence_score:.3f})",
        severity="info",
        user_id=session.user_id,
    )
    return PredictionResponse.from_contract(result)
