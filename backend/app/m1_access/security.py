"""Security operations: Argon2id hashing, anti-timing oracle dummy verification, session tokens, and role dependencies.

Conforms to PRD Section 5.1 and Module Interface Contract Section 6.
"""
from datetime import datetime, timezone, timedelta
import secrets
import time
from typing import Callable, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.m1_access.config import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    SESSION_EXPIRE_HOURS,
    OTP_EXPIRE_MINUTES,
)
from app.m1_access.models import User
from app.shared.db import get_db
from app.shared.errors import (
    AuthAccountDisabledException,
    AuthForbiddenException,
    AuthInvalidCredentialsException,
    AuthTokenInvalidException,
)
from app.shared.logging import emit
from app.shared.schemas import SessionContext

# Try argon2 first, fallback to passlib bcrypt
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

    def hash_password(password: str) -> str:
        return _ph.hash(password)

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            return _ph.verify(hashed_password, plain_password)
        except Exception:
            return False

except ImportError:
    from passlib.context import CryptContext
    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(password: str) -> str:
        return _pwd_context.hash(password)

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            return _pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False

# Fixed dummy hash for constant-time authentication against account enumeration (PRD §5.1.2)
DUMMY_HASH = hash_password("TruePixels_Dummy_Secret_Password_Timing_Protection_999")

# Top common passwords blacklist
COMMON_PASSWORDS = {
    "1234567890", "password123", "admin12345", "welcome123", "iloveyou123",
    "qwerty12345", "monkey12345", "dragon12345", "master12345", "sunshine123",
    "princess123", "football123", "shadow12345", "superman123", "trustno1123"
}

http_bearer = HTTPBearer(auto_error=False)


def validate_password_strength(password: str) -> None:
    """Enforces PRD password policy (min 10 chars, letter + digit, not common)."""
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters long.")
    if password.lower() in COMMON_PASSWORDS:
        raise ValueError("Password is too common. Please choose a stronger password.")
    if not any(c.isalpha() for c in password):
        raise ValueError("Password must contain at least one letter.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit.")


TupleToken = tuple[str, datetime, datetime]


def create_session_token(user: User, custom_expire_hours: Optional[int] = None) -> TupleToken:
    """Generates an opaque JWT session token with UTC timestamps."""
    issued_at = datetime.now(timezone.utc)
    expire_hours = custom_expire_hours or SESSION_EXPIRE_HOURS
    expires_at = issued_at + timedelta(hours=expire_hours)

    payload = {
        "sub": str(user.user_id),
        "email": user.email,
        "role": user.role,
        "account_status": user.account_status,
        # Migration 0005: a password change or reset increments token_version,
        # which ends every session issued before it.
        "ver": user.token_version or 0,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, issued_at, expires_at


def generate_otp() -> str:
    """Generates a cryptographically secure 6-digit numeric OTP."""
    return f"{secrets.randbelow(900000) + 100000}"


def create_otp_hash(otp: str) -> str:
    return hash_password(otp)


def verify_otp_hash(plain_otp: str, hashed_otp: str) -> bool:
    return verify_password(plain_otp, hashed_otp)


def verify_session_token(token: str, db: Session) -> SessionContext:
    """Decodes, verifies expiry, and ensures user account remains active."""
    # Strip any accidental 'Bearer ' prefix pasted by user in Swagger
    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    try:
        payload = jwt.decode(clean_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
        email = payload.get("email")
        role = payload.get("role")
        account_status = payload.get("account_status")
        iat = datetime.fromtimestamp(payload.get("iat"), timezone.utc)
        exp = datetime.fromtimestamp(payload.get("exp"), timezone.utc)
        version = int(payload.get("ver", 0))  # tokens from before migration 0005 carry none
    except (JWTError, ValueError, TypeError):
        raise AuthTokenInvalidException("Missing, malformed or expired session token.")

    # Check live account status in DB
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise AuthTokenInvalidException("User associated with token no longer exists.")
    if version != (user.token_version or 0):
        raise AuthTokenInvalidException("This session ended when the account's password was changed.")
    if user.account_status in ("disabled", "removed"):
        emit("authentication", f"Access blocked: user_id={user.user_id} is {user.account_status}", severity="warning", user_id=user.user_id)
        raise AuthAccountDisabledException(f"Account is {user.account_status}.")

    return SessionContext(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        account_status=user.account_status,
        session_token=token,
        issued_at=iat,
        expires_at=exp,
    )


async def current_session(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> SessionContext:
    """Contract C3 exported dependency for any authenticated user."""
    if not credentials or not credentials.credentials:
        raise AuthTokenInvalidException("Authorization Bearer token is required.")
    return verify_session_token(credentials.credentials, db)


def require_role(required_role: str) -> Callable:
    """Contract C3 exported dependency for role-gated endpoints (e.g. Admin)."""
    async def role_checker(session: SessionContext = Depends(current_session)) -> SessionContext:
        if session.role != required_role:
            emit(
                "authentication",
                f"Forbidden access: user_id={session.user_id} with role '{session.role}' requested '{required_role}' resource",
                severity="warning",
                user_id=session.user_id,
            )
            raise AuthForbiddenException(f"Resource requires '{required_role}' privileges.")
        return session
    return role_checker
