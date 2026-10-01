"""Contract C5: Logging interface dispatcher across all modules.

Synchronous, non-throwing, best-effort (Module Interface Contract v1.0
Section 8, SRS F.15 / NF.7).

INTEGRATION NOTE: M1 and M3 each shipped their own ``emit()``. This one does
what both did - see changes.md:

- M3's behaviour (M3 owns C5 and D6): persist the event to the D6 ``logs``
  table through ``app.m3_results.logging_service.emit_log``, with M3's
  redaction filter.
- M1's behaviour: echo a redacted line to stdout on the ``truepixels.audit``
  logger. Kept because M1's console e-mail backend relies on it - with
  EMAIL_BACKEND=console the OTP is only ever visible in this output.

``severity`` keeps M1's default of "info"; M3's version required it, and every
M3 call site passes it, so nothing changes for M3.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Literal, Optional

EventType = Literal["authentication", "prediction-request", "administrative-action", "error"]
Severity = Literal["info", "warning", "error"]

logger = logging.getLogger("truepixels.audit")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [AUDIT-%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Regex patterns for sensitive information that must NEVER appear in logs (from M1)
REDACTION_PATTERNS = [
    (re.compile(r'(?i)(password|pass|secret|token|bearer|auth|authorization)\s*[:=]\s*["\']?([^"\'\s,]+)["\']?'), r'\1=[REDACTED]'),
    (re.compile(r'(?i)bearer\s+[a-zA-Z0-9\-_.]+', re.IGNORECASE), 'Bearer [REDACTED]'),
    (re.compile(r'ey[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'), '[JWT_REDACTED]'),
]


def redact_secrets(text: str) -> str:
    """Sanitizes text to prevent accidental credential leakage in log records."""
    if not text:
        return ""
    redacted = str(text)
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def emit(
    event_type: EventType,
    event_detail: str,
    severity: Severity = "info",
    user_id: Optional[int] = None,
    request_id: Optional[str] = None,
) -> None:
    """Contract C5 logging entrypoint.

    Synchronous, non-throwing, and best-effort.
    """
    # 1. Console echo (M1)
    try:
        sanitized_detail = redact_secrets(event_detail)
        log_payload = f"type={event_type} | severity={severity} | user_id={user_id} | req_id={request_id} | {sanitized_detail}"

        if severity == "error":
            logger.error(log_payload)
        elif severity == "warning":
            logger.warning(log_payload)
        else:
            logger.info(log_payload)
    except Exception as e:
        # Non-throwing guarantee (PRD 5.3.1 / Goal G4)
        sys.stderr.write(f"[LOGGING-EMIT-FAIL] Failed to emit audit log: {e}\n")

    # 2. Persist to D6 (M3). emit_log is itself non-throwing.
    try:
        from app.m3_results.logging_service import emit_log
        emit_log(
            event_type=event_type,
            event_detail=event_detail,
            severity=severity,
            user_id=user_id,
            request_id=request_id,
        )
    except Exception as e:
        sys.stderr.write(f"[LOGGING-EMIT-FAIL] Failed to persist audit log: {e}\n")
