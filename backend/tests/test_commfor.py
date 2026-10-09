"""Community Forensics content detector (2026-10-09): pinned, strict, verified.

The model-backed tests are ``slow`` (they need the cached weights). The rest
check the pinned set, the registry rules and the crop geometry without a model.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.m2_analysis import detectors, registry
from app.shared import config
from app.shared.contracts.errors import InferenceError, ModelUnavailableError

FIXTURES = Path(__file__).parent / "fixtures" / "commfor"
# The authors' eval_using_huggingface.ipynb output on their DALL-E 2 samples.
NOTEBOOK = {"00000274.png": 0.9988, "00000420.png": 0.9878, "00000845.png": 0.9569,
            "00000916.png": 0.9516, "00000989.png": 0.7860}


# ---------------------------------------------------------------- no model needed

def test_both_content_detectors_are_pinned_and_commfor_is_the_baseline():
    assert set(config.SEMANTIC_BACKBONES) == {config.SEMANTIC_SIGLIP, config.SEMANTIC_COMMFOR}
    assert config.DETECTOR_PRIMARY == config.SEMANTIC_COMMFOR
    assert config.DETECTOR_PRIMARY_REVISION == config.SEMANTIC_COMMFOR_REVISION
    assert len(config.SEMANTIC_COMMFOR_REVISION) == 40 and len(config.SEMANTIC_COMMFOR_WEIGHTS_DIGEST) == 64
    assert isinstance(detectors.semantic(config.SEMANTIC_COMMFOR), detectors.CommForDetector)
    assert isinstance(detectors.semantic(config.SEMANTIC_SIGLIP), detectors.PretrainedDetector)
    assert detectors.primary is detectors.semantic(config.SEMANTIC_COMMFOR)


def test_an_unpinned_checkpoint_is_refused():
    with pytest.raises(ModelUnavailableError):
        detectors.semantic("someone/unpinned-detector")


@pytest.mark.parametrize("hyper, valid", [
    ({"checkpoint": config.SEMANTIC_COMMFOR, "revision": config.SEMANTIC_COMMFOR_REVISION, "head": None}, True),
    ({"checkpoint": config.SEMANTIC_SIGLIP, "revision": config.SEMANTIC_SIGLIP_REVISION, "head": None}, True),
    ({"checkpoint": config.SEMANTIC_SIGLIP, "revision": config.SEMANTIC_SIGLIP_REVISION,
      "head": {"file": "x", "sha256": "y", "id2label": {"0": "Real", "1": "AI"}}}, True),
    # Community Forensics takes no uploaded head.
    ({"checkpoint": config.SEMANTIC_COMMFOR, "revision": config.SEMANTIC_COMMFOR_REVISION,
      "head": {"file": "x", "sha256": "y"}}, False),
    # Wrong revision, unknown checkpoint, missing head key.
    ({"checkpoint": config.SEMANTIC_COMMFOR, "revision": "0" * 40, "head": None}, False),
    ({"checkpoint": "someone/unpinned", "revision": "0" * 40, "head": None}, False),
    ({"checkpoint": config.SEMANTIC_COMMFOR, "revision": config.SEMANTIC_COMMFOR_REVISION}, False),
])
def test_a_semantic_row_must_name_a_pinned_detector(hyper, valid):
    assert registry._valid_semantic(hyper) is valid


def test_the_baseline_rows_seed_commfor_with_its_fusion_operating_point():
    rows = registry.baseline_rows()
    sem = rows[registry.TYPE_SEMANTIC]
    assert sem["hyperparameters"] == {"checkpoint": config.SEMANTIC_COMMFOR,
                                      "revision": config.SEMANTIC_COMMFOR_REVISION, "head": None}
    assert sem["artifact_sha256"] == config.SEMANTIC_COMMFOR_WEIGHTS_DIGEST
    fusion = rows[registry.TYPE_FUSION]["hyperparameters"]
    assert (fusion["weight_semantic"], fusion["tau"]) == (0.55, 0.4524)


@pytest.mark.parametrize("size", [(1024, 768), (768, 1024), (500, 500), (4096, 1024)])
def test_the_crop_region_is_the_centre_square_the_model_sees(size):
    w, h = size
    x0, y0, x1, y1 = detectors.semantic(config.SEMANTIC_COMMFOR).crop_region(w, h)
    side = 384 * min(w, h) / 440  # crop side in original pixels
    assert (x1 - x0) * w == pytest.approx(side) and (y1 - y0) * h == pytest.approx(side)
    assert x0 + x1 == pytest.approx(1.0) and y0 + y1 == pytest.approx(1.0)  # centred


def test_uploaded_heads_are_refused_at_scoring_time():
    with pytest.raises(InferenceError):
        detectors.semantic(config.SEMANTIC_COMMFOR).score(str(FIXTURES / "00000274.png"), head=object())


def test_the_exact_patch_projection_is_the_same_linear_map_as_the_convolution():
    import torch

    torch.manual_seed(0)
    conv = torch.nn.Conv2d(3, 384, kernel_size=16, stride=16).double()
    x = torch.randn(2, 3, 384, 384, dtype=torch.float64)
    exact = detectors._ExactPatchProjection(conv)
    assert torch.allclose(exact(x), conv(x), atol=1e-10)
    assert exact.weight is conv.weight and exact.bias is conv.bias  # same tensors, nothing copied


# ------------------------------------------------------------- model-backed (slow)

@pytest.mark.slow
def test_the_authors_notebook_scores_are_reproduced():
    """Sign and integration canary: sigmoid(logit) = P(fake), the authors' convention.

    Four decimals on every device. On CUDA this holds only because the patch
    projection bypasses cuDNN's TF32 convolution (detectors._ExactPatchProjection):
    with TF32 the last sample read 0.7655 instead of 0.7860.
    """
    detector = detectors.semantic(config.SEMANTIC_COMMFOR)
    for name, expected in NOTEBOOK.items():
        assert round(detector.score(str(FIXTURES / name)).score, 4) == expected, name


@pytest.mark.slow
def test_a_digest_mismatch_refuses_to_load(monkeypatch):
    detector = detectors.CommForDetector(config.SEMANTIC_COMMFOR, revision=config.SEMANTIC_COMMFOR_REVISION,
                                         weights_digest="0" * 64, ai_is_positive=True)
    with pytest.raises(ModelUnavailableError, match="digest"):
        detector.load()


@pytest.mark.slow
def test_attention_capture_leaves_the_score_alone_and_matches_timm():
    import torch

    detector = detectors.semantic(config.SEMANTIC_COMMFOR)
    path = str(FIXTURES / "00000274.png")
    plain = detector.score(path).score
    captured = detector.score(path, capture=True)
    assert captured.score == plain  # bit-identical with the hooks attached
    maps = detector.attention_maps(captured.activations)
    assert maps["attention"].shape == (12, 6, 577, 577)
    assert (maps["patch_grid"], maps["pooling"], maps["backbone"]) == ((24, 24), "cls", "commfor_vits16")
    assert maps["region"] is not None

    # timm's own (non-fused) attention weights, read at attn_drop's output.
    grabbed = []
    blocks = list(detector._blocks())
    for block in blocks:
        block.attn.fused_attn = False
    hooks = [b.attn.attn_drop.register_forward_hook(lambda _m, _i, out: grabbed.append(out.detach()))
             for b in blocks]
    try:
        detector.score(path)
    finally:
        for hook in hooks:
            hook.remove()
        for block in blocks:
            block.attn.fused_attn = True
    eager = torch.stack([g[0] for g in grabbed]).float().cpu().numpy()
    assert float(np.abs(eager - maps["attention"]).max()) < 1e-4
