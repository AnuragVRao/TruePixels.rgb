"""Choose the decision threshold tau on a validation split. PRD2 FR-03.

    python ml/evaluation/select_threshold.py <validation_summary_or_csv>

WHY THIS IS NOT TRAINING. CLAUDE.md section 0 forbids training, fine-tuning or
retraining a model: no weight in this system is ever updated. ``tau`` is not a
weight. It is the operating point at which a probability becomes a verdict -
a policy choice about which error you would rather make - and PRD2 FR-03 is
explicit that it "is selected on the validation set to hold the false-positive
rate on real photographs at or below MM2.6". Step 4 was closed as "fitting is
training" back when no labelled data existed at all; that ruling was broader
than it needed to be, and this script is the narrow part of it reopened.

WHY A SEPARATE SPLIT. Choosing tau on the same images you then report is how a
test set quietly becomes a validation set and every number afterwards is
optimistic. The validation set here shares not one scene with the test set:
``fetch_synthbuster.py --per-model 22 --offset 99`` takes scenes 99-296, the
test set is scenes 0-98, and the RAISE reals follow the scene ids.

WHAT IS SELECTED. The smallest tau whose validation false-positive rate is at
or below the target - smallest because tau trades recall for FPR monotonically,
so the smallest qualifying value keeps the most recall. tau applies to
``fusion_score``, which is what ``fusion.combine`` thresholds.

TEMPERATURE. The same split can fit the calibration temperature T that PRD2
FR-04 asks for (MM2.5, ECE <= 0.05). It is REPORTED here, never applied,
because T and tau are coupled: ``combine()`` temperature-scales the fused
score and only then compares it to tau, so adopting a T means re-selecting
tau underneath it. Changing T also changes every confidence figure a user
sees. That is a decision, not a default.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared import config  # noqa: E402


def wilson(successes: int, total: int, z: float = 1.959963985) -> tuple[float, float]:
    if total == 0:
        return (0.0, 1.0)
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    spread = z * np.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def expected_calibration_error(scores: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    """ECE over confidence in the predicted class, equal-width bins."""
    confidence = np.where(scores >= 0.5, scores, 1 - scores)
    correct = (scores >= 0.5).astype(int) == labels
    total = 0.0
    edges = np.linspace(0.5, 1.0, bins + 1)
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (confidence >= low) & (confidence < high if high < 1.0 else confidence <= 1.0)
        if mask.sum():
            total += abs(correct[mask].mean() - confidence[mask].mean()) * mask.mean()
    return float(total)


def temperature_scale(scores: np.ndarray, temperature: float) -> np.ndarray:
    """Mirror of fusion.apply_temperature, vectorised."""
    if temperature == 1.0:
        return scores
    clamped = np.clip(scores, 1e-7, 1 - 1e-7)
    logit = np.log(clamped / (1 - clamped))
    return 1.0 / (1.0 + np.exp(-logit / temperature))


def fit_temperature(scores: np.ndarray, labels: np.ndarray) -> float:
    """T minimising negative log-likelihood. One scalar, on validation only."""
    best_t, best_nll = 1.0, np.inf
    for temperature in np.concatenate([np.arange(0.05, 1.0, 0.01), np.arange(1.0, 10.05, 0.05)]):
        scaled = np.clip(temperature_scale(scores, float(temperature)), 1e-7, 1 - 1e-7)
        nll = -np.mean(labels * np.log(scaled) + (1 - labels) * np.log(1 - scaled))
        if nll < best_nll:
            best_t, best_nll = float(temperature), float(nll)
    return best_t


def rates(scores: np.ndarray, labels: np.ndarray, tau: float) -> dict:
    predicted = scores >= tau
    real, fake = labels == 0, labels == 1
    fp = int((predicted & real).sum())
    tp = int((predicted & fake).sum())
    return {
        "tau": float(tau),
        "fpr": fp / max(1, int(real.sum())),
        "fpr_ci": wilson(fp, int(real.sum())),
        "recall": tp / max(1, int(fake.sum())),
        "recall_ci": wilson(tp, int(fake.sum())),
        "accuracy": float(((predicted.astype(int)) == labels).mean()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path, help="per-image CSV from evaluate.py on the VALIDATION set")
    parser.add_argument("--target-fpr", type=float, default=0.10, help="MM2.6, default 0.10")
    parser.add_argument("--column", default="fusion", help="score tau applies to (default: fusion)")
    args = parser.parse_args()

    rows = list(csv.DictReader(args.csv.open(encoding="utf-8")))
    scores = np.array([float(r[args.column]) for r in rows])
    labels = np.array([int(r["label"]) for r in rows])
    n_real, n_fake = int((labels == 0).sum()), int((labels == 1).sum())
    print(f"validation set: {args.csv.name}")
    print(f"  {n_real} real / {n_fake} generated, thresholding '{args.column}'")
    print(f"  current config: tau={config.FUSION_TAU}, T={config.CALIBRATION_TEMPERATURE}, "
          f"w={config.FUSION_WEIGHT}\n")

    # Candidate thresholds: every distinct score, plus the current one.
    candidates = sorted({*np.unique(scores).tolist(), config.FUSION_TAU})
    qualifying = [rates(scores, labels, t) for t in candidates]
    qualifying = [q for q in qualifying if q["fpr"] <= args.target_fpr]

    print(f"--- tau at the current setting ({config.FUSION_TAU}) ---")
    current = rates(scores, labels, config.FUSION_TAU)
    print(f"  FPR {current['fpr']:.3f} [{current['fpr_ci'][0]:.2f},{current['fpr_ci'][1]:.2f}]"
          f"   recall {current['recall']:.3f}   accuracy {current['accuracy']:.3f}")

    if not qualifying:
        print(f"\nNo threshold reaches FPR <= {args.target_fpr} on this split. "
              "MM2.6 is unreachable here; report that rather than moving the target.")
        return 1

    chosen = min(qualifying, key=lambda q: q["tau"])  # smallest tau => most recall
    print(f"\n--- selected tau (smallest with validation FPR <= {args.target_fpr}) ---")
    print(f"  tau = {chosen['tau']:.6f}")
    print(f"  FPR {chosen['fpr']:.3f} [{chosen['fpr_ci'][0]:.2f},{chosen['fpr_ci'][1]:.2f}]"
          f"   recall {chosen['recall']:.3f} [{chosen['recall_ci'][0]:.2f},{chosen['recall_ci'][1]:.2f}]"
          f"   accuracy {chosen['accuracy']:.3f}")
    print(f"  cost vs the current tau: recall {current['recall']:.3f} -> {chosen['recall']:.3f} "
          f"({chosen['recall'] - current['recall']:+.3f})")

    print("\n--- the trade, for context (validation only) ---")
    print(f"  {'tau':>10} {'FPR':>7} {'recall':>8}")
    for tau in (0.5, 0.7, 0.9, 0.95, 0.99, 0.999, chosen["tau"]):
        r = rates(scores, labels, tau)
        mark = "  <- selected" if abs(tau - chosen["tau"]) < 1e-12 else ""
        print(f"  {tau:10.6f} {r['fpr']:7.3f} {r['recall']:8.3f}{mark}")

    temperature = fit_temperature(scores, labels)
    ece_now = expected_calibration_error(scores, labels)
    ece_fitted = expected_calibration_error(temperature_scale(scores, temperature), labels)
    print(f"\n--- calibration (MM2.5, target ECE <= 0.05) - REPORTED, NOT APPLIED ---")
    print(f"  ECE at T=1.0          {ece_now:.3f}")
    print(f"  best T on validation  {temperature:.2f}  ->  ECE {ece_fitted:.3f}"
          f"{'  (meets MM2.5)' if ece_fitted <= 0.05 else '  (still misses MM2.5)'}")
    print("  Adopting T means re-selecting tau underneath it (combine() scales, then")
    print("  thresholds) and changes every confidence a user sees. Left as a decision.")

    out = args.csv.with_name(args.csv.stem + "_threshold.json")
    out.write_text(json.dumps({
        "validation_csv": str(args.csv), "n_real": n_real, "n_fake": n_fake,
        "column": args.column, "target_fpr": args.target_fpr,
        "current": current, "selected": chosen,
        "calibration": {"ece_at_T1": ece_now, "best_T": temperature, "ece_at_best_T": ece_fitted,
                        "applied": False},
        "note": "tau selected on this split only; report performance on the disjoint test set.",
    }, indent=2), encoding="utf-8")
    print(f"\nwritten: {out}")
    print("\nNEXT: set FUSION_TAU in backend/app/shared/config.py, then re-run")
    print("evaluate.py on the TEST set. That test number is the honest one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
