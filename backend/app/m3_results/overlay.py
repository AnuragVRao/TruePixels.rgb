"""
Module M3 Visualisation & Overlay Engine (F.10, NF.13).
Upsamples attention heatmaps bicubically to native image dimensions, alpha-blends over originals,
and renders radial frequency spectrum panels.
"""
from __future__ import annotations
import os
import numpy as np
from PIL import Image, ImageOps
import matplotlib
matplotlib.use("Agg")  # Non-GUI backend for server thread-safety
import matplotlib.pyplot as plt
from sqlalchemy.orm import Session
from app.shared import config
from app.shared.errors import AppException
from app.shared.schemas import ActivationBundle
from app.m3_results.models import Explainability, Image as DBImage
from app.m3_results.explain import build_relevance_map


def generate_semantic_overlay(
    original_image_path: str,
    relevance_2d: np.ndarray,
    target_width: int,
    target_height: int,
    output_path: str,
    alpha: float = 0.45,
) -> str:
    """
    Upsamples 2D relevance map to native image dimensions (W, H), applies colormap,
    and alpha-blends over original image at ~0.45 opacity.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Load original image or create synthetic canvas if missing
    if os.path.exists(original_image_path):
        orig_img = Image.open(original_image_path).convert("RGB")
        # Ensure display orientation
        orig_img = ImageOps.exif_transpose(orig_img)
    else:
        orig_img = Image.new("RGB", (target_width, target_height), color=(200, 200, 200))

    # Match target dimensions
    if orig_img.size != (target_width, target_height):
        orig_img = orig_img.resize((target_width, target_height), Image.Resampling.BICUBIC)

    # 1. Upsample relevance map bicubically to native image dimensions
    heatmap_pil = Image.fromarray((relevance_2d * 255).astype(np.uint8))
    upsampled_heatmap = heatmap_pil.resize((target_width, target_height), Image.Resampling.BICUBIC)
    heatmap_arr = np.array(upsampled_heatmap, dtype=np.float32) / 255.0

    # 2. Apply perceptually uniform colormap (turbo)
    colormap = matplotlib.colormaps["turbo"]
    colored_heatmap = (colormap(heatmap_arr)[:, :, :3] * 255).astype(np.uint8)
    colored_pil = Image.fromarray(colored_heatmap)

    # 3. Alpha-blend over original image at opacity alpha
    blended = Image.blend(orig_img, colored_pil, alpha=alpha)
    blended.save(output_path, format="PNG")
    return output_path


def generate_frequency_spectrum_panel(
    spectrum: np.ndarray | None,
    output_path: str,
    width: int = 512,
    height: int = 512,
) -> str:
    """
    Renders the log-magnitude 2D spectrum with radial frequency markers.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fig, ax = plt.subplots(figsize=(5, 5), dpi=100)
    fig.patch.set_facecolor("#111827")
    ax.set_facecolor("#111827")

    if spectrum is not None:
        spec_arr = np.asarray(spectrum, dtype=np.float32)
    else:
        # INTEGRATION: used to draw a synthetic spectrum here. A made-up
        # spectrum presented as the image's own is fabricated evidence;
        # surface XAI_UNAVAILABLE instead (PRD4 4.2.2). See changes.md.
        plt.close(fig)
        raise AppException(
            code="XAI_UNAVAILABLE",
            message="No frequency spectrum was provided for this prediction.",
            status_code=501,
        )

    # Normalize spectrum
    s_min, s_max = spec_arr.min(), spec_arr.max()
    norm_spec = (spec_arr - s_min) / (s_max - s_min + 1e-8)

    im = ax.imshow(norm_spec, cmap="inferno", origin="lower")

    # Draw representative radial frequency bands
    cy, cx = norm_spec.shape[0] // 2, norm_spec.shape[1] // 2
    for radius in [cy // 4, cy // 2, int(cy * 0.75)]:
        circle = plt.Circle((cx, cy), radius, color="#38bdf8", fill=False, linestyle="--", alpha=0.6, linewidth=1.2)
        ax.add_patch(circle)

    ax.set_title("Log-Magnitude Spectrum (FFT)", color="#f3f4f6", fontsize=11, pad=10)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(output_path, format="png", bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return output_path


def generate_and_persist_explainability(
    prediction_id: int,
    db_image: DBImage,
    activation_bundle: ActivationBundle,
    db: Session,
    # INTEGRATION: was "./uploads/xai" (relative to the working directory);
    # now the shared storage tree that main.py serves at /static.
    storage_dir: str = str(config.EXPLAINABILITY_DIR),
) -> list[Explainability]:
    """
    Orchestrates generation of semantic and frequency panels and persists records in D5.explainability.
    """
    os.makedirs(storage_dir, exist_ok=True)
    w = db_image.width or 512
    h = db_image.height or 512

    # 1. Semantic Attention Rollout
    relevance_2d, technique = build_relevance_map(activation_bundle)
    sem_filename = f"pred_{prediction_id}_semantic.png"
    sem_path = os.path.join(storage_dir, sem_filename)
    generate_semantic_overlay(
        original_image_path=db_image.file_reference,
        relevance_2d=relevance_2d,
        target_width=w,
        target_height=h,
        output_path=sem_path,
        alpha=0.45,
    )

    # 2. Frequency Spectrum Panel
    freq_filename = f"pred_{prediction_id}_frequency.png"
    freq_path = os.path.join(storage_dir, freq_filename)
    generate_frequency_spectrum_panel(
        spectrum=activation_bundle.spectrum,
        output_path=freq_path,
    )

    # Clean existing rows if any for idempotency
    db.query(Explainability).filter(Explainability.prediction_id == prediction_id).delete()

    sem_entry = Explainability(
        prediction_id=prediction_id,
        branch="semantic",
        technique=technique,
        visualization_reference=sem_path,
    )
    freq_entry = Explainability(
        prediction_id=prediction_id,
        branch="frequency",
        technique="fft-radial-spectrum",
        visualization_reference=freq_path,
    )

    db.add(sem_entry)
    db.add(freq_entry)
    db.commit()
    db.refresh(sem_entry)
    db.refresh(freq_entry)

    return [sem_entry, freq_entry]
