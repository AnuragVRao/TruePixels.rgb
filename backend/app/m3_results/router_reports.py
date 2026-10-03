"""
Module M3 Report Generation endpoints (F.14, US-3.3).
Generates and streams downloadable PDF reports for authorized predictions.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.shared.db import get_db
from app.shared.schemas import SessionContext
from app.shared.deps import current_session
from app.shared.errors import AppException
from app.shared.logging import emit
from app.m3_results.models import Prediction, Image, Explainability
from app.m3_results.reporting import build_pdf_report

router = APIRouter(tags=["Reports"])


@router.get("/reports/{prediction_id}")
def download_prediction_report(
    prediction_id: int,
    resolved_session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """
    Generates and streams a downloadable PDF forensic report.

    INTEGRATION (Phase 5a, changes.md 6.9): Authorization header only. The
    ?token= query parameter is gone - a session token in a URL ends up in
    browser history, proxy and server logs. Browsers download with fetch +
    the header + a blob URL (React app and legacy dashboard).
    """
    # 1. Enforce ownership check (or admin access)
    query = db.query(Prediction).join(Image, Image.image_id == Prediction.image_id).filter(Prediction.prediction_id == prediction_id)
    if resolved_session.role != "Admin":
        query = query.filter(Image.user_id == resolved_session.user_id)
    
    pred = query.first()

    if not pred:
        # Check if prediction exists at all
        exists = db.query(Prediction).filter(Prediction.prediction_id == prediction_id).first()
        if exists and resolved_session.role != "Admin":
            raise AppException(
                code="INF_PREDICTION_NOT_FOUND",
                message=f"Prediction #{prediction_id} not found.",
                status_code=404,
            )
        elif not exists:
            raise AppException(
                code="INF_PREDICTION_NOT_FOUND",
                message=f"Prediction #{prediction_id} not found.",
                status_code=404,
            )
        pred = exists

    # 2. Fetch explainability visualisations
    xai_items = (
        db.query(Explainability)
        .filter(Explainability.prediction_id == prediction_id)
        .order_by(Explainability.branch)
        .all()
    )

    # 3. Assemble PDF report
    try:
        pdf_buffer = build_pdf_report(prediction=pred, explainabilities=xai_items)
        pdf_bytes = pdf_buffer.getvalue()
        user_uid = resolved_session.user_id if resolved_session else None
        emit(
            event_type="prediction-request",
            event_detail=f"User {user_uid} downloaded PDF report for prediction #{prediction_id}",
            severity="info",
            user_id=user_uid,
        )
    except Exception as exc:
        user_uid = resolved_session.user_id if resolved_session else None
        emit(
            event_type="error",
            event_detail=f"PDF generation failed for prediction #{prediction_id}: {exc}",
            severity="error",
            user_id=user_uid,
        )
        raise AppException(
            code="RPT_GENERATION_FAILED",
            message="Failed to assemble PDF forensic report.",
            status_code=500,
        )

    filename = f"TruePixels_Report_{prediction_id}.pdf"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/pdf",
        "Content-Length": str(len(pdf_bytes)),
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
