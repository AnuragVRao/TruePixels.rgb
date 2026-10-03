"""Explainability maths and rendering, without any model (fast)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.m3_results.explain import build_relevance_map, compute_attention_rollout
from app.m3_results.overlay import (
    PANEL_MAX_SIDE,
    SPECTRUM_MAX_SIDE,
    generate_frequency_spectrum_panel,
    generate_semantic_overlay,
)
from app.shared.errors import AppException
from app.shared.schemas import ActivationBundle


def _focused_attention(tokens: int, target: int, layers: int = 3, heads: int = 2) -> np.ndarray:
    """Every query attends mostly to one token."""
    attn = np.full((layers, heads, tokens, tokens), 0.1 / (tokens - 1), dtype=np.float32)
    attn[..., target] = 0.9
    return attn / attn.sum(axis=-1, keepdims=True)


def test_mean_pooled_rollout_finds_the_attended_patch():
    relevance = compute_attention_rollout(_focused_attention(16, target=9), pooling="mean")
    assert relevance.shape == (16,)  # every token is a patch: no CLS to drop
    assert int(np.argmax(relevance)) == 9
    assert relevance.sum() == pytest.approx(1.0, abs=1e-5)


def test_cls_rollout_keeps_its_original_behaviour():
    relevance = compute_attention_rollout(_focused_attention(17, target=5), pooling="cls")
    assert relevance.shape == (16,) and int(np.argmax(relevance)) == 4  # CLS row, CLS dropped


def test_a_grid_that_does_not_match_the_tokens_is_refused_not_padded():
    bundle = ActivationBundle(backbone="siglip_b16", patch_grid=(14, 14), pooling="mean",
                              attention=_focused_attention(150, target=3))
    with pytest.raises(AppException) as raised:
        build_relevance_map(bundle)
    assert raised.value.code == "XAI_UNAVAILABLE"


def _assert_clean_png(path: str, max_side: int) -> tuple[int, int]:
    with Image.open(path) as image:
        assert image.format == "PNG" and image.mode == "RGB"
        assert max(image.size) <= max_side
        # No text/EXIF/ICC/time chunks - only what decoding needs.
        assert not {k for k in image.info if k not in ("dpi",)}, image.info
        return image.size


def test_overlay_is_metadata_free_and_bounded(tmp_path):
    source = tmp_path / "big.jpg"
    exif = Image.Exif()
    exif[0x010F] = "SomeCameraMaker"  # Make
    Image.new("RGB", (4000, 3000), (90, 120, 150)).save(source, exif=exif.tobytes(),
                                                         icc_profile=b"\x00" * 128)
    out = tmp_path / "overlay.png"
    generate_semantic_overlay(str(source), np.random.default_rng(0).random((14, 14)),
                              4000, 3000, str(out))
    assert _assert_clean_png(str(out), PANEL_MAX_SIDE) == (1600, 1200)  # aspect kept
    assert b"SomeCameraMaker" not in out.read_bytes()


def test_spectrum_panel_draws_spai_split_only_when_told(tmp_path):
    spectrum = np.random.default_rng(1).random((224, 224)).astype(np.float32)
    with_meta = tmp_path / "with.png"
    generate_frequency_spectrum_panel(spectrum, str(with_meta),
                                      meta={"mask_radius": 16, "patches": 308, "patch_size": 224})
    without = tmp_path / "without.png"
    generate_frequency_spectrum_panel(spectrum, str(without))
    _assert_clean_png(str(with_meta), SPECTRUM_MAX_SIDE)
    _assert_clean_png(str(without), SPECTRUM_MAX_SIDE)
    assert b"matplotlib" not in with_meta.read_bytes()  # no Software tag
    # The annotated panel differs from the plain one (circle + label drawn).
    assert with_meta.read_bytes() != without.read_bytes()
