"""Is the semantic attention map faithful? A deletion sanity test. EVALUATION ONLY.

    python ml/evaluation/xai_faithfulness.py [--per-class 20] [--fraction 0.2] [--random-draws 10]

Question: does hiding the regions the attention-rollout map ranks highest
change the SigLIP 2 score MORE than hiding equally large random regions? If
not, the map is not telling us what the model relies on, and the caption must
say so.

Protocol (fixed before running; no parameter was tuned on the outcome):
- Sample: the first ``--per-class`` images of each class from ``sbr_val`` (the
  validation split, scenes 99-296 - never the test set), sorted by name.
- For each image: semantic score s0, and the 14x14 rollout map exactly as the
  product computes it (passive capture -> attention_maps -> M3 rollout with
  mean pooling).
- The map's grid covers the whole image (the processor resizes the full image
  to 224x224), so cell (i, j) is the i-th/j-th fourteenth of the image.
- Masks of k = round(fraction * 196) cells, filled with the image's mean
  colour: TOP-k (highest relevance), BOTTOM-k (lowest), and ``--random-draws``
  uniformly random k-subsets (seeded).
- Effect = |s(masked) - s0|, the absolute change in P(AI Generated).
- Per image: top effect vs the MEAN of its random effects (paired). Reported:
  means, a 95% bootstrap interval on the paired difference, a Wilcoxon
  signed-rank test, and the share of images where top beats random.

Only the semantic branch is scored; the map explains that branch alone.
Writes ml/outputs/xai_faithfulness_<stamp>.json (gitignored).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from scipy.stats import wilcoxon  # noqa: E402

from app.m2_analysis import detectors  # noqa: E402
from app.m3_results.explain import build_relevance_map  # noqa: E402
from app.shared.schemas import ActivationBundle  # noqa: E402

VAL = REPO / "ml" / "datasets" / "sbr_val"
SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def sample(per_class: int) -> list[tuple[Path, int]]:
    out = []
    for folder, label in (("0_real", 0), ("1_fake", 1)):
        files = sorted(p for p in (VAL / folder).rglob("*") if p.suffix.lower() in SUFFIXES)
        out += [(p, label) for p in files[:per_class]]
    return out


def relevance(path: str) -> tuple[float, np.ndarray]:
    result = detectors.primary.score(path, capture=True)
    maps = detectors.primary.attention_maps(result.activations)
    bundle = ActivationBundle(backbone=maps["backbone"], patch_grid=maps["patch_grid"],
                              attention=maps["attention"], pooling=maps["pooling"])
    grid, _ = build_relevance_map(bundle)
    return result.score, grid


def masked_score(image: Image.Image, cells: np.ndarray, grid: int, scratch: Path) -> float:
    pixels = np.asarray(image, dtype=np.uint8).copy()
    height, width = pixels.shape[:2]
    fill = pixels.reshape(-1, 3).mean(axis=0).astype(np.uint8)
    for index in cells:
        row, col = divmod(int(index), grid)
        top, bottom = round(row * height / grid), round((row + 1) * height / grid)
        left, right = round(col * width / grid), round((col + 1) * width / grid)
        pixels[top:bottom, left:right] = fill
    path = scratch / "masked.png"
    Image.fromarray(pixels).save(path)
    return detectors.primary.score(str(path)).score


def bootstrap(values: np.ndarray, draws: int = 5000, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    means = [rng.choice(values, len(values), replace=True).mean() for _ in range(draws)]
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-class", type=int, default=20)
    parser.add_argument("--fraction", type=float, default=0.2)
    parser.add_argument("--random-draws", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    items = sample(args.per_class)
    if not items:
        raise SystemExit(f"no images under {VAL}; fetch the validation split first")
    rng = np.random.default_rng(args.seed)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        for path, label in items:
            s0, grid_map = relevance(str(path))
            grid = grid_map.shape[0]
            flat = grid_map.reshape(-1)
            k = round(args.fraction * flat.size)
            order = np.argsort(flat, kind="stable")
            with Image.open(path) as handle:
                image = handle.convert("RGB")
            top = abs(masked_score(image, order[-k:], grid, scratch) - s0)
            bottom = abs(masked_score(image, order[:k], grid, scratch) - s0)
            randoms = [abs(masked_score(image, rng.choice(flat.size, k, replace=False), grid, scratch) - s0)
                       for _ in range(args.random_draws)]
            rows.append({"image": str(path.relative_to(REPO)), "label": label, "s0": s0,
                         "top": top, "bottom": bottom, "random_mean": float(np.mean(randoms)),
                         "random_all": randoms})
            print(f"  {label} s0={s0:.3f} top={top:.3f} random={np.mean(randoms):.3f} "
                  f"bottom={bottom:.3f}  {path.name}")

    top = np.array([r["top"] for r in rows])
    rand = np.array([r["random_mean"] for r in rows])
    bottom = np.array([r["bottom"] for r in rows])
    diff = top - rand
    stat = wilcoxon(top, rand, alternative="greater")
    summary = {
        "n_images": len(rows), "k_cells": round(args.fraction * 196), "fraction": args.fraction,
        "random_draws": args.random_draws, "seed": args.seed, "sample": "sbr_val (validation split)",
        "mean_abs_change": {"top": float(top.mean()), "random": float(rand.mean()),
                            "bottom": float(bottom.mean())},
        "top_minus_random": {"mean": float(diff.mean()), "ci95": bootstrap(diff)},
        "share_top_beats_random": float((diff > 0).mean()),
        "wilcoxon_top_gt_random": {"statistic": float(stat.statistic), "p": float(stat.pvalue)},
        "per_image": rows,
    }
    out = REPO / "ml" / "outputs" / f"xai_faithfulness_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_image"}, indent=2))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
