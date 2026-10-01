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
) -> np.ndarray:
    """
    Computes Attention Rollout across transformer layers according to Abnar & Zuidema (2020).
    attention_matrices shape: (num_layers, num_heads, num_tokens, num_tokens)
    Returns: 1D token relevance vector of length (num_tokens - 1) for the patches.
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
        raw_relevance = compute_attention_rollout(attention_arr)
        technique = "attention-rollout"
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

    # Slice or pad if patch count deviates
    if len(raw_relevance) > expected_patches:
        raw_relevance = raw_relevance[:expected_patches]
    elif len(raw_relevance) < expected_patches:
        padded = np.zeros(expected_patches, dtype=np.float32)
        padded[:len(raw_relevance)] = raw_relevance
        raw_relevance = padded

    relevance_2d = raw_relevance.reshape((grid_h, grid_w))

    # Normalize to [0, 1]
    min_val = relevance_2d.min()
    max_val = relevance_2d.max()
    if max_val > min_val:
        relevance_2d = (relevance_2d - min_val) / (max_val - min_val)
    else:
        relevance_2d = np.zeros_like(relevance_2d)

    return relevance_2d.astype(np.float32), technique
