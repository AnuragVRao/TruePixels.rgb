"""
Module M3 Report Generation endpoints (F.14, US-3.3).
Generates and streams downloadable PDF reports for authorized predictions:
one PDF per prediction, or several PDFs in one ZIP (batch upload, 2026-10-14).
"""
from __future__ import annotations
import io
import zipfile
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.shared.db import get_db
from app.shared.schemas import SessionContext
from app.shared.deps import current_session
from app.shared.errors import AppException
from app.shared.logging import emit
from app.m3_results.models import Prediction, Image, Explainability
from app.m3_results.reporting import build_pdf_report

router = APIRouter(tags=["Reports"])

# The batch upload page allows 10 images; the ZIP accepts no more.
MAX_REPORTS_PER_ZIP = 10


def _owned_prediction(db: Session, session: SessionContext, prediction_id: int) -> Prediction:
    """The prediction if the caller owns it (or is an Admin); else 404.

    Not-found and not-yours are deliberately indistinguishable.
    """
    query = db.query(Prediction).join(Image, Image.image_id == Prediction.image_id).filter(Prediction.prediction_id == prediction_id)
    if session.role != "Admin":
        query = query.filter(Image.user_id == session.user_id)
    pred = query.first()
    if pred is None and session.role == "Admin":
        # An Admin may also reach a prediction whose image row is gone.
        pred = db.query(Prediction).filter(Prediction.prediction_id == prediction_id).first()
    if pred is None:
        raise AppException(
            code="INF_PREDICTION_NOT_FOUND",
            message=f"Prediction #{prediction_id} not found.",
            status_code=404,
        )
    return pred


def _render_pdf(db: Session, session: SessionContext, pred: Prediction) -> bytes:
    """The PDF report for one prediction, with its explainability panels."""
    xai_items = (
        db.query(Explainability)
        .filter(Explainability.prediction_id == pred.prediction_id)
        .order_by(Explainability.branch)
        .all()
    )
    try:
        return build_pdf_report(prediction=pred, explainabilities=xai_items).getvalue()
    except Exception as exc:
        emit(
            event_type="error",
            event_detail=f"PDF generation failed for prediction #{pred.prediction_id}: {exc}",
            severity="error",
            user_id=session.user_id if session else None,
        )
        raise AppException(
            code="RPT_GENERATION_FAILED",
            message="Failed to assemble PDF forensic report.",
            status_code=500,
        )


def _report_filename(prediction_id: int) -> str:
    return f"TruePixels_Report_{prediction_id}.pdf"


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
    pred = _owned_prediction(db, resolved_session, prediction_id)
    pdf_bytes = _render_pdf(db, resolved_session, pred)
    user_uid = resolved_session.user_id if resolved_session else None
    emit(
        event_type="prediction-request",
        event_detail=f"User {user_uid} downloaded PDF report for prediction #{prediction_id}",
        severity="info",
        user_id=user_uid,
    )

    headers = {
        "Content-Disposition": f'attachment; filename="{_report_filename(prediction_id)}"',
        "Content-Type": "application/pdf",
        "Content-Length": str(len(pdf_bytes)),
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


class ReportZipRequest(BaseModel):
    prediction_ids: list[int] = Field(min_length=1, max_length=MAX_REPORTS_PER_ZIP)


@router.post("/reports/zip")
def download_reports_zip(
    body: ReportZipRequest,
    resolved_session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    """
    Several PDF reports in one ZIP (the batch results page).

    All or nothing: every prediction must be the caller's (or the caller an
    Admin), checked before any PDF is built; one that is not gives the same
    404 as the single-report endpoint. Duplicate ids are included once.
    """
    ids = list(dict.fromkeys(body.prediction_ids))
    preds = [_owned_prediction(db, resolved_session, pid) for pid in ids]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for pred in preds:
            archive.writestr(_report_filename(pred.prediction_id), _render_pdf(db, resolved_session, pred))
    zip_bytes = buffer.getvalue()

    user_uid = resolved_session.user_id if resolved_session else None
    emit(
        event_type="prediction-request",
        event_detail=f"User {user_uid} downloaded a ZIP of {len(ids)} PDF reports "
                     f"(predictions {', '.join(f'#{pid}' for pid in ids)})",
        severity="info",
        user_id=user_uid,
    )

    headers = {
        "Content-Disposition": 'attachment; filename="TruePixels_Reports.zip"',
        "Content-Type": "application/zip",
        "Content-Length": str(len(zip_bytes)),
    }
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)
