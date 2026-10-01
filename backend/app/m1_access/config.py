"""Configuration settings for Module M1 (Image & Access Management)."""
import logging
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Security & JWT
#
# INTEGRATION (2026-09-30): the fallback used to be a fixed string written into
# this file. A signing key committed to the repository is not a secret - anyone
# who can read the source can mint a valid session token for any user on any
# deployment that did not override it. It is replaced by a random key generated
# per process: unset means unguessable, rather than unset means public.
#
# The cost is that sessions do not survive a restart when the variable is not
# set, which is the correct trade and is announced loudly below. Set
# JWT_SECRET_KEY in backend/.env to keep sessions across restarts - required
# for any deployment, and for running more than one worker (each would
# otherwise sign with a different key and reject the others' tokens).
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    JWT_SECRET_KEY = secrets.token_urlsafe(64)
    logging.getLogger(__name__).warning(
        "JWT_SECRET_KEY is not set; generated a random one for this process. "
        "Sessions will not survive a restart and multiple workers will reject "
        "each other's tokens. Set it in backend/.env before deploying."
    )
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
SESSION_EXPIRE_HOURS = int(os.getenv("SESSION_EXPIRE_HOURS", "8"))

# Storage Configuration
# INTEGRATION: default moved from backend/storage to the repository-root
# storage/ tree that M2 and M3 also use (BASE_DIR is backend/, so .parent is
# the repo root). Must match app.shared.config.STORAGE_ROOT. See changes.md.
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR.parent / "storage")))
UPLOADS_DIR = STORAGE_DIR / "uploads"
TENSORS_DIR = STORAGE_DIR / "tensors"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TENSORS_DIR.mkdir(parents=True, exist_ok=True)

# Validation Bounds
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
MIN_IMAGE_DIMENSION = int(os.getenv("MIN_IMAGE_DIMENSION", "64"))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "25000000"))  # Guard against decompression bombs (5000x5000)

# Email / 2FA Configuration
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "smtp")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
# INTEGRATION (2026-09-30): these defaulted to a developer's personal Gmail
# address, which then shipped in the repository. Empty by default; set them in
# backend/.env. With no SMTP_PASSWORD the email backend already falls back to
# printing the OTP to the console, so local development is unaffected.
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "True").lower() in ("true", "1", "yes")
OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "5"))
REQUIRE_2FA = os.getenv("REQUIRE_2FA", "False").lower() in ("true", "1", "yes")
