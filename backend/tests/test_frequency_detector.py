"""The frequency branch - SPAI - without its weights.

Nothing here needs the 560 MB weights file or the network. What is asserted:

- the vendored FFT filters partition the spectrum exactly;
- image preparation never resizes unless capped, never enlarges, and trims
  to even dimensions;
- the vendored architecture's parameter set matches the released checkpoint
  key-for-key and shape-for-shape (against a stored manifest);
- the loader refuses a missing file, a digest mismatch, a partial state dict
  and a multi-output head - each one a way of ending up with a model that
  produces plausible numbers for the wrong reason;
- the sign-convention flag really inverts the probability.

The one forward pass through the real architecture runs on random weights
and is a PLUMBING test: it proves the tensors flow, not that anything is
detected. No claim about detection quality is made anywhere in this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image
from safetensors.torch import save_file
from torch import nn

from app.m2_analysis import frequency_detector
from app.m2_analysis.frequency_detector import SpectralDetector, prepare_image, weights_digest
from app.m2_analysis.vendor.spai import build_config, build_mf_vit, filters
from app.shared import config
from app.shared.contracts.errors import ModelUnavailableError
from conftest import make_image

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------
# Vendored signal processing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "device",
    [
        "cpu",
        pytest.param(
            "cuda",
            marks=pytest.mark.skipif(
                not torch.cuda.is_available(), reason="no CUDA device"
            ),
        ),
    ],
)
def test_low_and_high_pass_components_sum_back_to_the_image(device):
    """mask + (1 - mask) == 1 everywhere, so low + high must reconstruct x.

    Parametrised over devices because the mask is an int64 parameter that
    multiplies a complex spectrum; the promotion must hold on CUDA too.
    """
    image = torch.rand(2, 3, 224, 224, device=device)
    mask = filters.generate_circular_mask(224, 16).to(device)

    low, high = filters.filter_image_frequencies(image, mask)

    assert low.device.type == device
    torch.testing.assert_close(low + high, image, atol=1e-5, rtol=0)


def test_circular_mask_keeps_only_the_low_frequencies_around_the_centre():
    mask = filters.generate_circular_mask(224, 16)

    assert mask.shape == (224, 224)
    assert mask[112, 112] == 1  # DC term, after fftshift
    assert mask[0, 0] == 0  # corner: highest frequencies
    assert mask[112, 112 + 15] == 1 and mask[112, 112 + 16] == 0  # radius 16, exclusive
    # Value recorded from the released checkpoint's own frequencies_mask.
    assert int(mask.sum()) == 856


# --------------------------------------------------------------------------
# Image preparation
# --------------------------------------------------------------------------


def test_prepare_image_keeps_native_resolution_and_scales_to_unit_range():
    tensor = prepare_image(make_image(300, 200), resize_to=None)

    assert tensor.shape == (1, 3, 200, 300)
    assert tensor.dtype == torch.float32
    assert 0.0 <= tensor.min() and tensor.max() <= 1.0


def test_prepare_image_trims_odd_dimensions_to_even():
    """The circular frequency mask is defined on an even grid."""
    tensor = prepare_image(make_image(301, 199), resize_to=None)

    assert tensor.shape == (1, 3, 198, 300)


def test_prepare_image_caps_only_images_larger_than_resize_to():
    small = prepare_image(make_image(300, 200), resize_to=1024)
    assert small.shape == (1, 3, 200, 300)  # untouched - never enlarged

    large = prepare_image(make_image(2048, 1024), resize_to=512)
    assert max(large.shape[-2:]) == 512
    assert large.shape == (1, 3, 256, 512)  # aspect ratio kept


def test_prepare_image_is_exactly_the_pixels_over_255():
    image = make_image(32, 32)
    expected = np.asarray(image, dtype=np.float32) / 255.0

    tensor = prepare_image(image, resize_to=None)[0].permute(1, 2, 0).numpy()

    np.testing.assert_array_equal(tensor, expected)


# --------------------------------------------------------------------------
# Architecture vs the released checkpoint
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def random_model():
    """The real SPAI architecture with random weights. Built once per module."""
    torch.manual_seed(config.SEED)
    model = build_mf_vit(build_config(feature_extraction_batch=4))
    model.eval()
    return model


def test_vendored_architecture_matches_the_released_checkpoint_exactly(random_model):
    """Every key and shape in the published weights, and nothing else.

    A vendoring slip that added, dropped or resized a single layer would
    make the strict load fail in production; this catches it without the
    560 MB file.
    """
    manifest = json.loads((FIXTURES / "spai_state_dict_manifest.json").read_text())["tensors"]
    state = random_model.state_dict()

    assert set(state) == set(manifest)
    for key, entry in manifest.items():
        assert list(state[key].shape) == entry["shape"], key
        assert str(state[key].dtype) == entry["dtype"], key


def test_random_weights_forward_is_plumbing_only(random_model):
    """448x448 -> 4 patches -> one logit. Proves the path, not the detector."""
    tensor = prepare_image(make_image(448, 448), resize_to=None)

    with torch.inference_mode():
        logit = random_model([tensor], 4)

    assert logit.shape == (1, 1)
    assert torch.isfinite(logit).all()


# --------------------------------------------------------------------------
# The loader refuses everything it cannot verify
# --------------------------------------------------------------------------


class _TinyModel(nn.Module):
    """Stands in for the SPAI architecture so loader tests need no 560 MB file.

    Exposes the two things the loader inspects: a state dict, and
    ``cls_head.head[-1]`` with an ``out_features``.
    """

    def __init__(self, head_outputs: int = 1) -> None:
        super().__init__()
        self.stem = nn.Linear(3, 4)
        self.cls_head = nn.Module()
        self.cls_head.head = nn.Sequential(nn.Linear(4, head_outputs))

    def forward(self, images: list[torch.Tensor], feature_batch: int) -> torch.Tensor:
        pixels = images[0].mean(dim=(0, 2, 3))  # (3,)
        return self.cls_head.head(self.stem(pixels)).reshape(1, -1)


@pytest.fixture
def tiny_architecture(monkeypatch, tmp_path):
    """Route the loader to _TinyModel and to a temporary models directory."""
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)

    import app.m2_analysis.vendor.spai as spai

    def build(cfg):
        torch.manual_seed(0)
        return _TinyModel(head_outputs=build.head_outputs)

    build.head_outputs = 1
    monkeypatch.setattr(spai, "build_mf_vit", build)
    return build


def _write_weights(path: Path, tensors: dict[str, torch.Tensor]) -> str:
    save_file({k: v.contiguous() for k, v in tensors.items()}, str(path))
    return weights_digest(tensors)


def _detector(filename: str, digest: str, **overrides) -> SpectralDetector:
    kwargs = dict(ai_is_positive=True, resize_to=None, feature_batch=4)
    kwargs.update(overrides)
    return SpectralDetector(filename=filename, digest=digest, **kwargs)


def test_missing_weights_file_names_the_path_and_the_setup_steps(tiny_architecture, tmp_path):
    detector = _detector("absent.safetensors", "0" * 64)

    with pytest.raises(ModelUnavailableError) as excinfo:
        detector.load()

    assert str(tmp_path / "absent.safetensors") in str(excinfo.value)
    assert "convert_spai_checkpoint.py" in str(excinfo.value)
    assert not detector.is_loaded


def test_digest_mismatch_refuses_to_load(tiny_architecture, tmp_path):
    torch.manual_seed(0)
    _write_weights(tmp_path / "w.safetensors", _TinyModel().state_dict())
    detector = _detector("w.safetensors", "f" * 64)

    with pytest.raises(ModelUnavailableError, match="pinned digest"):
        detector.load()

    assert not detector.is_loaded


def test_partial_state_dict_is_refused_not_papered_over(tiny_architecture, tmp_path):
    """Upstream loads with strict=False. We must not: a missing key means a
    randomly initialised layer that still produces plausible numbers."""
    torch.manual_seed(0)
    tensors = _TinyModel().state_dict()
    del tensors["stem.bias"]
    digest = _write_weights(tmp_path / "w.safetensors", tensors)
    detector = _detector("w.safetensors", digest)

    with pytest.raises(ModelUnavailableError, match="stem.bias"):
        detector.load()

    assert not detector.is_loaded


def test_multi_output_head_is_refused(tiny_architecture, tmp_path):
    """The sigmoid-of-one-logit convention is the only one implemented."""
    tiny_architecture.head_outputs = 2
    torch.manual_seed(0)
    digest = _write_weights(tmp_path / "w.safetensors", _TinyModel(2).state_dict())
    detector = _detector("w.safetensors", digest)

    with pytest.raises(ModelUnavailableError, match="2 outputs"):
        detector.load()


def test_verified_weights_load_and_score_a_probability(tiny_architecture, tmp_path):
    torch.manual_seed(0)
    digest = _write_weights(tmp_path / "w.safetensors", _TinyModel().state_dict())
    detector = _detector("w.safetensors", digest)
    image_path = tmp_path / "img.png"
    make_image(256, 256).save(image_path)  # >= MIN_SIDE: this test is about scoring, not size

    result = detector.score(str(image_path))

    assert detector.is_loaded
    assert 0.0 <= result.score <= 1.0
    assert result.activations is None


def test_sign_convention_flag_inverts_the_probability(tiny_architecture, tmp_path):
    """DETECTOR_FREQUENCY_AI_IS_POSITIVE=False must yield 1 - p, exactly."""
    torch.manual_seed(0)
    digest = _write_weights(tmp_path / "w.safetensors", _TinyModel().state_dict())
    image_path = tmp_path / "img.png"
    make_image(256, 256).save(image_path)  # >= MIN_SIDE: this test is about scoring, not size

    positive = _detector("w.safetensors", digest, ai_is_positive=True).score(str(image_path))
    negative = _detector("w.safetensors", digest, ai_is_positive=False).score(str(image_path))

    assert negative.score == pytest.approx(1.0 - positive.score)


def test_weights_digest_is_order_independent_and_content_sensitive():
    a = {"x": torch.ones(2), "y": torch.zeros(3)}
    b = {"y": torch.zeros(3), "x": torch.ones(2)}
    c = {"x": torch.ones(2), "y": torch.zeros(3) + 1e-6}

    assert weights_digest(a) == weights_digest(b)
    assert weights_digest(a) != weights_digest(c)


def test_module_level_detector_is_configured_from_config_only():
    """No checkpoint name, digest or flag lives anywhere but config.py."""
    detector = frequency_detector.frequency

    assert detector.filename == config.DETECTOR_FREQUENCY_FILENAME
    assert detector.digest == config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST
    assert detector.ai_is_positive == config.DETECTOR_FREQUENCY_AI_IS_POSITIVE
    assert detector.resize_to == config.DETECTOR_FREQUENCY_RESIZE_TO


# --------------------------------------------------------------------------
# Images too small for the branch (M1 admits 64px; SPAI needs 224)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("width", "height"), [(100, 100), (223, 400), (400, 223), (64, 64)])
def test_images_below_the_patch_size_are_declared_unavailable_not_crashed(
    tiny_architecture, tmp_path, width, height
):
    """SPAI cannot see anything smaller than one 224px patch.

    Before this guard the vendored ``Tensor.unfold`` raised a bare
    RuntimeError four frames down, which the pipeline turned into
    INF_FAILED - an HTTP 500 for a perfectly legitimate upload, since M1
    accepts images down to 64px (PRD C.9).
    """
    torch.manual_seed(0)
    digest = _write_weights(tmp_path / "w.safetensors", _TinyModel().state_dict())
    detector = _detector("w.safetensors", digest)
    image_path = tmp_path / "small.png"
    make_image(width, height).save(image_path)

    with pytest.raises(frequency_detector.SpectralBranchUnavailable):
        detector.score(str(image_path))


def test_the_smallest_acceptable_image_still_scores(tiny_architecture, tmp_path):
    """224x224 is exactly one patch and must work - the boundary, not near it."""
    torch.manual_seed(0)
    digest = _write_weights(tmp_path / "w.safetensors", _TinyModel().state_dict())
    detector = _detector("w.safetensors", digest)
    image_path = tmp_path / "exact.png"
    make_image(224, 224).save(image_path)

    assert 0.0 <= detector.score(str(image_path)).score <= 1.0


def test_branch_unavailable_is_not_an_inference_error():
    """It must never fail the request - it degrades to the passthrough.

    If this ever subclasses InferenceError, pipeline.py's broad handler will
    turn a small upload back into an HTTP 500.
    """
    from app.shared.contracts.errors import InferenceError

    assert not issubclass(frequency_detector.SpectralBranchUnavailable, InferenceError)
