"""PRD2 section 13.1 - spectral feature extraction.

Three properties are asserted: the feature vector is fixed-length for any
input size, it is invariant to overall brightness scaling, and the Hann window
is genuinely applied.

These features feed M3's explainability, not a classifier - the frequency
branch produces no score. See the module docstring in frequency.py.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.m2_analysis.frequency import (
    centre_crop,
    extract_features,
    hann_window_2d,
    log_spectrum,
    radial_profile,
    standardize,
    to_luminance,
)
from app.m2_analysis.registry import FrequencyFeatureConfig
from conftest import make_image


def config(crop_size: int = 256, radial_bins: int = 128):
    """A smaller crop than production, to keep the test suite fast."""
    return FrequencyFeatureConfig(
        crop_size=crop_size,
        radial_bins=radial_bins,
        use_luminance=True,
        highpass=True,
        highpass_sigma=1.0,
        scalar_features=4,
    )


@pytest.mark.parametrize("size", [(64, 64), (256, 256), (1024, 768), (37, 200)])
def test_feature_vector_is_fixed_length_for_any_input_size(tmp_path, size):
    """Spectra of differently-sized images are only comparable at a fixed size."""
    width, height = size
    path = tmp_path / f"img_{width}x{height}.png"
    make_image(width, height).save(path)

    cfg = config()
    features, _ = extract_features(str(path), cfg)

    assert features.shape == (cfg.radial_bins + cfg.scalar_features,)
    assert np.isfinite(features).all()


def test_features_are_invariant_to_overall_brightness_scaling(tmp_path):
    """A detector that responds to exposure is measuring the photographer.

    The base image is forced to even pixel values so that halving it is exact
    in uint8. Without that, re-quantisation adds genuine noise and the test
    would be measuring rounding rather than the invariance property.
    """
    base = (np.asarray(make_image(256, 256), dtype=np.int32) // 2) * 2

    bright_path = tmp_path / "bright.png"
    dim_path = tmp_path / "dim.png"
    Image.fromarray(base.astype(np.uint8)).save(bright_path)
    Image.fromarray((base // 2).astype(np.uint8)).save(dim_path)

    cfg = config()
    bright_features, _ = extract_features(str(bright_path), cfg)
    dim_features, _ = extract_features(str(dim_path), cfg)

    np.testing.assert_allclose(bright_features, dim_features, rtol=1e-5, atol=1e-5)


def test_standardize_is_exactly_scale_invariant():
    """The mechanism behind the property above, asserted directly."""
    plane = np.asarray(make_image(64, 64).convert("L"), dtype=np.float64)

    np.testing.assert_allclose(standardize(plane), standardize(plane * 3.7))


def test_hann_window_suppresses_the_spectral_cross():
    """PRD2 section 8.2 - the window is not optional.

    A synthetic image whose opposite edges do not match creates a
    discontinuity that exists only because the FFT treats the image as one
    period of an infinitely repeating signal. Unwindowed, that leaks energy
    into a bright cross through the origin. The window must remove it.
    """
    size = 256
    centre = size // 2

    # Ramps in both directions, so the left/right and top/bottom seams are both
    # maximal, plus texture so there is a real off-axis background to compare
    # the cross against.
    rows, cols = np.mgrid[0:size, 0:size]
    ramp = (cols / (size - 1)) + (rows / (size - 1))
    noise = np.random.default_rng(3).normal(0.0, 1.0, (size, size))
    plane = standardize(ramp * 8.0 + noise)

    def cross_to_background(spectrum: np.ndarray) -> float:
        off_axis = np.ones_like(spectrum, dtype=bool)
        off_axis[centre, :] = False
        off_axis[:, centre] = False

        cross = np.concatenate([spectrum[centre, :], spectrum[:, centre]]).mean()
        return float(cross / spectrum[off_axis].mean())

    unwindowed = cross_to_background(log_spectrum(plane, window=False))
    windowed = cross_to_background(log_spectrum(plane, window=True))

    # Unwindowed, the seam puts markedly more energy on the axes than off them.
    assert unwindowed > 1.4
    # Windowed, the cross is all but gone.
    assert windowed < 1.1
    assert windowed < unwindowed


def test_hann_window_is_separable_and_tapers_to_zero():
    window = hann_window_2d(64)

    assert window.shape == (64, 64)
    assert window[0, :].max() == pytest.approx(0.0, abs=1e-12)
    assert window[:, 0].max() == pytest.approx(0.0, abs=1e-12)
    assert window[32, 32] == pytest.approx(window.max())


def test_centre_crop_pads_by_reflection_when_the_image_is_smaller():
    small = np.asarray(make_image(40, 40).convert("L"), dtype=np.float64)

    cropped = centre_crop(small, 256)

    assert cropped.shape == (256, 256)
    assert np.isfinite(cropped).all()


def test_centre_crop_takes_the_middle_of_a_larger_image():
    plane = np.arange(100 * 100, dtype=np.float64).reshape(100, 100)

    cropped = centre_crop(plane, 10)

    assert cropped.shape == (10, 10)
    np.testing.assert_array_equal(cropped, plane[45:55, 45:55])


def test_radial_profile_has_the_requested_number_of_bins():
    plane = standardize(np.asarray(make_image(128, 128).convert("L"), dtype=np.float64))
    spectrum = log_spectrum(plane)

    profile = radial_profile(spectrum, bins=128)

    assert profile.shape == (128,)
    assert np.isfinite(profile).all()


def test_to_luminance_collapses_to_a_single_channel():
    plane = to_luminance(make_image(32, 48))

    assert plane.shape == (48, 32)
    assert plane.min() >= 0.0
    assert plane.max() <= 255.0
