"""
Module M3 Explainability Engine (F.10, OI-4).
Computes Attention Rollout and Gradient-Weighted Patch Attribution on ViT activations.
"""
from __future__ import annotations
import numpy as np
from app.shared.errors import AppException
from app.shared.schemas import ActivationBundle


def compute_attention_rollout(
    attention_matrices: np.ndarray,
    discard_ratio: float = 0.0,
    head_fusion: str = "mean",
    pooling: str = "cls",
) -> np.ndarray:
    """
    Computes Attention Rollout across transformer layers according to Abnar & Zuidema (2020).
    attention_matrices shape: (num_layers, num_heads, num_tokens, num_tokens)

    ``pooling`` (INTEGRATION, changes.md 6.7) - how the classifier reads the
    final tokens, which decides which row(s) of the rolled-out matrix matter:
    - ``"cls"``: a CLS token at index 0 feeds the classifier; returns its row
      over the patch tokens, length num_tokens - 1 (M3's original behaviour).
    - ``"mean"``: the classifier averages ALL tokens and there is no CLS token
      (SigLIP). Every token's row contributes equally to that average, so the
      relevance of each input patch is the mean of the rolled-out rows;
      returns length num_tokens.
    """
    if attention_matrices is None or len(attention_matrices.shape) < 3:
        raise ValueError("Invalid attention matrices provided.")

    if len(attention_matrices.shape) == 4:
        # Fuse heads (mean across head dimension)
        if head_fusion == "mean":
            attn = attention_matrices.mean(axis=1)  # (layers, tokens, tokens)
        elif head_fusion == "max":
            attn = attention_matrices.max(axis=1)
        else:
            attn = attention_matrices.mean(axis=1)
    else:
        attn = attention_matrices

    num_layers, num_tokens, _ = attn.shape
    eye = np.eye(num_tokens)
    result = eye.copy()

    for i in range(num_layers):
        layer_attn = attn[i]
        # Include residual connection (0.5 * Attention + 0.5 * Identity)
        layer_with_res = 0.5 * layer_attn + 0.5 * eye
        # Normalize rows to sum to 1
        row_sums = layer_with_res.sum(axis=-1, keepdims=True)
        layer_with_res = np.divide(layer_with_res, row_sums, out=np.zeros_like(layer_with_res), where=row_sums != 0)
        result = np.matmul(layer_with_res, result)

    if pooling == "mean":
        return result.mean(axis=0)
    # CLS token attention to patch tokens (exclude index 0 which is CLS itself)
    cls_attention_to_patches = result[0, 1:]
    return cls_attention_to_patches


def build_relevance_map(
    bundle: ActivationBundle,
) -> tuple[np.ndarray, str]:
    """
    Constructs normalized 2D patch relevance map from ActivationBundle.
    Returns: (2D array [grid_h, grid_w] normalized to [0, 1], technique_name)
    """
    grid_h, grid_w = bundle.patch_grid
    expected_patches = grid_h * grid_w

    if bundle.attention is not None:
        attention_arr = np.asarray(bundle.attention, dtype=np.float32)
        raw_relevance = compute_attention_rollout(attention_arr, pooling=bundle.pooling)
        # Community Forensics (CLS-pooled ViT on a centre crop) gets its own
        # technique name so its panel carries its own caption; every other
        # backbone keeps "attention-rollout" (SigLIP 2's caption).
        technique = "commfor-attention-rollout" if bundle.backbone == "commfor_vits16" else "attention-rollout"
    elif bundle.patch_embeddings is not None and bundle.head_gradients is not None:
        # Gradient-weighted patch attribution
        patches = np.asarray(bundle.patch_embeddings, dtype=np.float32)
        grads = np.asarray(bundle.head_gradients, dtype=np.float32)
        # Weight patches by gradients
        raw_relevance = np.maximum(0, (patches * grads).sum(axis=-1))
        technique = "grad-attribution"
    else:
        # INTEGRATION: this branch used to return a synthetic Gaussian map
        # labelled "synthetic-fallback", which renders as a plausible heatmap
        # that explains nothing. PRD4 4.2.2: surface XAI_UNAVAILABLE rather
        # than fabricate one. See changes.md.
        raise AppException(
            code="XAI_UNAVAILABLE",
            message="The active model exposed no attention or gradient state for this prediction.",
            status_code=501,
        )

    # INTEGRATION (changes.md 6.7): this used to truncate or zero-pad a vector
    # of the wrong length to fit the grid. Zero-padding invents relevance and
    # truncation shifts every patch; both draw a wrong map. A mismatch means
    # the bundle does not describe this model - refuse.
    if len(raw_relevance) != expected_patches:
        raise AppException(
            code="XAI_UNAVAILABLE",
            message=(f"relevance has {len(raw_relevance)} entries but the patch grid "
                     f"{grid_h}x{grid_w} needs {expected_patches}"),
            status_code=501,
        )

    relevance_2d = raw_relevance.reshape((grid_h, grid_w))

    # Normalize to [0, 1]
    min_val = relevance_2d.min()
    max_val = relevance_2d.max()
    if max_val > min_val:
        relevance_2d = (relevance_2d - min_val) / (max_val - min_val)
    else:
        relevance_2d = np.zeros_like(relevance_2d)

    return relevance_2d.astype(np.float32), technique


# --------------------------------------------------------------------------
# What each panel means - shown wherever a panel is shown (results, PDF).
# NF.13: interpretability without overclaiming. (changes.md 6.7)
# --------------------------------------------------------------------------

CAPTIONS: dict[str, str] = {
    "attention-rollout": (
        "Attention rollout of the SigLIP 2 classifier - an attention-based proxy for "
        "where the model looked, averaged over every image patch as its classifier does. "
        "It is not a measurement of what caused the verdict, not a map of where an image "
        "was edited or generated, and it does not say whether a region pushed the verdict "
        "towards Real or towards AI Generated."
    ),
    "commfor-attention-rollout": (
        "Attention rollout of the content detector (Community Forensics ViT) - an "
        "attention-based proxy for which parts of its 384x384 centre crop the token it "
        "classifies from attended to. It is not a measurement of what caused the verdict, "
        "not a map of where an image was edited or generated, and it does not say whether "
        "a region pushed the verdict towards Real or towards AI Generated."
    ),
    "spai-patch-spectrum": (
        "Average frequency content of the 224x224 patches the frequency detector (SPAI) "
        "analysed, with SPAI's low/high split marked (r = 16). Descriptive only: it shows "
        "which frequencies are present in what SPAI saw - not which of them drove its score."
    ),
}


def caption_for(technique: str) -> str:
    return CAPTIONS.get(technique, "Explainability visualisation; see the report notes.")
