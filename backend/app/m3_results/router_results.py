"""
Module M3 Prediction Results and Explainability endpoints (F.10, F.11, C.3).
"""
from __future__ import annotations
import os
from typing import Literal
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.shared import config
from app.shared.db import get_db
from app.shared.files import stored_file_response
from app.shared.logging import emit
from app.shared.deps import current_session
from app.shared.schemas import SessionContext
from app.shared.errors import AppException
from app.m3_results.models import Prediction, Image, Explainability
from app.m3_results.schemas import PredictionResultView, ExplainabilityItem
from app.m3_results.explain import caption_for
from app.m3_results.reporting import compute_confidence_band
from app.m3_results.urls import explainability_file_url, image_file_url

router = APIRouter(tags=["Results & Explainability"])


@router.get("/results/{prediction_id}", response_model=PredictionResultView)
def get_prediction_result(
    prediction_id: int,
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
) -> PredictionResultView:
    """
    Fetches comprehensive prediction result.
    Enforces strict ownership: returns 404 INF_PREDICTION_NOT_FOUND if not owned by caller.
    """
    # Join with Image to verify user ownership at the SQL query level
    row = (
        db.query(Prediction, Image)
        .join(Image, Image.image_id == Prediction.image_id)
        .filter(
            Prediction.prediction_id == prediction_id,
            Image.user_id == session.user_id,
        )
        .first()
    )

    if not row:
        raise AppException(
            code="INF_PREDICTION_NOT_FOUND",
            message=f"Prediction #{prediction_id} not found.",
            status_code=404,
        )

    pred, img = row

    # Fetch associated explainability visualisations
    xai_rows = (
        db.query(Explainability)
        .filter(Explainability.prediction_id == prediction_id)
        .order_by(Explainability.branch)
        .all()
    )

    vis_items = [
        ExplainabilityItem(
            branch=x.branch,
            technique=x.technique,
            visualization_url=explainability_file_url(x.prediction_id, x.branch),
            generated_at=x.generated_at,
            caption=caption_for(x.technique),
        )
        for x in xai_rows
    ]

    conf_score = pred.confidence_score
    conf_band = compute_confidence_band(conf_score)
    model_name = pred.model.model_name if pred.model else "Hybrid ViT/FFT Detector"
    model_version = pred.model.model_version if pred.model else "1.0"

    return PredictionResultView(
        prediction_id=pred.prediction_id,
        image_id=pred.image_id,
        predicted_class=pred.predicted_class,
        confidence_score=conf_score,
        confidence_percentage=round(conf_score * 100.0, 1),
        confidence_band=conf_band,
        semantic_score=pred.semantic_score,
        frequency_score=pred.frequency_score,
        fusion_score=pred.fusion_score,
        original_image_url=image_file_url(img.image_id),
        original_available=os.path.isfile(img.file_reference or ""),
        visualizations=vis_items,
        model_name=model_name,
        model_version=model_version,
        prediction_timestamp=pred.prediction_timestamp,
    )


@router.get("/explainability/{prediction_id}", response_model=list[ExplainabilityItem])
def get_explainability(
    prediction_id: int,
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
) -> list[ExplainabilityItem]:
    """
    Fetches explainability references for a prediction.
    Returns 404 INF_PREDICTION_NOT_FOUND if unauthorized/not found.
    Returns 501 XAI_UNAVAILABLE if explainability could not be generated.
    """
    # Enforce ownership
    row = (
        db.query(Prediction, Image)
        .join(Image, Image.image_id == Prediction.image_id)
        .filter(
            Prediction.prediction_id == prediction_id,
            Image.user_id == session.user_id,
        )
        .first()
    )

    if not row:
        raise AppException(
            code="INF_PREDICTION_NOT_FOUND",
            message=f"Prediction #{prediction_id} not found.",
            status_code=404,
        )

    xai_rows = (
        db.query(Explainability)
        .filter(Explainability.prediction_id == prediction_id)
        .order_by(Explainability.branch)
        .all()
    )

    if not xai_rows:
        raise AppException(
            code="XAI_UNAVAILABLE",
            message="Explainability visualisation is not available for this prediction.",
            status_code=501,
        )

    return [
        ExplainabilityItem(
            branch=x.branch,
            technique=x.technique,
            visualization_url=explainability_file_url(x.prediction_id, x.branch),
            generated_at=x.generated_at,
            caption=caption_for(x.technique),
        )
        for x in xai_rows
    ]


# INTEGRATION: POST /mock/predict was removed here. It stood in for M2 while M2
# did not exist, storing random scores in the real D4 table, where they mixed
# with genuine predictions in history, analytics and reports. Predictions now
# come from M2: POST /api/v1/images, then POST /api/v1/predictions. See
# changes.md.


def _not_found(prediction_id: int) -> AppException:
    return AppException(
        code="INF_PREDICTION_NOT_FOUND",
        message=f"Prediction #{prediction_id} not found.",
        status_code=404,
    )


@router.get(
    "/explainability/{prediction_id}/{branch}",
    response_class=FileResponse,
    summary="Download one explainability panel (owner only)",
)
def get_explainability_file(
    prediction_id: int,
    branch: Literal["semantic", "frequency"],
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
) -> FileResponse:
    """INTEGRATION: replaces the unauthenticated /static mount (changes.md).

    Same ownership join and same INF_PREDICTION_NOT_FOUND as the endpoints
    above, so "not yours", "no such prediction" and "no such panel" all look
    alike to the caller.
    """
    row = (
        db.query(Explainability)
        .join(Prediction, Prediction.prediction_id == Explainability.prediction_id)
        .join(Image, Image.image_id == Prediction.image_id)
        .filter(
            Explainability.prediction_id == prediction_id,
            Explainability.branch == branch,
            Image.user_id == session.user_id,
        )
        .first()
    )
    try:
        if row is None:
            raise _not_found(prediction_id)
        response = stored_file_response(
            row.visualization_reference, config.EXPLAINABILITY_DIR, _not_found(prediction_id),
            AppException(
                code="XAI_FILE_MISSING",
                message=f"The {branch} visualisation for prediction #{prediction_id} is recorded, "
                        "but its stored file is no longer available.",
                status_code=410,
            ),
        )
    except AppException as exc:
        if exc.code == "XAI_FILE_MISSING":
            emit("error", f"Explainability file missing on disk: prediction_id={prediction_id} "
                 f"branch={branch}", severity="warning", user_id=session.user_id)
            raise
        # F.4: refused access is logged; the caller sees one 404 whatever the reason.
        emit("error", f"Explainability file refused: prediction_id={prediction_id} branch={branch}",
             severity="warning", user_id=session.user_id)
        raise
    emit("prediction-request",
         f"Explainability file served: prediction_id={prediction_id} branch={branch}",
         severity="info", user_id=session.user_id)
    return response
