"""Typed representations of Contracts C1 through C5 from PRD4."""

from app.shared.contracts.c1 import NormalizationParams, PreprocessedImage
from app.shared.contracts.c2 import ActivationBundle, InferenceOutput
from app.shared.contracts.c3 import SessionContext
from app.shared.contracts.errors import (
    InferenceError,
    ModelUnavailableError,
    PredictionNotFoundError,
    TimeoutError,
)

__all__ = [
    "NormalizationParams",
    "PreprocessedImage",
    "ActivationBundle",
    "InferenceOutput",
    "SessionContext",
    "InferenceError",
    "ModelUnavailableError",
    "PredictionNotFoundError",
    "TimeoutError",
]
