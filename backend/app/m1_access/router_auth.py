"""Authentication API router for TruePixels.rgb.

Conforms to PRD Section 5.1 / 6.3 and SRS F.1, F.2, F.3, F.4.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.m1_access.config import OTP_EXPIRE_MINUTES, REQUIRE_2FA, ENVIRONMENT
from app.m1_access import login_activity, otp_challenge, password_reset, throttle
from app.m1_access.email_service import EmailService
from app.m1_access.models import User
from app.m1_access.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    MessageResponse,
    ResetPasswordRequest,
    OTPRequest,
    OTPVerifyRequest,
    OTPVerifyResponse,
    UserLoginRequest,
    UserLoginResponse,
    UserRegisterRequest,
    UserRegisterResponse,
)
from app.m1_access.security import (
    DUMMY_HASH,
    create_otp_hash,
    create_session_token,
    current_session,
    generate_otp,
    hash_password,
    validate_password_strength,
    verify_otp_hash,
    verify_password,
)
from app.shared.db import get_db
from app.shared.errors import (
    AppException,
    AuthAccountDisabledException,
    AuthEmailTakenException,
    AuthForbiddenException,
    AuthInvalidCredentialsException,
    AuthTokenInvalidException,
)
from app.shared.logging import emit
from app.shared.schemas import SessionContext

router = APIRouter(prefix="/auth", tags=["Authentication & Access"])


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account (F.1)",
)
def register_user(
    body: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    # 1. Enforce password complexity
    try:
        validate_password_strength(body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    if REQUIRE_2FA:
        otp_challenge.ensure_delivery_possible()

    # 2. Check email uniqueness in DB (App-level + wrapped DB constraint)
    existing_user = db.query(User).filter(func.lower(User.email) == body.email.lower()).first()
    if existing_user:
        emit("authentication", f"Registration rejected: email {body.email} already exists", severity="warning")
        raise AuthEmailTakenException("An account with this email address already exists.")

    # 3. Hash password with Argon2id and insert
    pwd_hash = hash_password(body.password)
    new_user = User(
        full_name=body.full_name,
        email=body.email,
        password_hash=pwd_hash,
        role="User",
        account_status="active",
        is_email_verified=not REQUIRE_2FA,
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        emit("authentication", f"Unique constraint violation for {body.email}", severity="warning")
        raise AuthEmailTakenException("An account with this email address already exists.")

    emit("authentication", f"User registered successfully: user_id={new_user.user_id}", severity="info", user_id=new_user.user_id)

    # If 2FA enabled, generate and dispatch OTP
    if REQUIRE_2FA:
        otp_challenge.issue(db, new_user, "register")  # changes.md 6.15
        return UserRegisterResponse(
            user_id=new_user.user_id,
            message="Account registered. Please verify your email with the OTP sent to your inbox.",
            requires_2fa=True,
        )

    return UserRegisterResponse(
        user_id=new_user.user_id,
        message="Account created successfully.",
        requires_2fa=False,
    )


@router.post(
    "/login",
    response_model=UserLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate a registered user (F.2)",
)
def login_user(
    body: UserLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    clean_email = body.email.strip().lower()
    # INTEGRATION (changes.md 6.13): increasing delay per (email, client IP),
    # shared by both sign-in endpoints; checked before any password work.
    attempt_key = throttle.login_key(clean_email, request.client.host if request.client else None)
    throttle.check_login(attempt_key)
    user = db.query(User).filter(func.lower(User.email) == clean_email).first()

    # Timing attack protection: perform dummy verification if user is not found (PRD §5.1.2)
    if not user:
        verify_password(body.password, DUMMY_HASH)
        throttle.login_failed(attempt_key)
        emit("authentication", f"Login failed: unknown email {clean_email}", severity="warning")
        login_activity.record(request, portal="user", outcome="unknown_account", email=clean_email)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    # Check password
    if not verify_password(body.password, user.password_hash):
        throttle.login_failed(attempt_key)
        emit("authentication", f"Login failed: bad password for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        login_activity.record(request, portal="user", outcome="wrong_password", email=clean_email, user=user)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    throttle.login_succeeded(attempt_key)  # the password was right

    # Check account active status
    if user.account_status in ("disabled", "removed"):
        emit("authentication", f"Login blocked: account {user.account_status} for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        login_activity.record(request, portal="user", outcome="account_disabled", email=clean_email, user=user)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    # If 2FA is required, trigger OTP dispatch before issuing token
    if REQUIRE_2FA:
        otp_challenge.issue(db, user, "login")  # after the correct password only (changes.md 6.15)
        emit("authentication", f"2FA OTP dispatched for login: user_id={user.user_id}", severity="info", user_id=user.user_id)
        login_activity.record(request, portal="user", outcome="otp_sent", email=clean_email, user=user)
        return UserLoginResponse(
            token="",
            role=user.role,
            expires_at=datetime.now(timezone.utc),
            user_id=user.user_id,
            requires_otp=True,
        )

    token, issued_at, expires_at = create_session_token(user)
    emit("authentication", f"User logged in successfully: user_id={user.user_id}", severity="info", user_id=user.user_id)
    login_activity.record(request, portal="user", outcome="success", email=clean_email, user=user)

    return UserLoginResponse(
        token=token,
        role=user.role,
        expires_at=expires_at,
        user_id=user.user_id,
        requires_otp=False,
    )


@router.post(
    "/admin/login",
    response_model=UserLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate an administrator (F.3)",
)
def login_admin(
    body: UserLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    clean_email = body.email.strip().lower()
    # INTEGRATION (changes.md 6.13): increasing delay per (email, client IP),
    # shared by both sign-in endpoints; checked before any password work.
    attempt_key = throttle.login_key(clean_email, request.client.host if request.client else None)
    throttle.check_login(attempt_key)
    user = db.query(User).filter(func.lower(User.email) == clean_email).first()

    if not user:
        verify_password(body.password, DUMMY_HASH)
        throttle.login_failed(attempt_key)
        emit("authentication", f"Admin login failed: unknown email {clean_email}", severity="warning")
        login_activity.record(request, portal="admin", outcome="unknown_account", email=clean_email)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    if not verify_password(body.password, user.password_hash):
        throttle.login_failed(attempt_key)
        emit("authentication", f"Admin login failed: bad password for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        login_activity.record(request, portal="admin", outcome="wrong_password", email=clean_email, user=user)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    throttle.login_succeeded(attempt_key)  # the password was right

    if user.account_status in ("disabled", "removed"):
        emit("authentication", f"Admin login blocked: account is {user.account_status}", severity="warning", user_id=user.user_id)
        login_activity.record(request, portal="admin", outcome="account_disabled", email=clean_email, user=user)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    # PRD §5.1.3: User credentials on admin login endpoint returns 403 AUTH_FORBIDDEN
    if user.role != "Admin":
        emit("authentication", f"Admin login rejected: user_id={user.user_id} has role '{user.role}'", severity="warning", user_id=user.user_id)
        login_activity.record(request, portal="admin", outcome="not_admin", email=clean_email, user=user)
        raise AuthForbiddenException("Access denied. Administrator privileges required.")

    if REQUIRE_2FA:
        otp_challenge.issue(db, user, "login")  # after the correct password only (changes.md 6.15)
        emit("authentication", f"2FA OTP dispatched for admin login: user_id={user.user_id}", severity="info", user_id=user.user_id)
        login_activity.record(request, portal="admin", outcome="otp_sent", email=clean_email, user=user)
        return UserLoginResponse(
            token="",
            role="Admin",
            expires_at=datetime.now(timezone.utc),
            user_id=user.user_id,
            requires_otp=True,
        )

    token, issued_at, expires_at = create_session_token(user)
    emit("authentication", f"Admin logged in successfully: user_id={user.user_id}", severity="info", user_id=user.user_id)
    login_activity.record(request, portal="admin", outcome="success", email=clean_email, user=user)

    return UserLoginResponse(
        token=token,
        role="Admin",
        expires_at=expires_at,
        user_id=user.user_id,
        requires_otp=False,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout current session",
)
def logout_user(
    session: SessionContext = Depends(current_session),
):
    emit("authentication", f"User logged out: user_id={session.user_id}", severity="info", user_id=session.user_id)
    return None


@router.get(
    "/me",
    response_model=SessionContext,
    status_code=status.HTTP_200_OK,
    summary="Get authenticated session info (Contract C3)",
)
def get_me(
    session: SessionContext = Depends(current_session),
):
    return session


# --- 2FA / OTP Verification Endpoints ---
# INTEGRATION (changes.md 6.15): codes only exist inside a challenge that a
# correct password ('login') or registration ('register') created. These two
# endpoints can re-send and redeem such a challenge; they can never start one.


def _portal_of(user: User) -> str:
    return "admin" if user.role == "Admin" else "user"


def _otp_in_use() -> None:
    if not REQUIRE_2FA:
        raise AuthForbiddenException("Verification codes are not in use on this server.")


@router.post(
    "/otp/send",
    summary="Re-send the code of a pending sign-in or registration challenge",
)
def send_otp(
    body: OTPRequest,
    db: Session = Depends(get_db),
):
    _otp_in_use()
    clean_email = body.email.strip().lower()
    # ONE answer for every case - account or not, challenge or not, sent or
    # throttled (60 s cooldown, 5 per hour, per address; changes.md 6.13).
    answer = {"message": "If a sign-in or registration is waiting for a code, a new code has been sent."}
    if not throttle.may_send(clean_email):
        return answer
    user = db.query(User).filter(func.lower(User.email) == clean_email).first()
    purpose = otp_challenge.pending_purpose(user)
    if purpose is None:
        create_otp_hash(generate_otp())  # same hashing cost as a real send
        return answer
    otp_challenge.issue(db, user, purpose)  # same purpose; never a new kind of challenge
    emit("authentication", f"2FA OTP re-sent ({purpose}) to {clean_email}: user_id={user.user_id}",
         severity="info", user_id=user.user_id)
    return answer


@router.post(
    "/otp/verify",
    response_model=OTPVerifyResponse,
    summary="Redeem the code of a pending sign-in or registration challenge",
)
def verify_otp(
    body: OTPVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _otp_in_use()
    clean_email = body.email.strip().lower()
    clean_otp = body.otp.strip()
    invalid = "Invalid or expired verification code."
    user = db.query(User).filter(func.lower(User.email) == clean_email).first()
    pending = otp_challenge.pending_purpose(user)
    if pending is None:
        if user is not None and user.otp_hash:
            otp_challenge.clear(db, user)  # expired (or purpose-less legacy) challenge
        emit("authentication", f"OTP verification failed: no pending challenge for {clean_email}", severity="warning")
        raise AuthInvalidCredentialsException(invalid)

    # The code must match AND be redeemed for the purpose it was issued for;
    # a registration challenge only ever yields a User session.
    right_purpose = pending == body.purpose and (pending != "register" or user.role == "User")
    if not verify_otp_hash(clean_otp, user.otp_hash) or not right_purpose:
        emit("authentication", f"OTP verification failed for user_id={user.user_id} "
             f"({'purpose mismatch' if not right_purpose else 'code mismatch'})", severity="warning",
             user_id=user.user_id)
        # Login activity: the code step of a sign-in. The challenge does not
        # carry which portal the password step used, so the role stands in.
        login_activity.record(request, portal=_portal_of(user), outcome="otp_failed", email=clean_email, user=user)
        if throttle.otp_wrong(user.user_id):  # the 5th wrong attempt kills the code (6.13)
            otp_challenge.clear(db, user)
        raise AuthInvalidCredentialsException(invalid)

    if user.account_status != "active":
        otp_challenge.clear(db, user)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    # Valid: the challenge is consumed. Redeeming ANY code proves control of
    # the mailbox, so a sign-in code also completes an unfinished
    # registration verification (changes.md 6.17).
    user.is_email_verified = True
    otp_challenge.clear(db, user)

    token, issued_at, expires_at_token = create_session_token(user)
    emit("authentication", f"2FA OTP verified successfully: user_id={user.user_id}", severity="info", user_id=user.user_id)
    login_activity.record(request, portal=_portal_of(user), outcome="success", email=clean_email, user=user)

    return OTPVerifyResponse(
        message="Verification successful.",
        token=token,
        role=user.role,
        expires_at=expires_at_token,
        user_id=user.user_id,
    )


# --- Forgot password, reset and change (migration 0005) ---
# A reset code lives in password_resets, apart from the sign-in / registration
# challenge: it can only set a new password, never open a session. Both a
# reset and a change end every existing session (users.token_version).

_RESET_SENT = "If an account exists for that address, a reset code has been sent to it."
_RESET_INVALID = "Invalid or expired reset code."


def _strong(password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError as e:
        raise AppException(code="AUTH_WEAK_PASSWORD", status_code=422, message=str(e))


@router.post(
    "/password/forgot",
    response_model=MessageResponse,
    summary="E-mail a password reset code (same answer whether or not the account exists)",
)
def forgot_password(
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    # Refused for EVERY address when no code could be delivered, so the
    # answer reveals nothing about which accounts exist.
    otp_challenge.ensure_delivery_possible()
    clean_email = body.email.strip().lower()
    answer = MessageResponse(message=_RESET_SENT)
    if not throttle.may_send(clean_email):  # 60 s cooldown, 5 per hour per address
        return answer
    user = db.query(User).filter(func.lower(User.email) == clean_email).first()
    if user is None or user.account_status != "active":
        create_otp_hash(generate_otp())  # same hashing cost as a real send
        emit("authentication", f"Password reset requested for {clean_email}: no active account", severity="warning")
        return answer
    password_reset.issue(db, user)
    emit("authentication", f"Password reset code sent: user_id={user.user_id}", severity="info", user_id=user.user_id)
    return answer


@router.post(
    "/password/reset",
    response_model=MessageResponse,
    summary="Set a new password with an e-mailed reset code; every session ends",
)
def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _strong(body.new_password)
    clean_email = body.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == clean_email).first()
    if not password_reset.redeem(db, user, body.otp.strip()):
        emit("authentication", f"Password reset failed for {clean_email}: invalid or expired code",
             severity="warning", user_id=user.user_id if user else None)
        raise AuthInvalidCredentialsException(_RESET_INVALID)
    if user.account_status != "active":
        password_reset.clear(db, user)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    user.is_email_verified = True  # redeeming the code proved control of the mailbox
    password_reset.set_password(db, user, body.new_password)
    emit("authentication", f"Password reset with an e-mailed code: user_id={user.user_id}", severity="info",
         user_id=user.user_id)
    login_activity.record(request, portal=_portal_of(user), outcome="password_reset", email=clean_email, user=user)
    return MessageResponse(message="Your password has been changed. Sign in with the new password.")


@router.post(
    "/password/change",
    response_model=UserLoginResponse,
    summary="Change the signed-in account's password; other sessions end, this one gets a new token",
)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == session.user_id).first()
    # The current-password check is throttled exactly like sign-in, so a
    # stolen session cannot be used to guess the password.
    attempt_key = throttle.login_key(user.email, request.client.host if request.client else None)
    throttle.check_login(attempt_key)
    if not verify_password(body.current_password, user.password_hash):
        throttle.login_failed(attempt_key)
        emit("authentication", f"Password change refused: wrong current password for user_id={user.user_id}",
             severity="warning", user_id=user.user_id)
        # 400, not 401: the session itself is fine, and a 401 would sign the
        # client out over a typo.
        raise AppException(code="AUTH_CURRENT_PASSWORD_INCORRECT", status_code=400,
                           message="The current password is not correct.")
    throttle.login_succeeded(attempt_key)
    if body.new_password == body.current_password:
        raise AppException(code="AUTH_WEAK_PASSWORD", status_code=422,
                           message="The new password must be different from the current one.")
    _strong(body.new_password)

    password_reset.set_password(db, user, body.new_password)
    token, issued_at, expires_at = create_session_token(user)
    emit("authentication", f"Password changed: user_id={user.user_id}", severity="info", user_id=user.user_id)
    login_activity.record(request, portal=_portal_of(user), outcome="password_changed", email=user.email, user=user)
    return UserLoginResponse(token=token, role=user.role, expires_at=expires_at, user_id=user.user_id,
                             requires_otp=False)
