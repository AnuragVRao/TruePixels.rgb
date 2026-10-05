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
from app.m1_access import otp_challenge, throttle
from app.m1_access.email_service import EmailService
from app.m1_access.models import User
from app.m1_access.schemas import (
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
        raise AuthInvalidCredentialsException("Invalid email or password.")

    # Check password
    if not verify_password(body.password, user.password_hash):
        throttle.login_failed(attempt_key)
        emit("authentication", f"Login failed: bad password for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    throttle.login_succeeded(attempt_key)  # the password was right

    # Check account active status
    if user.account_status in ("disabled", "removed"):
        emit("authentication", f"Login blocked: account {user.account_status} for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    # If 2FA is required, trigger OTP dispatch before issuing token
    if REQUIRE_2FA:
        otp_challenge.issue(db, user, "login")  # after the correct password only (changes.md 6.15)
        emit("authentication", f"2FA OTP dispatched for login: user_id={user.user_id}", severity="info", user_id=user.user_id)
        return UserLoginResponse(
            token="",
            role=user.role,
            expires_at=datetime.now(timezone.utc),
            user_id=user.user_id,
            requires_otp=True,
        )

    token, issued_at, expires_at = create_session_token(user)
    emit("authentication", f"User logged in successfully: user_id={user.user_id}", severity="info", user_id=user.user_id)

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
        raise AuthInvalidCredentialsException("Invalid email or password.")

    if not verify_password(body.password, user.password_hash):
        throttle.login_failed(attempt_key)
        emit("authentication", f"Admin login failed: bad password for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    throttle.login_succeeded(attempt_key)  # the password was right

    if user.account_status in ("disabled", "removed"):
        emit("authentication", f"Admin login blocked: account is {user.account_status}", severity="warning", user_id=user.user_id)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    # PRD §5.1.3: User credentials on admin login endpoint returns 403 AUTH_FORBIDDEN
    if user.role != "Admin":
        emit("authentication", f"Admin login rejected: user_id={user.user_id} has role '{user.role}'", severity="warning", user_id=user.user_id)
        raise AuthForbiddenException("Access denied. Administrator privileges required.")

    if REQUIRE_2FA:
        otp_challenge.issue(db, user, "login")  # after the correct password only (changes.md 6.15)
        emit("authentication", f"2FA OTP dispatched for admin login: user_id={user.user_id}", severity="info", user_id=user.user_id)
        return UserLoginResponse(
            token="",
            role="Admin",
            expires_at=datetime.now(timezone.utc),
            user_id=user.user_id,
            requires_otp=True,
        )

    token, issued_at, expires_at = create_session_token(user)
    emit("authentication", f"Admin logged in successfully: user_id={user.user_id}", severity="info", user_id=user.user_id)

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

    return OTPVerifyResponse(
        message="Verification successful.",
        token=token,
        role=user.role,
        expires_at=expires_at_token,
        user_id=user.user_id,
    )
