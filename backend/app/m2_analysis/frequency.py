"""FR-02 - Frequency artifact features (DFD 0.4.2). EXPLAINABILITY ONLY.

Asks the physical question: does this pixel grid carry the spectral
fingerprint of a synthesis pipeline? It ignores content entirely.

    THIS MODULE PRODUCES NO SCORE.

It used to end in a randomly initialised MLP, which meant it emitted a
confident-looking number that meant nothing. That head has been deleted. No
pretrained classifier exists for this bespoke 132-feature vector, and training
one is permanently out of scope, so there is no honest way to turn these
features into a probability.

What survives is the signal processing itself, which is real, final, and needs
no weights at all. Its output populates ``ActivationBundle.spectrum`` for M3's
explainability - a use Contract C2 already defines. If you are looking for the
thing that decides Real vs AI Generated, it is ``detectors.py``.

Reads ``PreprocessedImage.source_reference`` - the native-resolution original -
and NEVER the 224x224 tensor. Contract C1 section 4.3 makes that binding: a
bicubic downsample is a low-pass filter, and it has already erased exactly the
high-frequency evidence this analysis exists to find.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage, signal

from app.m2_analysis.registry import FrequencyFeatureConfig

# ITU-R BT.601 luminance weights.
_LUMA_WEIGHTS = np.array([0.299, 0.587, 0.114], dtype=np.float64)

_EPSILON = 1e-8


# --------------------------------------------------------------------------
# Feature extraction - real, final, and independently testable
# --------------------------------------------------------------------------


def to_luminance(image: Image.Image) -> np.ndarray:
    """Convert to a single-channel float luminance plane at native resolution."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64)
    return rgb @ _LUMA_WEIGHTS


def centre_crop(plane: np.ndarray, size: int) -> np.ndarray:
    """Centre-crop to a fixed square, padding by reflection when too small.

    A fixed size is not a convenience: spectra of differently-sized images are
    not comparable, so every image must reach the transform at the same
    dimensions.
    """
    height, width = plane.shape

    if height < size or width < size:
        pad_y = max(0, size - height)
        pad_x = max(0, size - width)
        padding = (
            (pad_y // 2, pad_y - pad_y // 2),
            (pad_x // 2, pad_x - pad_x // 2),
        )
        # 'reflect' is undefined for a length-1 axis; fall back to edge there.
        mode = "reflect" if min(height, width) > 1 else "edge"
        plane = np.pad(plane, padding, mode=mode)
        height, width = plane.shape

    top = (height - size) // 2
    left = (width - size) // 2
    return plane[top : top + size, left : left + size]


def standardize(plane: np.ndarray) -> np.ndarray:
    """Zero-mean, unit-variance.

    This is what makes the feature vector invariant to overall brightness
    scaling: for any c > 0, (c*x - mean(c*x)) / std(c*x) == (x - mean(x)) / std(x)
    exactly. A detector that responds to exposure rather than to synthesis
    artefacts would be measuring the photographer, not the generator.
    """
    return (plane - plane.mean()) / (plane.std() + _EPSILON)


def highpass_residual(plane: np.ndarray, sigma: float) -> np.ndarray:
    """Subtract a light Gaussian blur to suppress scene content."""
    return plane - ndimage.gaussian_filter(plane, sigma=sigma)


def hann_window_2d(size: int) -> np.ndarray:
    """The separable 2-D Hann window. Not optional - see PRD2 section 8.2.

    An image is a finite signal, and the FFT treats it as one period of an
    infinitely repeating one. The left edge therefore sits next to the right
    edge, producing a discontinuity that does not exist in the scene. That
    discontinuity leaks energy across the whole spectrum as a bright cross
    through the origin, in every image, real or generated - so without
    windowing a substantial fraction of what the classifier sees is an
    artifact of the transform rather than of the image. One multiplication per
    pixel removes the problem.
    """
    window_1d = np.hanning(size)
    return np.outer(window_1d, window_1d)


def log_spectrum(plane: np.ndarray, *, window: bool = True) -> np.ndarray:
    """2-D FFT -> fftshift -> log(1 + |F|), optionally Hann-windowed first.

    ``window=False`` exists so tests can demonstrate the spectral cross the
    window suppresses. Inference always windows.
    """
    if window:
        plane = plane * hann_window_2d(plane.shape[0])
    spectrum = np.fft.fftshift(np.fft.fft2(plane))
    return np.log1p(np.abs(spectrum))


def radial_profile(spectrum: np.ndarray, bins: int) -> np.ndarray:
    """Azimuthally average a 2-D spectrum into a 1-D radial power profile.

    Orientation is discarded deliberately - upsampling and GAN checkerboard
    artefacts show up as rings, i.e. as structure in radius, not in angle.
    """
    height, width = spectrum.shape
    centre_y, centre_x = (height - 1) / 2.0, (width - 1) / 2.0

    y_coords, x_coords = np.ogrid[:height, :width]
    radius = np.hypot(y_coords - centre_y, x_coords - centre_x)

    max_radius = min(centre_y, centre_x)
    bin_index = np.clip((radius / max_radius * bins).astype(int), 0, bins - 1)
    inside = radius <= max_radius

    totals = np.bincount(bin_index[inside], weights=spectrum[inside], minlength=bins)
    counts = np.bincount(bin_index[inside], minlength=bins)
    return totals[:bins] / np.maximum(counts[:bins], 1)


def _block_boundary_energy(plane: np.ndarray, block: int = 8) -> float:
    """Blockiness at 8-pixel boundaries - the JPEG/DCT grid signature.

    Ratio of mean absolute difference ACROSS block boundaries to mean absolute
    difference everywhere. A value near 1.0 means no block grid; above 1.0
    means the 8x8 DCT lattice is visible in the pixels.
    """
    horizontal = np.abs(np.diff(plane, axis=1))
    vertical = np.abs(np.diff(plane, axis=0))

    # Column j of np.diff spans pixels j and j+1, so boundaries sit at j = k*8 - 1.
    boundary_cols = np.arange(block - 1, horizontal.shape[1], block)
    boundary_rows = np.arange(block - 1, vertical.shape[0], block)
    if boundary_cols.size == 0 or boundary_rows.size == 0:
        return 0.0

    on_boundary = np.concatenate(
        [horizontal[:, boundary_cols].ravel(), vertical[boundary_rows, :].ravel()]
    ).mean()
    overall = np.concatenate([horizontal.ravel(), vertical.ravel()]).mean()
    return float(on_boundary / (overall + _EPSILON))


def scalar_features(profile: np.ndarray, plane: np.ndarray) -> np.ndarray:
    """The four scalars that accompany the radial profile.

    High-frequency energy ratio, peak count, mean peak prominence, and DCT
    block-boundary energy.
    """
    total = profile.sum() + _EPSILON
    high_frequency_ratio = float(profile[len(profile) // 2 :].sum() / total)

    # Peaks in the radial profile are the signature of periodic upsampling.
    # Detrend first so the overall 1/f falloff does not mask them.
    detrended = profile - ndimage.uniform_filter1d(profile, size=9)
    peaks, properties = signal.find_peaks(detrended, prominence=0.0)
    peak_count = float(len(peaks))
    peak_prominence = (
        float(np.mean(properties["prominences"])) if len(peaks) else 0.0
    )

    return np.array(
        [
            high_frequency_ratio,
            peak_count,
            peak_prominence,
            _block_boundary_energy(plane),
        ],
        dtype=np.float32,
    )


def extract_features(
    source_reference: str,
    model: FrequencyFeatureConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the full spectral chain on a native-resolution image file.

    Returns:
        (feature_vector, log_spectrum). The feature vector is always
        ``radial_bins + scalar_features`` long, whatever the input dimensions.
        The spectrum is returned for M3's explainability in Step 6.
    """
    with Image.open(source_reference) as handle:
        plane = to_luminance(handle)

    plane = centre_crop(plane, model.crop_size)
    plane = standardize(plane)

    if model.highpass:
        plane = highpass_residual(plane, model.highpass_sigma)

    spectrum = log_spectrum(plane, window=True)
    profile = radial_profile(spectrum, model.radial_bins)
    scalars = scalar_features(profile, plane)

    features = np.concatenate([profile.astype(np.float32), scalars])
    return features, spectrum


# There is deliberately no classifier below this line. If you are tempted to
# add one, note that doing so would require training it - see CLAUDE.md, where
# training is recorded as permanently out of scope.
