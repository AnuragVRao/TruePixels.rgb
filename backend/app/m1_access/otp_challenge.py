"""OTP challenges: who may receive a code, and what it may be redeemed for.

Phase 6-pre (changes.md 6.15). Before this, ``/auth/otp/send`` issued a code
to ANY address and ``/auth/otp/verify`` exchanged it for a full session, for
any role, even with 2FA off: a password-free sign-in, not a second factor.

Now a code exists only as part of a CHALLENGE with a purpose:

* ``login``    - created only after a correct password (``/auth/login`` or
  ``/auth/admin/login``), for any role;
* ``register`` - created only by ``/auth/register`` (which creates role User
  only), and redeemable only while the account's role is User.

``/auth/otp/verify`` must name the purpose it redeems; a mismatch, another
account's code, or no pending challenge are all the same "invalid or expired"
answer and count as a wrong attempt. ``/auth/otp/send`` only RE-SENDS a code
for a challenge that is already pending (same purpose); it can never start
one. With 2FA disabled both endpoints are refused outright.

Codes are stored only as Argon2id hashes (``create_otp_hash``) and checked
with Argon2's own constant-time verify.

Delivery: in production, codes are issued only when real e-mail delivery is
configured (``EMAIL_BACKEND=smtp`` with host, user, password and sender).
The console fallback - which prints the code - is development only.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.m1_access import throttle
from app.m1_access.config import OTP_EXPIRE_MINUTES, is_production
from app.m1_access.email_service import EmailService
from app.m1_access.models import User
from app.m1_access.security import create_otp_hash, generate_otp
from app.shared.errors import AppException

PURPOSES = ("login", "register")


def delivery_configured() -> bool:
    """Real e-mail delivery is set up (read at call time, so tests can vary it)."""
    return (os.getenv("EMAIL_BACKEND", "smtp").lower() == "smtp"
            and all(os.getenv(key, "").strip() for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")))


def ensure_delivery_possible() -> None:
    """Refuse BEFORE any state changes when a code could not be delivered."""
    if is_production() and not delivery_configured():
        raise AppException(code="OTP_DELIVERY_UNAVAILABLE", status_code=503,
                           message="Verification codes cannot be sent: e-mail delivery is not configured.")


def issue(db: Session, user: User, purpose: str) -> None:
    """Create (or replace) the user's challenge for ``purpose`` and send the code."""
    if purpose not in PURPOSES:
        raise ValueError(purpose)
    if purpose == "register" and user.role != "User":
        raise ValueError("a registration challenge is for role User only")
    ensure_delivery_possible()
    code = generate_otp()
    user.otp_hash = create_otp_hash(code)
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
    user.otp_purpose = purpose
    db.commit()
    throttle.new_code_issued(user.user_id)
    if not EmailService.send_otp_email(user.email, code, user.full_name):
        clear(db, user)
        raise AppException(code="OTP_DELIVERY_UNAVAILABLE", status_code=503,
                           message="The verification code could not be sent. Please try again later.")


def pending_purpose(user: User | None) -> str | None:
    """The purpose of an unexpired challenge, or None."""
    if user is None or not user.otp_hash or not user.otp_expires_at or user.otp_purpose not in PURPOSES:
        return None
    expires = user.otp_expires_at
    if expires.tzinfo is None:  # SQLite returns naive UTC
        expires = expires.replace(tzinfo=timezone.utc)
    return user.otp_purpose if datetime.now(timezone.utc) <= expires else None


PURGE_INTERVAL_S = 60


def purge_expired(db: Session) -> int:
    """Clear every EXPIRED challenge (hash, expiry, purpose) in one UPDATE.

    Consumed challenges and those killed by wrong attempts are cleared on the
    spot (``clear``); this removes the ones nobody came back for, so no stale
    code hash outlives its expiry by more than PURGE_INTERVAL_S. Run at
    startup and periodically from the app lifespan. Returns rows cleared.
    """
    from sqlalchemy import update

    result = db.execute(update(User)
                        .where(User.otp_expires_at.isnot(None),
                               User.otp_expires_at < datetime.now(timezone.utc))
                        .values(otp_hash=None, otp_expires_at=None, otp_purpose=None))
    db.commit()
    return result.rowcount or 0


def clear(db: Session, user: User) -> None:
    user.otp_hash = None
    user.otp_expires_at = None
    user.otp_purpose = None
    db.commit()
