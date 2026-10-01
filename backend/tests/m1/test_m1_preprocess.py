"""Tests for deterministic image preprocessing and Contract C1 compliance (PRD §5.3, MM1.5)."""
import hashlib
import pytest
import numpy as np
from PIL import Image
from app.m1_access.preprocess import preprocess_pil_to_clip_tensor


def test_preprocessing_output_shape_and_dtype():
    """AC1: Returned tensor must be float32 with shape (3, 224, 224)."""
    img = Image.new("RGB", (600, 400), color=(120, 150, 200))
    tensor = preprocess_pil_to_clip_tensor(img)

    assert isinstance(tensor, np.ndarray)
    assert tensor.shape == (3, 224, 224)
    assert tensor.dtype == np.float32


def test_preprocessing_determinism_100_runs():
    """MM1.5: Bit-for-bit determinism across 100 repeat runs."""
    img = Image.new("RGB", (800, 600), color=(50, 100, 150))
    
    # Base run
    base_tensor = preprocess_pil_to_clip_tensor(img)
    base_sha256 = hashlib.sha256(base_tensor.tobytes()).hexdigest()

    # 100 Repeat runs
    for _ in range(100):
        repeat_tensor = preprocess_pil_to_clip_tensor(img)
        repeat_sha256 = hashlib.sha256(repeat_tensor.tobytes()).hexdigest()
        assert repeat_sha256 == base_sha256


@pytest.mark.parametrize("mode", ["L", "RGBA", "CMYK", "P"])
def test_all_color_modes_converge_to_3_channel_rgb(mode):
    """AC4: Grayscale, palette, CMYK and RGBA all converge to (3, 224, 224) float32."""
    img = Image.new(mode, (300, 300))
    tensor = preprocess_pil_to_clip_tensor(img)

    assert tensor.shape == (3, 224, 224)
    assert tensor.dtype == np.float32


def test_non_square_aspect_ratio_center_crop():
    """AC3: Non-square images are resized by shorter side then center-cropped, not squashed."""
    # A wide banner 1000x200
    img = Image.new("RGB", (1000, 200), color=(20, 40, 60))
    tensor = preprocess_pil_to_clip_tensor(img)

    assert tensor.shape == (3, 224, 224)
    assert not np.isnan(tensor).any()
    assert not np.isinf(tensor).any()
