"""User administration API router (write half of F.17).

Conforms to PRD Section 5.1.5 / 6.3 and Module Interface Contract Section 6.3.
"""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.m1_access import login_activity
from app.m1_access.account_policy import apply_status_change
from app.m1_access.models import LoginEvent, User
from typing import List
from app.m1_access.schemas import (
    PaginatedLoginEvents,
    UserListItemResponse,
    UserStatusUpdateRequest,
    UserStatusUpdateResponse,
)
from app.m1_access.security import current_session, require_role
from app.shared.db import get_db
from app.shared.errors import (
    AdmActionNotPermittedException,
)
from app.shared.logging import emit
from app.shared.schemas import SessionContext

router = APIRouter(prefix="/users", tags=["User Administration (M1 Write)"])


@router.get(
    "/me/login-activity",
    response_model=PaginatedLoginEvents,
    summary="The signed-in user's own sign-ins and password changes, newest first",
)
def my_login_activity(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
):
    query = db.query(LoginEvent).filter(LoginEvent.user_id == session.user_id)
    return login_activity.page_of(query, page, page_size)


@router.get(
    "",
    response_model=List[UserListItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List all users (Admin only)",
)
def list_users(
    admin_session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.user_id.asc()).all()
    return users


@router.patch(
    "/{user_id}/status",
    response_model=UserStatusUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user account status (F.17 write half - Admin only)",
)
def update_user_status(
    user_id: int,
    body: UserStatusUpdateRequest,
    admin_session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
):
    # INTEGRATION (Phase 5b, changes.md 6.11): the self-change guard, the
    # last-active-admin invariant and the not-found code live in
    # account_policy, shared with M3's admin endpoint.
    try:
        target_user, old_status = apply_status_change(db, admin_session.user_id, user_id, body.action)
    except AdmActionNotPermittedException:
        emit(
            "administrative-action",
            f"Blocked status change by admin_id={admin_session.user_id} on user_id={user_id} ({body.action})",
            severity="warning",
            user_id=admin_session.user_id,
        )
        raise
    new_status = target_user.account_status
    db.commit()
    db.refresh(target_user)

    emit(
        "administrative-action",
        f"Admin user_id={admin_session.user_id} changed user_id={user_id} status from '{old_status}' to '{new_status}'",
        severity="info",
        user_id=admin_session.user_id,
    )

    return UserStatusUpdateResponse(
        user_id=target_user.user_id,
        account_status=target_user.account_status,
    )
