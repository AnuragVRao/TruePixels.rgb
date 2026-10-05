"""Standardized error envelope and exception classes for TruePixels.rgb.

Conforms strictly to Module Interface Contract v1.0 Section 3.4 and SRS F.20 / NF.7.

INTEGRATION NOTE: M1 and M3 each shipped their own version of this file. This
is the union of the two - see changes.md:

- ``ERROR_REGISTRY`` and the ``AppException`` signature are M3's. It is a
  superset of M1's: ``message`` and ``status_code`` default from the registry
  when omitted, and every existing M1 call site passes them explicitly, so M1
  behaviour is unchanged.
- The named exception subclasses and both handlers are M1's.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

# Standard Error Registry from Interface Contract Section 3.4 (from M3)
ERROR_REGISTRY: dict[str, tuple[int, str]] = {
    # M1 Errors
    "AUTH_EMAIL_TAKEN": (409, "Registration with an email already present."),
    "AUTH_INVALID_CREDENTIALS": (401, "Email or password did not match."),
    "AUTH_TOKEN_INVALID": (401, "Missing, malformed or expired session token."),
    "AUTH_FORBIDDEN": (403, "Authenticated but role is insufficient for the resource."),
    "AUTH_ACCOUNT_DISABLED": (403, "Account state is disabled or removed."),
    "AUTH_RATE_LIMITED": (429, "Too many attempts; wait before trying again."),
    "IMG_FORMAT_UNSUPPORTED": (415, "Only JPG, JPEG and PNG images are accepted."),
    "IMG_TOO_LARGE": (413, "File exceeds the configured maximum upload size."),
    "IMG_CORRUPTED": (422, "Decoder could not open the file, or the file is truncated."),
    "IMG_NOT_FOUND": (404, "Image not found or not owned by the caller."),
    # Owner only: the record exists and is theirs, but the stored file is gone
    # (e.g. data migrated without its storage tree). Never shown to others.
    "FILE_TOO_LARGE": (413, "A stored file exceeds the size the server will serve."),
    "IMG_FILE_MISSING": (410, "The image record exists but its stored file is no longer available."),
    # M2 Errors
    "INF_MODEL_UNAVAILABLE": (503, "No active model of a required type, or artefact failed to load."),
    "INF_TIMEOUT": (504, "Inference exceeded the configured wall-clock budget."),
    "INF_FAILED": (500, "Unhandled failure inside a classifier or the fusion module."),
    "INF_PREDICTION_NOT_FOUND": (404, "Prediction not found or not visible to the caller."),
    # M2 model management (Phase 4, F.19)
    "MDL_NOT_FOUND": (404, "No such model row."),
    "MDL_INVALID": (422, "The model row does not describe the resident backbone, or is invalid."),
    "MDL_INVALID_ARTIFACT": (422, "The uploaded artefact failed validation."),
    "MDL_TOO_LARGE": (413, "The uploaded artefact exceeds the size limit for its type."),
    "MDL_EXISTS": (409, "A model with this name and version is already registered."),
    "MDL_CANARY_FAILED": (422, "The candidate failed its canary forward pass."),
    "MDL_GATE_REFUSED": (409, "The quality gate refused the candidate."),
    "MDL_FORCE_NEEDS_REASON": (422, "A forced activation must give a reason."),
    "MDL_CONFLICT": (409, "A concurrent activation committed first; nothing changed."),
    "MDL_NOTHING_TO_ROLL_BACK": (409, "There is no previous model of this type."),
    "MDL_ROLLBACK_NOT_PREVIOUS": (409, "Rollback can only return to a previously active model."),
    # M3 Errors
    "XAI_UNAVAILABLE": (501, "Explainability not supported for the active model."),
    "XAI_FILE_MISSING": (410, "The visualisation record exists but its stored file is no longer available."),
    "RPT_GENERATION_FAILED": (500, "PDF assembly failed."),
    "ADM_ACTION_NOT_PERMITTED": (409, "Administrative action rejected by policy."),
}


class AppException(Exception):
    """Base application exception with standardized code and status code."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        status_code: int | None = None,
        request_id: str | None = None,
        internal_detail: str | None = None,
    ):
        self.code = code
        default_status, default_msg = ERROR_REGISTRY.get(code, (500, "An unexpected error occurred."))
        self.status_code = status_code or default_status
        self.message = message or default_msg
        self.request_id = request_id or str(uuid.uuid4())
        self.internal_detail = internal_detail
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": self.request_id,
            }
        }


# --- M1 Auth & Access Exceptions ---
class AuthEmailTakenException(AppException):
    def __init__(self, message: str = "An account with this email already exists.", request_id: Optional[str] = None):
        super().__init__(code="AUTH_EMAIL_TAKEN", message=message, status_code=409, request_id=request_id)


class AuthInvalidCredentialsException(AppException):
    def __init__(self, message: str = "Invalid email or password.", request_id: Optional[str] = None):
        super().__init__(code="AUTH_INVALID_CREDENTIALS", message=message, status_code=401, request_id=request_id)


class AuthTokenInvalidException(AppException):
    def __init__(self, message: str = "Missing, invalid or expired session token.", request_id: Optional[str] = None):
        super().__init__(code="AUTH_TOKEN_INVALID", message=message, status_code=401, request_id=request_id)


class AuthForbiddenException(AppException):
    def __init__(self, message: str = "You do not have permission to access this resource.", request_id: Optional[str] = None):
        super().__init__(code="AUTH_FORBIDDEN", message=message, status_code=403, request_id=request_id)


class AuthAccountDisabledException(AppException):
    def __init__(self, message: str = "Account is disabled or removed.", request_id: Optional[str] = None):
        super().__init__(code="AUTH_ACCOUNT_DISABLED", message=message, status_code=403, request_id=request_id)


# --- M1 Image & Upload Exceptions ---
class ImgFormatUnsupportedException(AppException):
    def __init__(self, message: str = "Only JPG, JPEG and PNG images are accepted.", request_id: Optional[str] = None):
        super().__init__(code="IMG_FORMAT_UNSUPPORTED", message=message, status_code=415, request_id=request_id)


class ImgTooLargeException(AppException):
    def __init__(self, message: str = "File exceeds the configured maximum upload size.", request_id: Optional[str] = None):
        super().__init__(code="IMG_TOO_LARGE", message=message, status_code=413, request_id=request_id)


class ImgCorruptedException(AppException):
    def __init__(self, message: str = "Decoder could not open the file, or image is corrupted/truncated.", request_id: Optional[str] = None):
        super().__init__(code="IMG_CORRUPTED", message=message, status_code=422, request_id=request_id)


class ImgNotFoundException(AppException):
    def __init__(self, message: str = "Image does not exist or is not accessible.", request_id: Optional[str] = None):
        super().__init__(code="IMG_NOT_FOUND", message=message, status_code=404, request_id=request_id)


# --- M3 Admin Exceptions ---
class AdmActionNotPermittedException(AppException):
    def __init__(self, message: str = "Administrative action rejected by policy.", request_id: Optional[str] = None):
        super().__init__(code="ADM_ACTION_NOT_PERMITTED", message=message, status_code=409, request_id=request_id)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Exception handler for custom AppException."""
    # Phase 6-pre: an exception may carry response headers (Retry-After on 429).
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict(),
                        headers=getattr(exc, "headers", None))


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback 500 handler to ensure no tracebacks or internal paths leak to users (F.20/NF.7)."""
    req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred. Please contact administrator.",
                "request_id": str(req_id),
            }
        },
    )
