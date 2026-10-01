"""Contract C1 - PreprocessedImage (M1 -> M2).

Transcribed from PRD4 section 4.1. This is an in-process data contract, not an
HTTP payload: M1 calls M2 directly and hands this structure over.

Guarantees M2 relies on and does not re-derive:

- The tensor at ``tensor_ref`` exists, is readable, and has exactly shape
  (3, 224, 224) with dtype float32. M2 asserts this on load and raises
  INF_FAILED if violated; it does not attempt repair.
- The underlying image already passed all four of M1's validation stages.
- ``source_reference`` points at the losslessly decoded original, NOT the
  resized tensor. The frequency branch must read this one - resizing to
  224x224 is a low-pass filter that destroys the high-frequency evidence that
  branch exists to detect.
- The D2.images row is committed before this structure is handed over, so
  ``image_id`` is always a valid foreign key target.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NormalizationParams(BaseModel):
    """The normalisation M1 applied when building the tensor."""

    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    scheme: Literal["clip_openai", "imagenet"]


class PreprocessedImage(BaseModel):
    """The validated, preprocessed image handed from M1 to M2."""

    image_id: int  # FK to D2.images
    user_id: int  # owner, for authorisation and D4 linkage
    tensor_ref: str  # path to a .npy on the shared volume
    shape: tuple[int, int, int]  # (C, H, W) = (3, 224, 224)
    dtype: Literal["float32"]
    normalization: NormalizationParams
    source_reference: str  # path to the ORIGINAL decoded image
    created_at: datetime
