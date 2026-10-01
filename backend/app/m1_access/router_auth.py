"""Authentication API router for TruePixels.rgb.

Conforms to PRD Section 5.1 / 6.3 and SRS F.1, F.2, F.3, F.4.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.m1_access.config import OTP_EXPIRE_MINUTES, REQUIRE_2FA, ENVIRONMENT
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

    # 2. Check email uniqueness in DB (App-level + wrapped DB constraint)
    existing_user = db.query(User).filter(User.email == body.email).first()
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
        otp = generate_otp()
        new_user.otp_hash = create_otp_hash(otp)
        new_user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
        db.commit()
        EmailService.send_otp_email(new_user.email, otp, new_user.full_name)
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
    db: Session = Depends(get_db),
):
    clean_email = body.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    # Timing attack protection: perform dummy verification if user is not found (PRD §5.1.2)
    if not user:
        verify_password(body.password, DUMMY_HASH)
        emit("authentication", f"Login failed: unknown email {clean_email}", severity="warning")
        raise AuthInvalidCredentialsException("Invalid email or password.")

    # Check password
    if not verify_password(body.password, user.password_hash):
        emit("authentication", f"Login failed: bad password for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    # Check account active status
    if user.account_status in ("disabled", "removed"):
        emit("authentication", f"Login blocked: account {user.account_status} for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    # If 2FA is required, trigger OTP dispatch before issuing token
    if REQUIRE_2FA:
        otp = generate_otp()
        user.otp_hash = create_otp_hash(otp)
        user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
        db.commit()
        EmailService.send_otp_email(user.email, otp, user.full_name)
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
    db: Session = Depends(get_db),
):
    clean_email = body.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    if not user:
        verify_password(body.password, DUMMY_HASH)
        emit("authentication", f"Admin login failed: unknown email {clean_email}", severity="warning")
        raise AuthInvalidCredentialsException("Invalid email or password.")

    if not verify_password(body.password, user.password_hash):
        emit("authentication", f"Admin login failed: bad password for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        raise AuthInvalidCredentialsException("Invalid email or password.")

    if user.account_status in ("disabled", "removed"):
        emit("authentication", f"Admin login blocked: account is {user.account_status}", severity="warning", user_id=user.user_id)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    # PRD §5.1.3: User credentials on admin login endpoint returns 403 AUTH_FORBIDDEN
    if user.role != "Admin":
        emit("authentication", f"Admin login rejected: user_id={user.user_id} has role '{user.role}'", severity="warning", user_id=user.user_id)
        raise AuthForbiddenException("Access denied. Administrator privileges required.")

    if REQUIRE_2FA:
        otp = generate_otp()
        user.otp_hash = create_otp_hash(otp)
        user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
        db.commit()
        EmailService.send_otp_email(user.email, otp, user.full_name)
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
@router.post(
    "/otp/send",
    summary="Request a new OTP code to email",
)
def send_otp(
    body: OTPRequest,
    db: Session = Depends(get_db),
):
    clean_email = body.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        # Don't leak whether email exists
        return {"message": "If the account exists, a verification code has been dispatched."}

    otp = generate_otp()
    user.otp_hash = create_otp_hash(otp)
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
    db.commit()

    EmailService.send_otp_email(user.email, otp, user.full_name)
    emit("authentication", f"2FA OTP re-dispatched to {clean_email}: user_id={user.user_id}", severity="info", user_id=user.user_id)
    return {"message": "Verification code has been dispatched to your email."}


@router.post(
    "/otp/verify",
    response_model=OTPVerifyResponse,
    summary="Verify OTP code for 2FA",
)
def verify_otp(
    body: OTPVerifyRequest,
    db: Session = Depends(get_db),
):
    clean_email = body.email.strip().lower()
    clean_otp = body.otp.strip()
    user = db.query(User).filter(User.email == clean_email).first()
    if not user or not user.otp_hash or not user.otp_expires_at:
        emit("authentication", f"OTP verification failed: no active OTP for email {clean_email}", severity="warning")
        raise AuthInvalidCredentialsException("Invalid or expired verification code.")

    # SQLite returns naive datetime; ensure comparison works with UTC
    expires_at = user.otp_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > expires_at:
        user.otp_hash = None
        db.commit()
        raise AuthInvalidCredentialsException("Verification code has expired. Please request a new one.")

    if not verify_otp_hash(clean_otp, user.otp_hash):
        emit("authentication", f"OTP verification failed: code mismatch for user_id={user.user_id}", severity="warning", user_id=user.user_id)
        raise AuthInvalidCredentialsException("Invalid verification code. Please make sure you enter the latest code sent to your email.")

    # OTP is valid
    user.otp_hash = None
    user.is_email_verified = True
    db.commit()

    token, issued_at, expires_at_token = create_session_token(user)
    emit("authentication", f"2FA OTP verified successfully: user_id={user.user_id}", severity="info", user_id=user.user_id)

    return OTPVerifyResponse(
        message="Verification successful.",
        token=token,
        role=user.role,
        expires_at=expires_at_token,
        user_id=user.user_id,
    )
