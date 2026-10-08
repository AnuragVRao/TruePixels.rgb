"""Login activity (migration 0005): who tried to sign in, when, from where.

``record`` writes one ``login_events`` row per sign-in attempt and per
password change or reset. Like C5's emit_log it uses its own session and
never raises, so a failure here can never break a sign-in, and a row written
just before an authentication error is still kept.

The client address is ``request.client.host`` - the same value the sign-in
throttle uses, which honours forwarded headers only from the trusted proxy.
Rows older than ``RETENTION_DAYS`` are purged by the app lifespan.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.m1_access.models import LOGIN_OUTCOMES, LOGIN_PORTALS, LoginEvent, User
from app.shared.db import SessionLocal

RETENTION_DAYS = 90


def record(request: Request | None, *, portal: str, outcome: str, email: str, user: User | None = None) -> None:
    try:
        if portal not in LOGIN_PORTALS or outcome not in LOGIN_OUTCOMES:
            raise ValueError(f"portal={portal!r} outcome={outcome!r}")
        ip = request.client.host if request is not None and request.client else None
        agent = request.headers.get("user-agent") if request is not None else None
        with SessionLocal() as db:
            db.add(LoginEvent(
                user_id=user.user_id if user is not None else None,
                email=email.strip().lower()[:254],
                portal=portal,
                outcome=outcome,
                ip_address=(ip or None) and ip[:45],
                user_agent=(agent or None) and agent[:255],
                created_at=datetime.now(timezone.utc),
            ))
            db.commit()
    except Exception as e:  # noqa: BLE001 - recording must never fail the request
        sys.stderr.write(f"[LOGIN-ACTIVITY-FAIL] Failed to record login event: {e}\n")


def purge_older_than(db: Session, days: int = RETENTION_DAYS) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = db.execute(delete(LoginEvent).where(LoginEvent.created_at < cutoff))
    db.commit()
    return result.rowcount or 0


def page_of(query, page: int, page_size: int):
    """One page of a LoginEvent query, newest first, as PaginatedLoginEvents."""
    import math

    from app.m1_access.schemas import LoginEventItem, PaginatedLoginEvents

    total = query.count()
    rows = (query.order_by(LoginEvent.created_at.desc(), LoginEvent.event_id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return PaginatedLoginEvents(items=[LoginEventItem.model_validate(r) for r in rows], total=total, page=page,
                                page_size=page_size, total_pages=max(1, math.ceil(total / page_size)))
