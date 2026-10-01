"""Evaluate the pretrained branches on a labelled image set. EVALUATION ONLY.

    python ml/evaluation/evaluate.py <dataset_root> [--name attgan] [--limit N] [--seed S]

Reads weights, reports numbers, never updates anything - the distinction that
keeps this in scope under CLAUDE.md section 0.

Dataset layout: ``<root>/0_real/*`` and ``<root>/1_fake/*`` (the convention
used by ForenSynths, GANGen-Detection and SPAI's own evaluation sets). Folder
names carry the label; nothing is inferred from file names.

Each image goes through exactly the production path - ``detectors.primary``
(semantic), ``frequency_detector.frequency`` (spectral) and ``fusion.combine``
with the active configuration - so the numbers describe the system as
deployed, not a variant of it. Per-image results are appended to a CSV under
``ml/outputs/`` as they are produced, so an interrupted run loses nothing and
can be summarised as-is.

Reported, per branch and fused, at the production threshold tau: accuracy,
precision, recall, F1, false-positive rate on real images (the MM2.6 number),
and threshold-free ROC-AUC. Also the accuracy each branch WOULD reach at its
own best threshold - reported for information only. Choosing a threshold from
this number and shipping it would be fitting on the test set; the point of
printing it is to show how far the fixed tau is from that ceiling, not to
move tau.

EVERY NUMBER CARRIES AN INTERVAL. Proportions get a Wilson score interval and
AUC a percentile bootstrap, both at 95%. At the pilot sizes these evaluations
run at, the interval is the difference between a result and an anecdote: an
FPR of 0.04 over 99 images means "somewhere between 0.01 and 0.10", and
reporting the point estimate alone invites a claim the data cannot support.

When the fake class is split into per-generator subfolders, recall is also
reported per generator. The real class is shared, so the false-positive rate
stays a single number.

``--claim`` records, in the summary JSON, exactly what the run is evidence
for. It defaults to a deliberately narrow sentence, because "accuracy of the
system" is almost never what a single labelled set measures.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import numpy as np  # noqa: E402
from sklearn.metrics import roc_auc_score, roc_curve  # noqa: E402

from app.m2_analysis import detectors, frequency_detector, fusion, registry  # noqa: E402
from app.shared import config  # noqa: E402

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
OUTPUT_DIR = REPO_ROOT / "ml" / "outputs"


def collect(root: Path, limit: int | None, seed: int) -> list[tuple[Path, int]]:
    items: list[tuple[Path, int]] = []
    for folder, label in (("0_real", 0), ("1_fake", 1)):
        directory = root / folder
        if not directory.is_dir():
            raise SystemExit(f"expected {directory} - dataset layout is <root>/0_real and <root>/1_fake")
        # rglob, not iterdir: the fake class may be split into per-generator
        # subfolders, and a non-recursive scan would silently evaluate nothing.
        files = sorted(p for p in directory.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
        if limit is not None:
            random.Random(seed).shuffle(files)
            files = sorted(files[:limit])
        items.extend((p, label) for p in files)
    return items


def wilson(successes: int, total: int, z: float = 1.959963985) -> list[float | None]:
    """95% Wilson score interval for a proportion.

    Preferred over the normal approximation because it stays inside [0, 1] and
    behaves sensibly at 0, at 1 and at small n - all of which occur here.
    """
    if total == 0:
        return [None, None]
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    spread = z * np.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return [float(max(0.0, centre - spread)), float(min(1.0, centre + spread))]


def bootstrap_auc(scores: np.ndarray, labels: np.ndarray, resamples: int = 2000,
                  seed: int = 0) -> list[float | None]:
    """95% percentile bootstrap interval for ROC-AUC, stratified by class."""
    positive = np.flatnonzero(labels == 1)
    negative = np.flatnonzero(labels == 0)
    if len(positive) == 0 or len(negative) == 0:
        return [None, None]
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(resamples):
        index = np.concatenate([rng.choice(positive, len(positive), replace=True),
                                rng.choice(negative, len(negative), replace=True)])
        sample = labels[index]
        if len(set(sample.tolist())) == 2:
            values.append(roc_auc_score(sample, scores[index]))
    if not values:
        return [None, None]
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def show(point: float | None, interval: list, width: int = 20) -> str:
    """'0.042 [0.015, 0.104]' - the interval is never optional."""
    if point is None:
        return "n/a".rjust(width)
    if interval[0] is None:
        return f"{point:.3f}".rjust(width)
    return f"{point:.3f} [{interval[0]:.2f},{interval[1]:.2f}]".rjust(width)


def metrics_at(scores: np.ndarray, labels: np.ndarray, tau: float) -> dict:
    predicted = scores >= tau
    positive = labels == 1
    tp = int((predicted & positive).sum())
    tn = int((~predicted & ~positive).sum())
    fp = int((predicted & ~positive).sum())
    fn = int((~predicted & positive).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "accuracy": (tp + tn) / len(labels),
        "accuracy_ci": wilson(tp + tn, len(labels)),
        "precision": precision,
        "precision_ci": wilson(tp, tp + fp),
        "recall": recall,
        "recall_ci": wilson(tp, tp + fn),
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "fpr_on_real": fp / (fp + tn) if fp + tn else 0.0,
        "fpr_on_real_ci": wilson(fp, fp + tn),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


def _branch_arrays(rows: list[dict], labels: np.ndarray, key: str) -> tuple[np.ndarray, np.ndarray]:
    """Scores and labels for one branch, dropping images it declined to score."""
    kept = [i for i, r in enumerate(rows) if r[key] is not None]
    return (np.array([rows[i][key] for i in kept], dtype=float), labels[kept])


def summarise(scores: np.ndarray, labels: np.ndarray, tau: float) -> dict:
    out = metrics_at(scores, labels, tau)
    two_classes = len(set(labels.tolist())) == 2
    out["auc"] = float(roc_auc_score(labels, scores)) if two_classes else None
    out["auc_ci"] = bootstrap_auc(scores, labels, seed=config.SEED) if two_classes else [None, None]
    # Best achievable accuracy over all thresholds - INFORMATION ONLY, see docstring.
    fpr, tpr, thresholds = roc_curve(labels, scores)
    n_pos, n_neg = int((labels == 1).sum()), int((labels == 0).sum())
    accuracies = (tpr * n_pos + (1 - fpr) * n_neg) / len(labels)
    best = int(np.argmax(accuracies))
    out["best_threshold_accuracy_INFO_ONLY"] = float(accuracies[best])
    out["best_threshold_INFO_ONLY"] = float(thresholds[best]) if np.isfinite(thresholds[best]) else None
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", type=Path)
    parser.add_argument("--name", default=None, help="label for the output files (default: folder name)")
    parser.add_argument("--limit", type=int, default=None, help="images per class (random subset, seeded)")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--claim", default=None, help=(
        "what this run is evidence for; stored in the summary JSON. Defaults to a "
        "narrow sentence naming the two populations, because a labelled set measures "
        "a task, not the accuracy of the system."))
    args = parser.parse_args()

    name = args.name or args.root.name
    items = collect(args.root, args.limit, args.seed)
    models = registry.active()
    tau = models.fusion.tau

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = OUTPUT_DIR / f"{name}_{stamp}.csv"
    json_path = OUTPUT_DIR / f"{name}_{stamp}_summary.json"

    print(f"{len(items)} images ({sum(1 for _, l in items if l == 0)} real / {sum(1 for _, l in items if l == 1)} fake)")
    print(f"device {config.DEVICE} | tau {tau} | w {models.fusion.weight} | SPAI resize_to {config.DETECTOR_FREQUENCY_RESIZE_TO}")
    print("loading models ...", flush=True)
    detectors.primary.load()
    frequency_detector.frequency.load()

    rows: list[dict] = []
    started = time.perf_counter()
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "path", "label", "semantic", "frequency", "fusion", "predicted", "t_semantic_s", "t_frequency_s"])
        writer.writeheader()
        for index, (path, label) in enumerate(items, 1):
            t = time.perf_counter()
            semantic = detectors.primary.score(str(path)).score
            t_s = time.perf_counter() - t
            t = time.perf_counter()
            try:
                frequency = frequency_detector.frequency.score(str(path)).score
            except frequency_detector.SpectralBranchUnavailable:
                # Exactly what pipeline.run_detection does: the branch has no
                # evidence for this image (under SPAI's 224px patch), so the
                # verdict comes from the semantic branch alone. Scoring these
                # as 0.0, or aborting the run, would both misreport the system.
                frequency = None
            t_f = time.perf_counter() - t
            fused, predicted_class, _ = fusion.combine(semantic, frequency, models.fusion)
            row = {
                "path": str(path.relative_to(args.root)), "label": label,
                "semantic": f"{semantic:.6f}",
                "frequency": "" if frequency is None else f"{frequency:.6e}",
                "fusion": f"{fused:.6f}",
                "predicted": 1 if predicted_class == "AI Generated" else 0,
                "t_semantic_s": f"{t_s:.3f}", "t_frequency_s": f"{t_f:.3f}",
            }
            writer.writerow(row)
            handle.flush()
            rows.append({**row, "semantic": semantic, "frequency": frequency, "fusion": fused})
            if index % 100 == 0 or index == len(items):
                elapsed = time.perf_counter() - started
                print(f"  {index}/{len(items)}  {elapsed/index:.2f} s/img  eta {(len(items)-index)*elapsed/index/60:.1f} min", flush=True)

    labels = np.array([r["label"] for r in rows])
    declined = sum(1 for r in rows if r["frequency"] is None)

    # Per-generator recall, when the fake class is split into subfolders. The
    # real class is shared across generators, so FPR stays a single number and
    # is not repeated per generator.
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if row["label"] == 1:
            parts = Path(row["path"]).parts
            if len(parts) > 2:
                groups.setdefault(parts[1], []).append(row)
    per_generator = {}
    for generator, group in sorted(groups.items()):
        entry = {"n": len(group)}
        for key in ("semantic", "frequency", "fusion"):
            scored = [r for r in group if r[key] is not None]
            if not scored:
                entry[key] = entry[f"{key}_ci"] = entry[f"{key}_mean_score"] = None
                continue
            detected = sum(1 for r in scored if r[key] >= tau)
            entry[key] = detected / len(scored)
            entry[f"{key}_ci"] = wilson(detected, len(scored))
            entry[f"{key}_mean_score"] = float(np.mean([r[key] for r in scored]))
            if len(scored) != len(group):
                entry[f"{key}_n_scored"] = len(scored)
        per_generator[generator] = entry

    summary = {
        "dataset": name, "root": str(args.root), "n_real": int((labels == 0).sum()), "n_fake": int((labels == 1).sum()),
        "tau": tau, "fusion_weight": models.fusion.weight, "device": config.DEVICE,
        "semantic_checkpoint": config.DETECTOR_PRIMARY, "frequency_detector": config.DETECTOR_FREQUENCY_NAME,
        "frequency_resize_to": config.DETECTOR_FREQUENCY_RESIZE_TO,
        # The frequency branch is summarised over only the images it could
        # score. Including a declined image as 0.0 would count "no evidence" as
        # "confidently real" and flatter the branch; dropping it from semantic
        # and fusion would hide that the system still returned a verdict.
        "branches": {
            key: summarise(*_branch_arrays(rows, labels, key), tau)
            for key in ("semantic", "frequency", "fusion")
        },
        "frequency_branch_declined": declined,
        "claim": args.claim or (
            f"Separation of the '1_fake' population from the '0_real' population in "
            f"'{name}' ({int((labels == 0).sum())} real / {int((labels == 1).sum())} "
            f"generated) at the configured tau={tau}. Not a general accuracy figure for "
            f"the system, and evidence for nothing beyond these two populations."),
        "per_generator_detection_rate": per_generator,
        "mean_latency_s": {
            "semantic": float(np.mean([float(r["t_semantic_s"]) for r in rows])),
            "frequency": float(np.mean([float(r["t_frequency_s"]) for r in rows])) if rows else None,
        },
        "per_image_csv": str(csv_path),
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    n_real, n_fake = int((labels == 0).sum()), int((labels == 1).sum())
    print(f"\n=== {name}: {n_real} real / {n_fake} generated, tau = {tau} ===")
    print("all figures with 95% intervals (Wilson for rates, bootstrap for AUC)\n")
    print(f"{'branch':10} {'accuracy':>20} {'recall':>20} {'FPR on real':>20} {'AUC':>20}")
    for key, m in summary["branches"].items():
        print(f"{key:10} {show(m['accuracy'], m['accuracy_ci'])} "
              f"{show(m['recall'], m['recall_ci'])} "
              f"{show(m['fpr_on_real'], m['fpr_on_real_ci'])} "
              f"{show(m['auc'], m['auc_ci'])}")

    if declined:
        print(f"\nNOTE: the frequency branch declined {declined} of {len(rows)} images "
              f"(under its {frequency_detector.MIN_SIDE}px patch). Those took the "
              "documented passthrough - a semantic-only verdict - exactly as production "
              "does. The 'frequency' row below is over the rest; 'semantic' and 'fusion' "
              "are over all of them.")

    print("\ninformation only - NOT an operating point; choosing tau from this would be "
          "fitting on the test set:")
    for key, m in summary["branches"].items():
        print(f"  {key:10} best-threshold accuracy {m['best_threshold_accuracy_INFO_ONLY']:.3f} "
              f"@ {m['best_threshold_INFO_ONLY']}")

    if per_generator:
        per_n = next(iter(per_generator.values()))["n"]
        print(f"\n--- detection rate per generator (n={per_n} each - indicative only) ---")
        print(f"{'generator':24} {'SigLIP 2':>20} {'SPAI':>20} {'fused':>20}")
        for generator, entry in per_generator.items():
            print(f"{generator:24} {show(entry['semantic'], entry['semantic_ci'])} "
                  f"{show(entry['frequency'], entry['frequency_ci'])} "
                  f"{show(entry['fusion'], entry['fusion_ci'])}")

    print(f"\nclaim: {summary['claim']}")
    print(f"\nper-image CSV: {csv_path}\nsummary JSON:  {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
