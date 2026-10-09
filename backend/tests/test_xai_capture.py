"""Explainability capture is faithful to the model and does not touch its score."""

from __future__ import annotations

import numpy as np
import pytest
import torch
from PIL import Image

from app.m2_analysis import detectors
from app.shared import config
from conftest import make_image

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def image_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("xai") / "x.png"
    make_image(width=640, height=480, seed=11).save(path)
    return str(path)


def test_capture_does_not_change_the_score(image_path):
    plain = detectors.primary.score(image_path)
    captured = detectors.primary.score(image_path, capture=True)
    assert plain.activations is None
    assert captured.score.hex() == plain.score.hex()  # bit-identical, not approximately


def test_recomputed_attention_equals_eager_attention(image_path):
    """The hook-based recomputation reproduces transformers' own eager
    attention weights for the same input, layer by layer."""
    from transformers import AutoModelForImageClassification

    siglip = detectors.semantic(config.SEMANTIC_SIGLIP)  # SigLIP-specific: compared with transformers' eager path
    captured = siglip.attention_maps(siglip.score(image_path, capture=True).activations)
    ours = captured["attention"]
    assert ours.shape == (12, 12, 196, 196) and captured["patch_grid"] == (14, 14)
    assert np.allclose(ours.sum(axis=-1), 1.0, atol=1e-5)  # each row is a distribution

    eager = AutoModelForImageClassification.from_pretrained(
        siglip.checkpoint, revision=siglip.revision, use_safetensors=True
    ).eval().to(config.DEVICE)
    # attn_implementation="eager" in from_pretrained does NOT reach the vision
    # sub-config of this composite checkpoint (it stays on SDPA, which returns
    # no weights); set_attn_implementation does.
    eager.set_attn_implementation("eager")
    assert eager.vision_model.config._attn_implementation == "eager"
    weights: list[torch.Tensor] = []
    hooks = [layer.self_attn.register_forward_hook(lambda _m, _a, out: weights.append(out[1][0]))
             for layer in eager.vision_model.encoder.layers]
    try:
        with Image.open(image_path) as handle:
            inputs = siglip._processor(images=handle.convert("RGB"), return_tensors="pt")
        with torch.inference_mode():
            eager(**{k: v.to(config.DEVICE) for k, v in inputs.items()})
        reference = torch.stack(weights).float().cpu().numpy()
    finally:
        for hook in hooks:
            hook.remove()
        del eager
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    assert reference.shape == ours.shape
    assert np.max(np.abs(reference - ours)) < 1e-4, np.max(np.abs(reference - ours))
