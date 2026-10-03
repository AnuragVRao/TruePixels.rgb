"""
Module M3 Administrator Subsystem endpoints (F.16, F.17, F.18, F.19).
Guarded strictly by require_role("Admin").
"""
from __future__ import annotations
import math
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.shared.db import get_db
from app.shared.deps import require_role
from app.shared.schemas import SessionContext
from app.shared.errors import AppException
from app.shared.logging import emit
from app.m3_results.models import LogEntry, User, ModelRegistry
from app.m3_results.schemas import (
    AdminSummaryTile,
    PaginatedLogs,
    LogItem,
    SystemAnalytics,
    AdminUserItem,
    UserStatusActionRequest,
    UserStatusResponse,
)
from app.m3_results.analytics import get_admin_summary, get_system_analytics

router = APIRouter(prefix="/admin", tags=["Administration & Monitoring"])


@router.get("/summary", response_model=AdminSummaryTile)
def get_dashboard_summary(
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
) -> AdminSummaryTile:
    """Returns top-level metric tiles for Admin Dashboard (F.16)."""
    return get_admin_summary(db)


@router.get("/logs", response_model=PaginatedLogs)
def get_system_logs(
    event_type: str | None = Query(default=None, description="Filter by event_type"),
    severity: str | None = Query(default=None, description="Filter by severity ('info','warning','error')"),
    start_time: datetime | None = Query(default=None, description="Start time filter"),
    end_time: datetime | None = Query(default=None, description="End time filter"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=200, description="Items per page"),
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
) -> PaginatedLogs:
    """
    Paginated query for system logs with filtering (F.16).
    Emits an audit log event because reading logs is itself an audited administrative action.
    """
    query = db.query(LogEntry)

    if event_type:
        query = query.filter(LogEntry.event_type == event_type)
    if severity:
        query = query.filter(LogEntry.severity == severity)
    if start_time:
        query = query.filter(LogEntry.log_timestamp >= start_time)
    if end_time:
        query = query.filter(LogEntry.log_timestamp <= end_time)

    total = query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    offset = (page - 1) * page_size

    rows = query.order_by(LogEntry.log_timestamp.desc(), LogEntry.log_id.desc()).offset(offset).limit(page_size).all()

    # Log the log-inspection audit action
    emit(
        event_type="administrative-action",
        event_detail=f"Admin {session.user_id} viewed logs (page={page}, filters: type={event_type}, sev={severity})",
        severity="info",
        user_id=session.user_id,
    )

    items = [
        LogItem(
            log_id=row.log_id,
            user_id=row.user_id,
            event_type=row.event_type,
            event_detail=row.event_detail,
            severity=row.severity,
            request_id=row.request_id,
            log_timestamp=row.log_timestamp,
        )
        for row in rows
    ]

    return PaginatedLogs(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/analytics", response_model=SystemAnalytics)
def get_analytics(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
) -> SystemAnalytics:
    """Returns system analytics including volume over time and confidence histograms (F.18)."""
    return get_system_analytics(db, days=days)


@router.get("/users", response_model=list[AdminUserItem])
def list_users(
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
) -> list[AdminUserItem]:
    """Returns list of registered users for administrator management screen (F.17)."""
    users = db.query(User).order_by(User.registered_at.desc(), User.user_id.desc()).all()
    return [
        AdminUserItem(
            user_id=u.user_id,
            full_name=u.full_name,
            email=u.email,
            role=u.role,
            account_status=u.account_status,
            registered_at=u.registered_at,
        )
        for u in users
    ]


@router.patch("/users/{user_id}/status", response_model=UserStatusResponse)
def update_user_status(
    user_id: int,
    body: UserStatusActionRequest,
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
) -> UserStatusResponse:
    """
    Administrative account state change (F.17 write half / Contract C3.3).
    Prevents self-modification by the administrator.
    """
    if user_id == session.user_id and body.action in ("disable", "remove"):
        raise AppException(
            code="ADM_ACTION_NOT_PERMITTED",
            message="Administrators cannot disable or remove their own account.",
            status_code=409,
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise AppException(
            code="AUTH_INVALID_CREDENTIALS",
            message=f"User #{user_id} not found.",
            status_code=404,
        )

    status_map = {
        "enable": "active",
        "disable": "disabled",
        "remove": "removed",
    }
    user.account_status = status_map[body.action]
    db.commit()

    emit(
        event_type="administrative-action",
        event_detail=f"Admin {session.user_id} changed user #{user_id} status to '{user.account_status}'",
        severity="warning",
        user_id=session.user_id,
    )

    return UserStatusResponse(
        user_id=user.user_id,
        account_status=user.account_status,
    )


@router.get("/models")
def list_models(
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Admin view for Model Registry (Contract C4 / F.19)."""
    models = db.query(ModelRegistry).order_by(ModelRegistry.registered_at.desc(), ModelRegistry.model_id.desc()).all()
    return [
        {
            "model_id": m.model_id,
            "model_name": m.model_name,
            "model_version": m.model_version,
            "model_type": m.model_type,
            "is_active": m.is_active,
            "metrics": m.metrics,
            "registered_at": m.registered_at.isoformat(),
        }
        for m in models
    ]


@router.post("/models/{model_id}/activate")
def activate_model(
    model_id: int,
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Admin activation of a model version (Contract C4 / F.19)."""
    target = db.query(ModelRegistry).filter(ModelRegistry.model_id == model_id).first()
    if not target:
        raise AppException(
            code="INF_MODEL_UNAVAILABLE",
            message=f"Model #{model_id} not found.",
            status_code=404,
        )

    # Deactivate previous active model of same type atomically in one transaction
    db.query(ModelRegistry).filter(
        ModelRegistry.model_type == target.model_type,
        ModelRegistry.is_active.is_(True),
    ).update({"is_active": False})

    target.is_active = True
    db.commit()

    emit(
        event_type="administrative-action",
        event_detail=f"Admin {session.user_id} activated model #{model_id} ({target.model_name} v{target.model_version})",
        severity="info",
        user_id=session.user_id,
    )

    return {
        "status": "success",
        "activated_model_id": target.model_id,
        "model_type": target.model_type,
        "is_active": True,
    }
