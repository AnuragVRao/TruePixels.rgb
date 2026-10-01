# TruePixels: this file is NOT from upstream. It transcribes the upstream yacs
# configuration - `spai/config.py` defaults merged with `configs/spai.yaml` -
# as a plain attribute tree, restricted to the keys that `build_mf_vit` and
# `build_vit` read. This avoids a runtime dependency on yacs and PyYAML.
#
# Every value below was cross-checked on 2026-09-12 against the training
# configuration embedded in the released `spai.pth` checkpoint. Where the two
# differ the difference is noted; the released inference config (spai.yaml)
# wins, because that is what the authors evaluate with.

from __future__ import annotations

from types import SimpleNamespace


def build_config(
    *,
    feature_extraction_batch: int = 400,
    minimum_patches: int = 4,
) -> SimpleNamespace:
    """The SPAI model configuration, as the vendored builders expect it.

    Args:
        feature_extraction_batch: how many 224x224 patches go through the
            backbone per forward call. Upstream default 400 assumes a GPU with
            8 GB; the caller lowers it on CPU. Affects memory only, never the
            result.
        minimum_patches: images that yield fewer sliding-window patches than
            this fall back to a five-crop. spai.yaml says 4; the checkpoint
            was trained with 1. Inference follows spai.yaml.
    """
    vit = SimpleNamespace(
        PATCH_SIZE=16,
        IN_CHANS=3,
        EMBED_DIM=768,
        DEPTH=12,
        NUM_HEADS=12,
        MLP_RATIO=4,
        QKV_BIAS=True,
        INIT_VALUES=None,  # spai.yaml overrides the 0.1 default; no layer-scale gammas
        USE_APE=True,
        USE_RPB=False,
        USE_SHARED_RPB=False,
        USE_MEAN_POOLING=True,
        USE_INTERMEDIATE_LAYERS=True,
        INTERMEDIATE_LAYERS=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        PROJECTION_DIM=1024,
        PROJECTION_LAYERS=2,
        PATCH_PROJECTION=True,
        PATCH_PROJECTION_PER_FEATURE=True,
        FEATURES_PROCESSOR="rine",
        PATCH_POOLING="mean",
    )
    fre = SimpleNamespace(
        MASKING_RADIUS=16,
        PROJECTOR_LAST_LAYER_ACTIVATION_TYPE=None,
        ORIGINAL_IMAGE_FEATURES_BRANCH=True,
        DISABLE_RECONSTRUCTION_SIMILARITY=False,
    )
    patch_vit = SimpleNamespace(
        PATCH_STRIDE=224,
        NUM_HEADS=12,
        ATTN_EMBED_DIM=1536,
        MINIMUM_PATCHES=minimum_patches,
    )
    model = SimpleNamespace(
        TYPE="vit",
        NUM_CLASSES=2,  # the builder maps <= 2 classes to a single BCE logit
        DROP_RATE=0.0,
        SID_DROPOUT=0.5,
        DROP_PATH_RATE=0.1,  # DropPath is the identity in eval mode
        REQUIRED_NORMALIZATION="positive_0_1",  # inputs are [0, 1] floats
        SID_APPROACH="freq_restoration",
        RESOLUTION_MODE="arbitrary",
        FEATURE_EXTRACTION_BATCH=feature_extraction_batch,
        VIT=vit,
        FRE=fre,
        PATCH_VIT=patch_vit,
        CLS_HEAD=SimpleNamespace(MLP_RATIO=3),
    )
    return SimpleNamespace(
        MODEL_WEIGHTS="mfm",
        DATA=SimpleNamespace(IMG_SIZE=224),
        MODEL=model,
        TRAIN=SimpleNamespace(MODE="supervised"),
    )
