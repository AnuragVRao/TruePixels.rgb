"""Cross-module shared data structures and interface schemas.

Conforms to Module Interface Contract v1.0 (Contracts C1, C2, C3).

INTEGRATION NOTE: M1 and M3 each shipped a module at this path defining their
own copies of the contract classes, and M2 had its own under
``app.shared.contracts``. Three definitions of one contract is how seams drift,
so there is now exactly one: the classes live in ``app.shared.contracts`` and
this module re-exports them under the import path M1's and M3's code already
uses. See changes.md.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.shared.contracts.c1 import NormalizationParams, PreprocessedImage
from app.shared.contracts.c2 import ActivationBundle, InferenceOutput
from app.shared.contracts.c3 import SessionContext


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


__all__ = [
    "NormalizationParams",
    "PreprocessedImage",
    "ActivationBundle",
    "InferenceOutput",
    "SessionContext",
    "ErrorDetail",
    "ErrorEnvelope",
]
