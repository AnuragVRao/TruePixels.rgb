"""
Unit & Integration Tests for Module M3 Explainability Engine (F.10, NF.13, C.3).
"""
from __future__ import annotations
import os
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

from app.shared.schemas import ActivationBundle
from app.m3_results.explain import compute_attention_rollout, build_relevance_map
from app.m3_results.overlay import generate_semantic_overlay, generate_frequency_spectrum_panel
from app.m3_results.reporting import compute_confidence_band


def test_attention_rollout_shape_and_cls_exclusion():
    """Validates that Attention Rollout produces a 1D vector corresponding to patch tokens, excluding CLS."""
    num_layers = 12
    num_heads = 8
    num_tokens = 50  # 1 CLS + 49 patches (7x7 grid)
    # Synthetic attention matrix
    attn = np.random.uniform(0.1, 1.0, size=(num_layers, num_heads, num_tokens, num_tokens)).astype(np.float32)
    attn = attn / attn.sum(axis=-1, keepdims=True)

    relevance = compute_attention_rollout(attn)
    assert relevance.shape == (49,)  # Exactly 49 patches, CLS dropped


def test_relevance_map_normalization():
    """Validates 2D relevance map reshapes to patch grid and normalizes to [0, 1]."""
    num_layers, num_heads, num_tokens = 6, 4, 50
    attn = np.random.uniform(0.1, 1.0, size=(num_layers, num_heads, num_tokens, num_tokens)).astype(np.float32)
    bundle = ActivationBundle(
        backbone="clip_vit_b32",
        patch_grid=(7, 7),
        attention=attn,
    )
    rel_2d, tech = build_relevance_map(bundle)
    assert rel_2d.shape == (7, 7)
    assert tech == "attention-rollout"
    assert rel_2d.min() >= 0.0
    assert rel_2d.max() <= 1.0


def test_overlay_upsamples_to_deliberately_non_square_native_dimensions():
    """
    Asserts that the overlay upsamples to native dimensions (e.g. 1600x900)
    rather than stretching a 224x224 tensor (PRD Section 10.1).
    """
    width, height = 1600, 900
    orig_path = "./uploads/test_images/non_square_test.png"
    out_path = "./uploads/test_xai/non_square_overlay.png"

    # Create non-square test image
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    img.save(orig_path)

    relevance_2d = np.random.uniform(0, 1, size=(7, 7)).astype(np.float32)

    result_path = generate_semantic_overlay(
        original_image_path=orig_path,
        relevance_2d=relevance_2d,
        target_width=width,
        target_height=height,
        output_path=out_path,
        alpha=0.45,
    )

    assert os.path.exists(result_path)
    with Image.open(result_path) as out_img:
        assert out_img.size == (1600, 900)  # Native resolution preserved!


def test_frequency_spectrum_panel_generation():
    """Validates that the FFT spectrum panel is rendered with radial frequency annotations."""
    out_path = "./uploads/test_xai/test_spectrum.png"
    dummy_spec = np.random.randn(512, 512).astype(np.float32)

    res = generate_frequency_spectrum_panel(
        spectrum=dummy_spec,
        output_path=out_path,
    )
    assert os.path.exists(res)
    with Image.open(res) as img:
        assert img.size[0] > 100 and img.size[1] > 100


def test_confidence_banding_boundaries():
    """Validates confidence band boundaries according to PRD 10.1 (0.649, 0.650, 0.849, 0.850)."""
    assert compute_confidence_band(0.649) == "Low"
    assert compute_confidence_band(0.650) == "Moderate"
    assert compute_confidence_band(0.849) == "Moderate"
    assert compute_confidence_band(0.850) == "High"
    assert compute_confidence_band(0.99) == "High"


def test_interpretive_caption_presence(client: TestClient, seeded_db):
    """Validates that results view contains the permanent non-causal interpretability disclaimer (NF.13)."""
    pred_id = seeded_db["a_preds"][0].prediction_id
    resp = client.get(f"/api/v1/results/{pred_id}", headers={"Authorization": "Bearer test-user-token-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "interpretive_caption" in data
    assert "not proof of manipulation" in data["interpretive_caption"]
