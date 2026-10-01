"""
Module M3 Prediction Results and Explainability endpoints (F.10, F.11, C.3).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.shared.db import get_db
from app.shared.deps import current_session
from app.shared.schemas import SessionContext
from app.shared.errors import AppException
from app.m3_results.models import Prediction, Image, Explainability
from app.m3_results.schemas import PredictionResultView, ExplainabilityItem
from app.m3_results.reporting import compute_confidence_band
from app.m3_results.urls import storage_url

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
        .all()
    )

    vis_items = [
        ExplainabilityItem(
            branch=x.branch,
            technique=x.technique,
            visualization_url=storage_url(x.visualization_reference),
            generated_at=x.generated_at,
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
        original_image_url=storage_url(img.file_reference),
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
            visualization_url=storage_url(x.visualization_reference),
            generated_at=x.generated_at,
        )
        for x in xai_rows
    ]


# INTEGRATION: POST /mock/predict was removed here. It stood in for M2 while M2
# did not exist, storing random scores in the real D4 table, where they mixed
# with genuine predictions in history, analytics and reports. Predictions now
# come from M2: POST /api/v1/images, then POST /api/v1/predictions. See
# changes.md.
