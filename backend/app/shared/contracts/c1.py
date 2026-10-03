"""Contract C1 - PreprocessedImage (M1 -> M2).

Transcribed from PRD4 section 4.1. This is an in-process data contract, not an
HTTP payload: M1 calls M2 directly and hands this structure over.

Guarantees M2 relies on and does not re-derive:

- The underlying image already passed all four of M1's validation stages.
- ``source_reference`` points at the losslessly decoded original, NOT the
  resized tensor. The frequency branch must read this one - resizing to
  224x224 is a low-pass filter that destroys the high-frequency evidence that
  branch exists to detect.
- The D2.images row is committed before this structure is handed over, so
  ``image_id`` is always a valid foreign key target.

The pre-resized CLIP tensor is no longer produced (2026-10-03, changes.md
6.3). PRD4 had M1 build a (3, 224, 224) CLIP-normalised tensor and save it as
``.npy``; no detector ever read it - both branches preprocess the original
themselves, SigLIP 2 with its own processor (mean/std 0.5, not CLIP's) and SPAI
at native resolution - so it was built and written twice per image for
nothing. ``tensor_ref``, ``shape``, ``dtype`` and ``normalization`` stay in the
model as optional fields, always ``None``, so existing callers and M3's stub
still validate; C1 v2 should drop them.
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
    source_reference: str  # path to the ORIGINAL decoded image - what M2 reads
    created_at: datetime
    # Deprecated (see module docstring): no longer produced, never read.
    tensor_ref: str | None = None
    shape: tuple[int, int, int] | None = None
    dtype: Literal["float32"] | None = None
    normalization: NormalizationParams | None = None
