"""Forgot-password codes and password changes (migration 0005).

A reset code lives in ``password_resets`` (one row per user, Argon2id hash
only), NOT in users.otp_*: requesting a reset never replaces a pending
sign-in or registration code, and a reset code can never be redeemed for a
session at /auth/otp/verify. Redeeming one only sets a new password; the
user then signs in normally (with 2FA, if it is on).

Delivery follows the OTP rules (otp_challenge.ensure_delivery_possible): in
production a code is only issued when real e-mail delivery is configured.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.m1_access import throttle
from app.m1_access.config import OTP_EXPIRE_MINUTES
from app.m1_access.email_service import EmailService
from app.m1_access.models import PasswordReset, User
from app.m1_access.security import create_otp_hash, generate_otp, hash_password, verify_otp_hash
from app.shared.db import SessionLocal
from app.shared.logging import emit


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # SQLite returns naive UTC


def issue(db: Session, user: User) -> str:
    """Create (or replace) the user's reset code and return it, NOT yet sent.

    The caller sends it with ``deliver`` after the HTTP response has gone out,
    so a real account and an unknown address answer in the same time (an SMTP
    round-trip would otherwise reveal which addresses have accounts).
    """
    code = generate_otp()
    row = db.get(PasswordReset, user.user_id) or PasswordReset(user_id=user.user_id)
    row.code_hash = create_otp_hash(code)
    row.created_at = datetime.now(timezone.utc)
    row.expires_at = row.created_at + timedelta(minutes=OTP_EXPIRE_MINUTES)
    db.add(row)
    db.commit()
    throttle.new_code_issued(user.user_id, scope="reset")
    return code


def deliver(user_id: int, email: str, full_name: str | None, code: str) -> None:
    """Send a reset code (run as a background task). If it cannot be sent, the
    code is deleted, so no undeliverable code stays redeemable."""
    if EmailService.send_password_reset_email(email, code, full_name):
        return
    with SessionLocal() as db:
        db.execute(delete(PasswordReset).where(PasswordReset.user_id == user_id))
        db.commit()
    emit("error", f"Password reset code for user_id={user_id} could not be sent; the code was discarded",
         severity="error", user_id=user_id)


def redeem(db: Session, user: User | None, code: str) -> bool:
    """True when ``code`` is the user's unexpired reset code. A wrong code counts
    towards the limit; the 5th wrong one deletes the code."""
    row = db.get(PasswordReset, user.user_id) if user is not None else None
    if row is None:
        create_otp_hash(code)  # same hashing cost as a real check
        return False
    if datetime.now(timezone.utc) > _aware(row.expires_at):
        clear(db, user)
        return False
    if not verify_otp_hash(code, row.code_hash):
        if throttle.otp_wrong(user.user_id, scope="reset"):
            clear(db, user)
        return False
    return True


def set_password(db: Session, user: User, new_password: str) -> None:
    """Store the new password and end every existing session (token_version)."""
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.token_version = (user.token_version or 0) + 1
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.user_id))
    db.commit()
    db.refresh(user)


def clear(db: Session, user: User) -> None:
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.user_id))
    db.commit()


def purge_expired(db: Session) -> int:
    """Delete every expired reset code (run with the OTP purge in the app lifespan)."""
    result = db.execute(delete(PasswordReset).where(PasswordReset.expires_at < datetime.now(timezone.utc)))
    db.commit()
    return result.rowcount or 0
