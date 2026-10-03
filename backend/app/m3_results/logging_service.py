"""
Module M3 System Logging Service (F.15, Contract C5).
Implements synchronous, non-throwing emit(), secret redaction filter, and retention management.
"""
from __future__ import annotations
import re
import sys
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Literal
from sqlalchemy.orm import Session
from app.shared.db import SessionLocal
from app.m3_results.models import LogEntry

# Redaction patterns for secrets (passwords, tokens, bearer strings, auth headers, base64 data)
REDACTION_PATTERNS = [
    (re.compile(r'password["\']?\s*[:=]\s*["\']?([^"\'\s,]+)["\']?', re.IGNORECASE), r'password=[REDACTED]'),
    (re.compile(r'bearer\s+(?:token\s+)?([A-Za-z0-9\-\._~\+\/=]+)', re.IGNORECASE), r'Bearer [REDACTED]'),
    (re.compile(r'token["\']?\s*[:=]\s*["\']?([^"\'\s,]+)["\']?', re.IGNORECASE), r'token=[REDACTED]'),
    (re.compile(r'authorization["\']?\s*[:=]\s*["\']?([^"\'\s,]+)["\']?', re.IGNORECASE), r'authorization=[REDACTED]'),
    (re.compile(r'data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=]{40,}', re.IGNORECASE), r'[IMAGE_BYTES_REDACTED]'),
]


# Every write failure emit_log swallows is also recorded here (bounded), so a
# test can assert that logging actually happened instead of trusting silence.
# Production behaviour is unchanged: still non-throwing, still on stderr.
WRITE_FAILURES: deque[str] = deque(maxlen=100)


def redact_secrets(detail: str) -> str:
    """Applies strict redaction filter over log strings to strip passwords, tokens, and payloads."""
    if not detail:
        return ""
    sanitized = detail
    for pattern, replacement in REDACTION_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def emit_log(
    event_type: Literal["authentication", "prediction-request", "administrative-action", "error"],
    event_detail: str,
    severity: Literal["info", "warning", "error"],
    user_id: int | None = None,
    request_id: str | None = None,
    db: Session | None = None,
) -> None:
    """
    Synchronous, non-throwing logging implementation for Contract C5.
    Catches all internal errors and writes to stderr to protect host request from failing.
    """
    try:
        clean_detail = redact_secrets(event_detail)
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            entry = LogEntry(
                user_id=user_id,
                event_type=event_type,
                event_detail=clean_detail,
                severity=severity,
                request_id=request_id,
                log_timestamp=datetime.now(timezone.utc),
            )
            db.add(entry)
            db.commit()
        finally:
            if close_db:
                db.close()
    except Exception as e:
        # Non-throwing by design (G4): logging failure must never fail the underlying request
        WRITE_FAILURES.append(f"{event_type}: {type(e).__name__}: {e}")
        sys.stderr.write(f"[TruePixels Logging Error]: Failed to emit log: {e}\n")


def purge_expired_logs(db: Session) -> int:
    """
    Purges logs older than policy:
    - 90 days for severity 'info'
    - 365 days (1 year) for severity 'warning' and 'error'
    """
    now = datetime.now(timezone.utc)
    info_cutoff = now - timedelta(days=90)
    warn_error_cutoff = now - timedelta(days=365)

    info_deleted = db.query(LogEntry).filter(
        LogEntry.severity == "info",
        LogEntry.log_timestamp < info_cutoff,
    ).delete(synchronize_session=False)

    warn_deleted = db.query(LogEntry).filter(
        LogEntry.severity.in_(["warning", "error"]),
        LogEntry.log_timestamp < warn_error_cutoff,
    ).delete(synchronize_session=False)

    db.commit()
    return info_deleted + warn_deleted
