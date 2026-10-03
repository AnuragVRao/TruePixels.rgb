"""Explainability data for M3 (Phase 3). Produces no score.

Two pieces of the Contract C2 ActivationBundle are assembled here:

* the semantic branch's attention, recomputed from what the SigLIP detector
  captured during its normal scoring pass (``detectors.attention_maps``);
* the **frequency panel's spectrum**, defined to be what the frequency
  detector actually looks at - not an illustration of it.

What SPAI consumes (read from the vendored code, not assumed):
``frequency_detector.prepare_image`` makes RGB in [0, 1], native resolution,
height and width trimmed to even; ``vendor/spai/sid.patchify_image`` cuts it
into 224x224 patches at stride 224 (any remainder at the right/bottom edge is
not analysed); an image with fewer than ``MINIMUM_PATCHES`` (4) patches is
five-cropped instead; and each patch's 2-D FFT is split by a circular mask of
radius ``MASKING_RADIUS`` (16) into the low- and high-frequency components the
model compares.

So the spectrum returned here is the **mean, over every patch SPAI analyses
and over the three colour channels, of log(1 + |FFT|)** of those exact
224x224 patches, centre-shifted. The panel draws the r = 16 circle on it.
What it shows: the frequency content present in the regions SPAI saw.
What it does NOT show: which frequencies drove SPAI's score - SPAI's decision
comes from learned features compared across the low/high/original views,
which this average does not expose.

The old spectrum source (``frequency.extract_features``: a 512x512 centre
crop of luminance, high-pass filtered and Hann-windowed) was NOT what SPAI
sees, and is no longer used for the panel.
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

from app.m2_analysis.frequency_detector import MIN_SIDE, SpectralBranchUnavailable, prepare_image
from app.m2_analysis.vendor.spai import build_config
from app.m2_analysis.vendor.spai.layers import five_crop
from app.m2_analysis.vendor.spai.sid import patchify_image

_SPAI = build_config()
PATCH_SIZE: int = _SPAI.DATA.IMG_SIZE                      # 224
PATCH_STRIDE: int = _SPAI.MODEL.PATCH_VIT.PATCH_STRIDE     # 224
MINIMUM_PATCHES: int = _SPAI.MODEL.PATCH_VIT.MINIMUM_PATCHES  # 4
MASK_RADIUS: int = _SPAI.MODEL.FRE.MASKING_RADIUS          # 16

# Patches transformed per step; bounds memory on a 16 MP image (~320 patches).
_CHUNK = 64


def spai_patch_spectrum(image_path: str, *, resize_to: int | None) -> tuple[np.ndarray, dict]:
    """Mean log-magnitude spectrum of the patches SPAI analyses, and how it was made.

    Raises:
        SpectralBranchUnavailable: the image is below one patch in a dimension,
            exactly when SPAI itself has no evidence (no panel is drawn then).
    """
    with Image.open(image_path) as handle:
        tensor = prepare_image(handle, resize_to=resize_to)  # 1 x 3 x H x W, [0, 1]
    height, width = tensor.shape[-2:]
    if min(height, width) < MIN_SIDE:
        raise SpectralBranchUnavailable(
            f"{width}x{height} is smaller than SPAI's {MIN_SIDE}px patch; no spectrum to show"
        )

    patches = patchify_image(tensor, (PATCH_SIZE, PATCH_SIZE), (PATCH_STRIDE, PATCH_STRIDE))
    five_cropped = patches.size(1) < MINIMUM_PATCHES
    if five_cropped:
        patches = torch.stack(five_crop(tensor, [PATCH_SIZE, PATCH_SIZE]), dim=1)
    patches = patches[0]  # L x 3 x 224 x 224

    total = torch.zeros((PATCH_SIZE, PATCH_SIZE), dtype=torch.float64)
    for start in range(0, patches.size(0), _CHUNK):
        chunk = patches[start:start + _CHUNK].double()
        magnitude = torch.fft.fftshift(torch.fft.fft2(chunk), dim=(-2, -1)).abs()
        total += torch.log1p(magnitude).sum(dim=(0, 1))
    spectrum = (total / (patches.size(0) * patches.size(1))).numpy().astype(np.float32)

    meta = {
        "source": "mean log(1+|FFT|) of the 224x224 RGB patches SPAI analyses",
        "patch_size": PATCH_SIZE,
        "patch_stride": PATCH_STRIDE,
        "patches": int(patches.size(0)),
        "five_crop": bool(five_cropped),
        "analysed_size": [int(width), int(height)],
        "mask_radius": MASK_RADIUS,
        "resize_to": resize_to,
    }
    return spectrum, meta
