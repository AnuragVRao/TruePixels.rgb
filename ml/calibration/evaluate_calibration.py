"""Pilot: the FROZEN P(AI) map and certainty band on the held-out test set. Run ONCE.

    python ml/calibration/evaluate_calibration.py

PRE-REGISTERED (2026-10-08, committed before the first run):

- Headline arm: native test set, ml/outputs/sbr_test_tuned_20261001T172154Z.csv
  (Synthbuster vs RAISE-1k, scenes 0-98, 99 per class).
- Secondary arm: the same scenes with the reals centre-cropped to 1024^2,
  ml/outputs/sbr_crop1024_20260930T143201Z.csv (the confound-control arm).
- Primary metrics: Brier, log loss, calibration-in-the-large (CITL), and a
  diagnostic-only calibration slope/intercept refit (reported, NEVER applied).
  Secondary: ECE (equal-count, 10 bins). Bootstrap 95 % CIs (stratified,
  2000 resamples, seed config.SEED); Wilson for proportions.
- Certainty: accuracy of the tau-verdict within 'confident' vs 0.85 (AC2),
  with its Wilson lower bound; overall and split by side.
- "Material" native-vs-cropped difference: |CITL_native - CITL_cropped| > 0.05,
  or non-overlapping Brier CIs.
- No refit, no band edit, no second run. The map and band are read from
  backend/app/shared/config.py exactly as committed in phase 1.

WHAT THIS IS NOT. The test set is a different slice of scenes from the
validation split, drawn from the same population: same nine generators in
equal numbers, the same RAISE camera originals (same sizes, so the same Nikon
bodies), the same file formats. It shares no scene with validation. It is a
held-out same-distribution test, not a distribution-shift test. The cropped
arm changes the reals and is the only arm that differs from validation.

The semantic-only map cannot be tested here: every image is >= 256 px, so
SPAI scored them all.

Branch scores come from the stored CSVs, which evaluate.py produced through the
production path; the combined score is recomputed at the production w from the
stored branch scores, and P(AI) comes from backend calibration.calibrated() -
the function the pipeline will call. No GPU, no model load.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import calibration_metrics as cm  # noqa: E402
from app.m2_analysis import calibration, registry  # noqa: E402
from app.shared import config  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "ml" / "outputs"
ARMS = (
    ("native (headline)", OUTPUT_DIR / "sbr_test_tuned_20261001T172154Z.csv"),
    ("cropped reals (secondary)", OUTPUT_DIR / "sbr_crop1024_20260930T143201Z.csv"),
)
AC2_TARGET = 0.85
CITL_MATERIAL = 0.05


def bootstrap_refit(p: np.ndarray, y: np.ndarray, seed: int) -> dict:
    point = cm.diagnostic_refit(p, y)
    rng = np.random.default_rng(seed)
    slopes, intercepts = [], []
    for _ in range(cm.BOOTSTRAP_RESAMPLES):
        idx = cm.stratified_indices(y, rng)
        r = cm.diagnostic_refit(p[idx], y[idx])
        slopes.append(r["slope"])
        intercepts.append(r["intercept"])
    return {**point, "slope_ci": [float(np.percentile(slopes, 2.5)), float(np.percentile(slopes, 97.5))],
            "intercept_ci": [float(np.percentile(intercepts, 2.5)), float(np.percentile(intercepts, 97.5))],
            "applied": False}


def confident_report(p, certainty, score, y, tau) -> dict:
    confident = certainty == "confident"
    correct = (score >= tau).astype(int) == y
    out = {"coverage": float(confident.mean()), "coverage_ci": cm.wilson(int(confident.sum()), len(y))}
    for side, mask in (("all", confident), ("confident_ai", confident & (p >= 0.5)),
                       ("confident_real", confident & (p < 0.5)), ("inconclusive", ~confident)):
        n, k = int(mask.sum()), int(correct[mask].sum())
        ci = cm.wilson(k, n)
        out[side] = {"n": n, "correct": k, "accuracy": k / n if n else None, "wilson": ci,
                     "meets_085_point": (k / n >= AC2_TARGET) if n else None,
                     "meets_085_wilson_lower": (ci[0] >= AC2_TARGET) if n else None}
    return out


def evaluate_arm(name: str, csv_path: Path, models, seed: int) -> tuple[dict, tuple]:
    data = cm.load_scores(csv_path, config.FUSION_WEIGHT)
    if data["semantic_only"].any():
        raise SystemExit(f"{csv_path.name}: unexpected semantic-only rows")
    y, score = data["labels"], data["combined"]
    results = [calibration.calibrated(models, float(s), semantic_only=False) for s in score]
    if any(r.p_ai is None for r in results):
        raise SystemExit("the frozen map does not apply to the baseline configuration - refusing to report")
    p = np.array([r.p_ai for r in results])
    cert = np.array([r.certainty for r in results])
    raw = np.clip(score, 0, 1)

    per_generator = {}
    for gen in sorted({path.split("/")[1] for path, lab in zip(data["paths"], y) if lab == 1}):
        mask = np.array([lab == 1 and path.split("/")[1] == gen for path, lab in zip(data["paths"], y)])
        per_generator[gen] = {"n": int(mask.sum()), "mean_p_ai": float(p[mask].mean()),
                              "detected_at_tau": int((score[mask] >= config.FUSION_TAU).sum()),
                              "confident_ai": int(((cert == "confident") & (p >= 0.5) & mask).sum()),
                              "confident_real": int(((cert == "confident") & (p < 0.5) & mask).sum())}
    reals = y == 0
    report = {
        "arm": name, "csv": csv_path.relative_to(REPO_ROOT).as_posix(),
        "n": int(len(y)), "n_real": int(reals.sum()), "n_fake": int((~reals).sum()),
        "files_sha256": cm.files_sha256(data["paths"], y),
        "p_ai": cm.metric_block(p, y, seed),
        "raw_score": cm.metric_block(raw, y, seed),
        "p_ai_minus_raw": cm.paired_difference(p, raw, y, seed),
        "diagnostic_refit": bootstrap_refit(p, y, seed),
        "certainty": confident_report(p, cert, score, y, config.FUSION_TAU),
        "reals_only": {"n": int(reals.sum()), "mean_p_ai": float(p[reals].mean()),
                       "confident_ai_on_real": int(((cert == "confident") & (p >= 0.5) & reals).sum())},
        "per_generator_INDICATIVE_n11": per_generator,
        "reliability": cm.reliability_bins(p, y),
    }
    return report, (p, raw, y)


def fmt(block: dict) -> str:
    return f"{block['value']:+.4f} [{block['ci'][0]:+.4f}, {block['ci'][1]:+.4f}]"


def main() -> int:
    seed = config.SEED
    models = registry.baseline()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reports, series = [], []
    for name, path in ARMS:
        report, arrays = evaluate_arm(name, path, models, seed)
        reports.append(report)
        series.append((name, arrays))

    native, cropped = reports
    citl_gap = abs(native["p_ai"]["calibration_in_the_large"]["value"]
                   - cropped["p_ai"]["calibration_in_the_large"]["value"])
    bn, bc = native["p_ai"]["brier"]["ci"], cropped["p_ai"]["brier"]["ci"]
    brier_overlap = not (bn[1] < bc[0] or bc[1] < bn[0])
    materiality = {"citl_gap": citl_gap, "citl_material": citl_gap > CITL_MATERIAL,
                   "brier_cis_overlap": brier_overlap,
                   "material": citl_gap > CITL_MATERIAL or not brier_overlap}

    png = OUTPUT_DIR / f"reliability_pilot_{stamp}.png"
    cm.reliability_diagram([
        {"title": f"{name}, n = {len(arrays[2])}",
         "series": [("raw S", arrays[1], arrays[2]), ("P(AI), frozen map", arrays[0], arrays[2])]}
        for name, arrays in series
    ], png, "Test set (scenes 0-98), frozen map, equal-count bins, Wilson 95 % intervals")

    out = {"run_utc": stamp, "pre_registered": __doc__.split("WHAT THIS IS NOT")[0].strip(),
           "frozen_map": {"fused_a": config.CALIBRATION_FUSED_A, "fused_b": config.CALIBRATION_FUSED_B,
                          "ref": config.CALIBRATION_FUSED_REF, "band": config.CERTAINTY_CONFIDENT_P,
                          "fusion_weight": config.FUSION_WEIGHT, "tau": config.FUSION_TAU},
           "arms": reports, "materiality": materiality,
           "reliability_png": png.relative_to(REPO_ROOT).as_posix()}
    json_path = OUTPUT_DIR / f"calibration_pilot_{stamp}.json"
    json_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    for r in reports:
        print(f"\n== {r['arm']}  ({r['n_real']} real / {r['n_fake']} generated) ==")
        for metric in ("brier", "log_loss", "calibration_in_the_large", "ece_equal_count"):
            print(f"  {metric:26s} P(AI) {fmt(r['p_ai'][metric])}   raw S {fmt(r['raw_score'][metric])}")
        for metric in ("brier", "log_loss"):
            print(f"  {metric:26s} P(AI) - raw {fmt(r['p_ai_minus_raw'][metric])}")
        d = r["diagnostic_refit"]
        print(f"  diagnostic refit (NOT applied): slope {d['slope']:.3f} [{d['slope_ci'][0]:.3f}, {d['slope_ci'][1]:.3f}]"
              f"  intercept {d['intercept']:+.3f} [{d['intercept_ci'][0]:+.3f}, {d['intercept_ci'][1]:+.3f}]")
        c = r["certainty"]
        print(f"  coverage {c['coverage']:.3f} [{c['coverage_ci'][0]:.3f}, {c['coverage_ci'][1]:.3f}]")
        for side in ("all", "confident_ai", "confident_real", "inconclusive"):
            s = c[side]
            acc = "n/a" if s["accuracy"] is None else f"{s['accuracy']:.3f} [{s['wilson'][0]:.3f}, {s['wilson'][1]:.3f}]"
            print(f"    {side:15s} n={s['n']:3d} correct={s['correct']:3d} acc {acc}"
                  f"  >=0.85 point {s['meets_085_point']}  Wilson-lower {s['meets_085_wilson_lower']}")
        print(f"  reals: mean P(AI) {r['reals_only']['mean_p_ai']:.3f}, confident-AI on a real photo: "
              f"{r['reals_only']['confident_ai_on_real']}")
        print("  per generator (n = 11 each, INDICATIVE):")
        for gen, g in r["per_generator_INDICATIVE_n11"].items():
            print(f"    {gen:22s} mean P(AI) {g['mean_p_ai']:.3f}  detected {g['detected_at_tau']}/11"
                  f"  confident-AI {g['confident_ai']}  confident-Real {g['confident_real']}")
    print(f"\nmateriality: |CITL gap| {citl_gap:.4f} (> {CITL_MATERIAL}: {materiality['citl_material']}),"
          f" Brier CIs overlap: {brier_overlap} -> material: {materiality['material']}")
    print(f"wrote {json_path.relative_to(REPO_ROOT)} and {png.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
