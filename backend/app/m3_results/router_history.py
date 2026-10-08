"""
Module M3 User Prediction History endpoints (F.13, US-3.2, R3.1).
Strictly scoped to requesting authenticated user at the database query level.
"""
from __future__ import annotations
import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.shared.db import get_db
from app.shared.deps import current_session
from app.shared.schemas import SessionContext
from app.m3_results.models import Prediction, Image
from app.m3_results.schemas import PaginatedHistory, HistoryItem
from app.m3_results.likelihood import describe
from app.m3_results.router_results import _likelihood_fields
from app.m3_results.urls import image_thumbnail_url

router = APIRouter(tags=["Prediction History"])


@router.get("/history", response_model=PaginatedHistory)
def get_user_prediction_history(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
) -> PaginatedHistory:
    """
    Returns paginated list of predictions strictly belonging to the authenticated user.
    Scope is bound at the SQL query level (F.13 Rule 8).
    """
    offset = (page - 1) * page_size

    # Total count for the user
    total_count = (
        db.query(func.count(Prediction.prediction_id))
        .join(Image, Image.image_id == Prediction.image_id)
        .filter(Image.user_id == session.user_id)
        .scalar()
        or 0
    )

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

    # Fetch rows ordered newest first
    rows = (
        db.query(Prediction, Image)
        .join(Image, Image.image_id == Prediction.image_id)
        .filter(Image.user_id == session.user_id)
        .order_by(Prediction.prediction_timestamp.desc(), Prediction.prediction_id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = []
    for pred, img in rows:
        items.append(
            HistoryItem(
                prediction_id=pred.prediction_id,
                image_id=pred.image_id,
                thumbnail_url=image_thumbnail_url(img.image_id),
                predicted_class=pred.predicted_class,
                **_likelihood_fields(describe(pred)),
                prediction_timestamp=pred.prediction_timestamp,
            )
        )

    return PaginatedHistory(
        items=items,
        total=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
