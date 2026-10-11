"""Community Forensics tiled input mode (2026-10-10): whole-image coverage.

``tiled`` scores the image, resized as the authors do (shortest side 440), as
overlapping 384 px tiles covering all of it; the D3 row says which mode runs.
The model-backed tests are ``slow``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.m2_analysis import detectors, registry
from app.m3_results.explain import build_relevance_map
from app.shared import config
from app.shared.contracts.errors import InferenceError
from app.shared.errors import AppException
from app.shared.schemas import ActivationBundle

FIXTURES = Path(__file__).parent / "fixtures" / "commfor"
TILE = config.SEMANTIC_TILE_SIZE
COMMFOR = {"checkpoint": config.SEMANTIC_COMMFOR, "revision": config.SEMANTIC_COMMFOR_REVISION, "head": None}


# ---------------------------------------------------------------- no model needed

@pytest.mark.parametrize("length", [384, 385, 440, 586, 660, 767, 768, 769, 1000, 2400])
def test_tiles_cover_every_pixel_from_edge_to_edge(length):
    starts = detectors.CommForDetector.tile_positions(length, TILE)
    assert starts[0] == 0
    assert starts[-1] + TILE == max(length, TILE)  # the last tile ends on the last pixel
    assert all(b - a <= TILE for a, b in zip(starts, starts[1:]))  # no gap between tiles
    assert len(starts) == max(1, -(-length // TILE))  # ceil(length / tile)


@pytest.mark.parametrize("extra, valid", [
    ({}, True),  # rows registered before tiling existed: centre crop
    ({"input_mode": "center-crop"}, True),
    ({"input_mode": "tiled", "tile_aggregation": "mean"}, True),
    ({"input_mode": "tiled", "tile_aggregation": "max"}, True),
    ({"input_mode": "tiled"}, False),  # no aggregation
    ({"input_mode": "tiled", "tile_aggregation": "median"}, False),
    ({"input_mode": "mosaic", "tile_aggregation": "mean"}, False),
])
def test_a_semantic_row_names_a_known_input_mode(extra, valid):
    assert registry._valid_semantic({**COMMFOR, **extra}) is valid


def test_siglip_has_no_tiled_mode():
    siglip = {"checkpoint": config.SEMANTIC_SIGLIP, "revision": config.SEMANTIC_SIGLIP_REVISION, "head": None,
              "input_mode": "tiled", "tile_aggregation": "mean"}
    assert registry._valid_semantic(siglip) is False


def test_the_input_mode_is_part_of_the_row_and_its_version():
    plain = registry.semantic_row_spec(config.SEMANTIC_COMMFOR)
    assert "input_mode" not in plain["hyperparameters"]
    tiled = registry.semantic_row_spec(config.SEMANTIC_COMMFOR, input_mode="tiled", tile_aggregation="mean")
    assert tiled["hyperparameters"]["input_mode"] == "tiled"
    assert tiled["hyperparameters"]["tile_aggregation"] == "mean"
    assert tiled["model_version"].endswith("-tiled-mean") and tiled["model_version"] != plain["model_version"]
    assert registry._valid_semantic(tiled["hyperparameters"])


def _tile_attention(rng, layers=2, side=4):
    tokens = 1 + side * side
    a = rng.random((layers, tokens, tokens)).astype(np.float32)
    return a / a.sum(axis=-1, keepdims=True)


def test_tile_maps_are_assembled_over_the_whole_image():
    rng = np.random.default_rng(0)
    boxes = [(0.0, 0.0, 0.6, 1.0), (0.4, 0.0, 1.0, 1.0)]
    bundle = ActivationBundle(backbone="commfor_vits16", patch_grid=(4, 4), pooling="cls",
                              attention_tiles=[{"attention": _tile_attention(rng), "box": b} for b in boxes])
    relevance, technique = build_relevance_map(bundle)
    # Default: the score came from the centre crop; the tiles are for the panel only.
    assert technique == "commfor-whole-image-attention-rollout"
    scored = bundle.model_copy(update={"attention_tiles_scored": True})
    assert build_relevance_map(scored)[1] == "commfor-tiled-attention-rollout"
    assert relevance.shape[1] > relevance.shape[0]  # wider than tall, like the boxes' union
    assert relevance.min() == 0.0 and relevance.max() == 1.0


def test_tiles_that_leave_a_gap_are_refused_not_filled():
    rng = np.random.default_rng(1)
    boxes = [(0.0, 0.0, 0.4, 1.0), (0.6, 0.0, 1.0, 1.0)]  # nothing covers 0.4-0.6
    bundle = ActivationBundle(backbone="commfor_vits16", patch_grid=(4, 4), pooling="cls",
                              attention_tiles=[{"attention": _tile_attention(rng), "box": b} for b in boxes])
    with pytest.raises(AppException) as raised:
        build_relevance_map(bundle)
    assert raised.value.code == "XAI_UNAVAILABLE"


def test_siglip_refuses_the_tiled_mode(tmp_path):
    with pytest.raises(InferenceError, match="input mode"):
        detectors.semantic(config.SEMANTIC_SIGLIP).score(str(tmp_path / "x.png"), input_mode="tiled",
                                                         tile_aggregation="mean")


def test_tiled_scoring_needs_an_aggregation(tmp_path):
    with pytest.raises(InferenceError, match="tile_aggregation"):
        detectors.semantic(config.SEMANTIC_COMMFOR).score(str(tmp_path / "x.png"), input_mode="tiled")


# ---------------------------------------------------------------- model-backed

@pytest.mark.slow
def test_the_centre_crop_mode_is_unchanged_by_tiling():
    detector = detectors.semantic(config.SEMANTIC_COMMFOR)
    assert round(detector.score(str(FIXTURES / "00000989.png")).score, 4) == 0.7860


@pytest.mark.slow
def test_tiled_scores_combine_the_tiles_and_cover_a_wide_image(tmp_path):
    detector = detectors.semantic(config.SEMANTIC_COMMFOR)
    path = tmp_path / "wide.png"
    Image.fromarray(np.random.default_rng(3).integers(0, 256, (600, 1400, 3), dtype=np.uint8)).save(path)
    mean = detector.score(str(path), input_mode="tiled", tile_aggregation="mean")
    peak = detector.score(str(path), input_mode="tiled", tile_aggregation="max")
    # 600x1400 -> 440x1027: 2 rows x 3 columns of 384 px tiles.
    assert len(mean.tile_scores) == 6 and mean.tile_scores == peak.tile_scores
    assert mean.score == pytest.approx(sum(mean.tile_scores) / 6)
    assert peak.score == max(peak.tile_scores)

    captured = detector.score(str(path), capture=True, input_mode="tiled", tile_aggregation="mean")
    assert captured.score == mean.score  # hooks leave the score alone
    maps = detector.attention_maps(captured.activations)
    boxes = [t["box"] for t in maps["tiles"]]
    assert min(b[0] for b in boxes) == 0.0 and max(b[2] for b in boxes) == 1.0
    assert min(b[1] for b in boxes) == 0.0 and max(b[3] for b in boxes) == 1.0
    assert maps["tiles"][0]["attention"].shape == (12, 577, 577)
    bundle = ActivationBundle(backbone=maps["backbone"], patch_grid=maps["patch_grid"], pooling="cls",
                              attention_tiles=maps["tiles"])
    relevance, _ = build_relevance_map(bundle)
    assert relevance.shape[1] > 2 * relevance.shape[0]
