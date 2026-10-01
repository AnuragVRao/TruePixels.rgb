"""
Unit Tests for Module M3 System Logging and Secret Redaction (F.15, G4, MM3.8).
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from app.m3_results.logging_service import redact_secrets, emit_log, purge_expired_logs
from app.m3_results.models import LogEntry


def test_redaction_filter_scrubs_passwords_and_tokens():
    """Validates that regex redaction filter eliminates passwords, tokens, and bearer keys."""
    raw_strings = [
        ('User attempted login with password="SecretPassword123!"', 'User attempted login with password=[REDACTED]'),
        ("Authorization header: Bearer eyJhbGciOiJIUzI1NiIsIn...", "Authorization header: Bearer [REDACTED]"),
        ('Generated token="abcdef1234567890"', 'Generated token=[REDACTED]'),
        ('Embedded image data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAA...', '[IMAGE_BYTES_REDACTED]'),
    ]

    for raw, expected_pattern in raw_strings:
        scrubbed = redact_secrets(raw)
        assert "SecretPassword123!" not in scrubbed
        assert "eyJhbGciOiJIUzI1NiIsIn" not in scrubbed
        assert "abcdef1234567890" not in scrubbed
        assert "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAA" not in scrubbed


def test_emit_log_is_non_throwing_under_failure():
    """Validates that emit_log never raises exceptions even with unusual input types (G4)."""
    try:
        # None event_detail or bad types should not raise an unhandled error
        emit_log(event_type="error", event_detail=None, severity="error")
        emit_log(event_type="authentication", event_detail="Regular login event", severity="info")
    except Exception as e:
        assert False, f"emit_log raised an exception: {e}"


def test_log_retention_purge(db_session):
    """Validates log retention policy: 90 days for info, 365 days for warning/error."""
    now = datetime.now(timezone.utc)

    # 1. Info log older than 90 days (should be deleted)
    old_info = LogEntry(
        event_type="authentication",
        event_detail="Old info log",
        severity="info",
        log_timestamp=now - timedelta(days=95),
    )
    # 2. Info log recent (should remain)
    recent_info = LogEntry(
        event_type="authentication",
        event_detail="Recent info log",
        severity="info",
        log_timestamp=now - timedelta(days=30),
    )
    # 3. Warning log older than 365 days (should be deleted)
    old_warn = LogEntry(
        event_type="administrative-action",
        event_detail="Old warning log",
        severity="warning",
        log_timestamp=now - timedelta(days=400),
    )
    # 4. Warning log 200 days old (should remain)
    recent_warn = LogEntry(
        event_type="administrative-action",
        event_detail="Recent warning log",
        severity="warning",
        log_timestamp=now - timedelta(days=200),
    )

    db_session.add_all([old_info, recent_info, old_warn, recent_warn])
    db_session.commit()

    deleted_count = purge_expired_logs(db_session)
    assert deleted_count == 2

    remaining = db_session.query(LogEntry).all()
    assert len(remaining) == 2
    remaining_details = [r.event_detail for r in remaining]
    assert "Recent info log" in remaining_details
    assert "Recent warning log" in remaining_details
