"""
Module M3 Visualisation & Overlay Engine (F.10, NF.13).
Upsamples attention heatmaps bicubically to native image dimensions, alpha-blends over originals,
and renders radial frequency spectrum panels.

INTEGRATION (Phase 3, changes.md 6.7):
- Each panel is generated and persisted independently: a frequency panel that
  cannot be drawn no longer throws away a good semantic panel (or vice versa).
  ``persist_explainability`` reports what happened as a status
  (generated / partial / unavailable) with reason codes, instead of raising.
- The spectrum panel shows SPAI's real low/high split (radius from the
  bundle's ``spectrum_meta``), not three fixed-fraction rings; with no meta it
  draws no rings at all rather than decorative ones.
- PNGs carry no metadata (no EXIF/ICC/text chunks, no "Software" tag) and are
  bounded: the overlay keeps the original's aspect at native resolution up to
  ``PANEL_MAX_SIDE`` px on its longer side (the 14x14 relevance map carries no
  detail beyond that), the spectrum panel is at most ``SPECTRUM_MAX_SIDE``.
- References are stored relative to the explainability folder when inside it,
  never as absolute machine paths.
"""
from __future__ import annotations
import io
import os
from dataclasses import dataclass, field
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

PANEL_MAX_SIDE = 1600
SPECTRUM_MAX_SIDE = 768

TECHNIQUE_SEMANTIC = "attention-rollout"
TECHNIQUE_FREQUENCY = "spai-patch-spectrum"


def _save_clean_png(pixels: np.ndarray | Image.Image, output_path: str, max_side: int) -> None:
    """Write an RGB PNG with no metadata chunks, longer side <= max_side."""
    image = pixels if isinstance(pixels, Image.Image) else Image.fromarray(pixels)
    # Rebuild from raw pixels: drops every info/EXIF/ICC/text entry the source carried.
    clean = Image.frombytes("RGB", image.size, image.convert("RGB").tobytes())
    if max(clean.size) > max_side:
        scale = max_side / max(clean.size)
        clean = clean.resize((max(1, round(clean.width * scale)), max(1, round(clean.height * scale))),
                             Image.Resampling.LANCZOS)
    # compress_level 6 without optimize: optimize=True spent ~3 s of a 3.7 s
    # overlay on a 16 MP image (measured, Phase 3) for ~6% smaller files.
    clean.save(output_path, format="PNG", compress_level=6)


def _bounded(width: int, height: int, max_side: int) -> tuple[int, int]:
    if max(width, height) <= max_side:
        return width, height
    scale = max_side / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


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

    The relevance grid covers the WHOLE image: the semantic model's processor
    resizes the full image to 224x224 (no crop), so grid cell (i, j) is the
    i-th/j-th fourteenth of the image's height/width.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # INTEGRATION (changes.md 6.6): no substitute canvas when the original is
    # missing - an overlay drawn on a grey placeholder would present a heat map
    # over an image that is not there. Refuse; the caller reports
    # XAI_UNAVAILABLE and the prediction itself is unaffected.
    if not os.path.exists(original_image_path):
        raise AppException(
            code="XAI_UNAVAILABLE",
            message="The original image file is missing, so no overlay can be drawn on it.",
            status_code=501,
        )
    target_width, target_height = _bounded(target_width, target_height, PANEL_MAX_SIDE)
    with Image.open(original_image_path) as handle:
        orig_img = ImageOps.exif_transpose(handle).convert("RGB")

    # Match target dimensions
    if orig_img.size != (target_width, target_height):
        orig_img = orig_img.resize((target_width, target_height), Image.Resampling.BICUBIC)

    # 1. Upsample relevance map bicubically to native image dimensions
    heatmap_pil = Image.fromarray((np.clip(relevance_2d, 0.0, 1.0) * 255).astype(np.uint8))
    upsampled_heatmap = heatmap_pil.resize((target_width, target_height), Image.Resampling.BICUBIC)
    heatmap_arr = np.array(upsampled_heatmap, dtype=np.float32) / 255.0

    # 2. Apply perceptually uniform colormap (turbo)
    colormap = matplotlib.colormaps["turbo"]
    colored_heatmap = (colormap(heatmap_arr)[:, :, :3] * 255).astype(np.uint8)
    colored_pil = Image.fromarray(colored_heatmap)

    # 3. Alpha-blend over original image at opacity alpha
    blended = Image.blend(orig_img, colored_pil, alpha=alpha)
    _save_clean_png(blended, output_path, PANEL_MAX_SIDE)
    return output_path


def generate_frequency_spectrum_panel(
    spectrum: np.ndarray | None,
    output_path: str,
    width: int = 512,
    height: int = 512,
    meta: dict | None = None,
) -> str:
    """
    Renders the log-magnitude 2D spectrum, with SPAI's low/high split when known.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if spectrum is None:
        # INTEGRATION: used to draw a synthetic spectrum here. A made-up
        # spectrum presented as the image's own is fabricated evidence;
        # surface XAI_UNAVAILABLE instead (PRD4 4.2.2). See changes.md.
        raise AppException(
            code="XAI_UNAVAILABLE",
            message="No frequency spectrum was provided for this prediction.",
            status_code=501,
        )
    spec_arr = np.asarray(spectrum, dtype=np.float32)

    fig, ax = plt.subplots(figsize=(5.4, 5), dpi=100)
    try:
        fig.patch.set_facecolor("#111827")
        ax.set_facecolor("#111827")
        size_y, size_x = spec_arr.shape
        # Frequencies in cycles per patch, centred on DC.
        extent = (-size_x / 2, size_x / 2, -size_y / 2, size_y / 2)
        # The DC peak is several times larger than everything else, so a
        # full-range colour scale renders the panel almost black. Clip the
        # COLOUR RANGE (not the data) to the 1st-99.5th percentile, and say so.
        low, high = np.percentile(spec_arr, [1.0, 99.5])
        im = ax.imshow(spec_arr, cmap="inferno", origin="lower", extent=extent,
                       vmin=float(low), vmax=float(high))
        bar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, extend="both")
        bar.set_label("log(1 + |FFT|)  (colour range: 1st-99.5th percentile)",
                      color="#f3f4f6", fontsize=8)
        bar.ax.tick_params(colors="#9ca3af", labelsize=7)

        if meta and meta.get("mask_radius"):
            radius = float(meta["mask_radius"])
            ax.add_patch(plt.Circle((0, 0), radius, color="#38bdf8", fill=False,
                                    linestyle="--", linewidth=1.4))
            ax.annotate(f"SPAI low/high split (r = {int(radius)})", xy=(radius * 0.71, radius * 0.71),
                        xytext=(size_x * 0.12, size_y * 0.38), color="#38bdf8", fontsize=8,
                        arrowprops={"arrowstyle": "-", "color": "#38bdf8", "lw": 0.8})
            title = (f"Mean spectrum of the {meta.get('patches', '?')} "
                     f"{meta.get('patch_size', '?')}x{meta.get('patch_size', '?')} patches SPAI analysed")
        else:
            title = "Log-magnitude spectrum (FFT)"
        ax.set_title(title, color="#f3f4f6", fontsize=9.5, pad=8)
        ax.set_xlabel("horizontal frequency (cycles / patch)", color="#9ca3af", fontsize=8)
        ax.set_ylabel("vertical frequency (cycles / patch)", color="#9ca3af", fontsize=8)
        ax.tick_params(colors="#9ca3af", labelsize=7)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", bbox_inches="tight", facecolor=fig.get_facecolor(),
                    edgecolor="none", metadata={"Software": None})
    finally:
        plt.close(fig)
    buffer.seek(0)
    with Image.open(buffer) as rendered:
        _save_clean_png(rendered, output_path, SPECTRUM_MAX_SIDE)
    return output_path


@dataclass
class ExplainabilityResult:
    """What persist_explainability produced. Never raised as an error."""

    status: str  # "generated" | "partial" | "unavailable"
    reasons: list[str] = field(default_factory=list)
    rows: list[Explainability] = field(default_factory=list)


def _reference(path: str, storage_dir: str) -> str:
    """Store a path relative to the explainability folder when it is inside it."""
    try:
        return os.path.relpath(path, config.EXPLAINABILITY_DIR) if \
            os.path.commonpath([os.path.abspath(path), str(config.EXPLAINABILITY_DIR)]) == \
            str(config.EXPLAINABILITY_DIR) else os.path.abspath(path)
    except ValueError:  # different drives on Windows
        return os.path.abspath(path)


def explainability_path(reference: str) -> str:
    """Absolute path of a stored D5 visualization_reference (relative or legacy absolute)."""
    return reference if os.path.isabs(reference) else str(config.EXPLAINABILITY_DIR / reference)


def persist_explainability(
    prediction_id: int,
    db_image: DBImage,
    activation_bundle: ActivationBundle,
    db: Session,
    storage_dir: str = str(config.EXPLAINABILITY_DIR),
) -> ExplainabilityResult:
    """Draw each panel independently and record the ones that succeeded in D5.

    Returns a status rather than raising: SRS C.3 - explainability failing
    must never turn a successful prediction into an error. Commits its own
    transaction (D4 is already committed by M2 before this runs).
    """
    os.makedirs(storage_dir, exist_ok=True)
    w = db_image.width or 512
    h = db_image.height or 512
    reasons: list[str] = []
    rows: list[Explainability] = []

    # 1. Semantic attention rollout
    try:
        relevance_2d, technique = build_relevance_map(activation_bundle)
        sem_path = os.path.join(storage_dir, f"pred_{prediction_id}_semantic.png")
        generate_semantic_overlay(
            original_image_path=db_image.file_reference,
            relevance_2d=relevance_2d,
            target_width=w,
            target_height=h,
            output_path=sem_path,
            alpha=0.45,
        )
        rows.append(Explainability(prediction_id=prediction_id, branch="semantic",
                                   technique=technique,
                                   visualization_reference=_reference(sem_path, storage_dir)))
    except AppException as exc:
        reasons.append(f"semantic:{exc.code}")
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"semantic:{type(exc).__name__}")

    # 2. Frequency spectrum panel
    if activation_bundle.spectrum is None:
        reasons.append("frequency:not_applicable")  # below one SPAI patch, or branch off
    else:
        try:
            freq_path = os.path.join(storage_dir, f"pred_{prediction_id}_frequency.png")
            generate_frequency_spectrum_panel(spectrum=activation_bundle.spectrum,
                                              output_path=freq_path,
                                              meta=activation_bundle.spectrum_meta)
            rows.append(Explainability(prediction_id=prediction_id, branch="frequency",
                                       technique=TECHNIQUE_FREQUENCY if activation_bundle.spectrum_meta
                                       else "fft-radial-spectrum",
                                       visualization_reference=_reference(freq_path, storage_dir)))
        except AppException as exc:
            reasons.append(f"frequency:{exc.code}")
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"frequency:{type(exc).__name__}")

    if rows:
        # Clean existing rows if any for idempotency
        db.query(Explainability).filter(Explainability.prediction_id == prediction_id).delete()
        db.add_all(rows)
        db.commit()
        for row in rows:
            db.refresh(row)
    status = "unavailable" if not rows else ("generated" if len(rows) == 2 else "partial")
    return ExplainabilityResult(status=status, reasons=reasons, rows=rows)


def generate_and_persist_explainability(
    prediction_id: int,
    db_image: DBImage,
    activation_bundle: ActivationBundle,
    db: Session,
    # INTEGRATION: was "./uploads/xai" (relative to the working directory);
    # now the shared storage tree, served only through the owner-checked
    # GET /api/v1/explainability/{prediction_id}/{branch}.
    storage_dir: str = str(config.EXPLAINABILITY_DIR),
) -> list[Explainability]:
    """
    Orchestrates generation of semantic and frequency panels and persists records in D5.explainability.

    Kept for existing callers (M3's stub): raises XAI_UNAVAILABLE only when no
    panel at all could be produced; ``persist_explainability`` is the
    status-returning form the live predict path uses.
    """
    result = persist_explainability(prediction_id, db_image, activation_bundle, db, storage_dir)
    if result.status == "unavailable":
        raise AppException(code="XAI_UNAVAILABLE",
                           message=f"No explainability panel could be produced: {result.reasons}",
                           status_code=501)
    return result.rows
