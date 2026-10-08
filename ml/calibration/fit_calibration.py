"""Fit the P(AI) display map on the validation split, and pre-register the certainty band.

    python ml/calibration/fit_calibration.py [validation_csv] [--band 0.90]

WHAT IS FITTED. Two constants per map, a and b, in
    P(AI) = sigmoid(a * logit(S) + b),     logit clipped at eps = 1e-6
(Platt scaling). One map for the combined score S = w*semantic + (1-w)*frequency
at the production w, one for the semantic score alone (the <224 px passthrough).
No model weight is read or changed: the inputs are the per-image scores that
ml/evaluation/evaluate.py already wrote for the validation split (scenes 99-296,
disjoint from the Synthbuster/RAISE test set). CLAUDE.md section 0 holds.

Light L2 (LogisticRegression C=1.0) because a validation set can be close to
separable and plain maximum likelihood then inflates the slope. The
near-unpenalised fit (C=1e6) is printed next to it so the effect of the
penalty is visible.

HONEST ESTIMATE. Fitting and scoring on the same 396 images flatters the map,
so the AFTER metrics come from 5-fold stratified cross-validated predictions
(fixed seed): each image is scored by a map fitted without it.

PRIMARY METRICS: Brier score and log loss. ECE (equal-count, 10 bins) is
reported but has a noise floor of a few points at n ~ 400.

CERTAINTY BAND (pre-registered at 0.90 before this script was first run): an
image is "confident" iff P(AI) >= band or <= 1 - band. Reported from the CV
predictions: coverage, and the tau-verdict accuracy inside and outside the
band, with Wilson intervals. AC2 (revised PRD M2, agreed 2026-10-08):
tau-verdict accuracy within 'confident' >= 85 % on validation.

THE SEMANTIC-ONLY MAP IS A PROXY. No validation image is below 224 px (the
smallest Synthbuster image is 256^2), so the semantic-only map is fitted on the
semantic scores of full-size images. Tiny uploads may score differently.

Writes ml/outputs/calibration_fit_<stamp>.json and reliability_val_<stamp>.png,
and prints the block to paste into backend/app/shared/config.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.model_selection import StratifiedKFold

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import calibration_metrics as cm  # noqa: E402
from app.m2_analysis import registry  # noqa: E402
from app.shared import config  # noqa: E402

DEFAULT_CSV = REPO_ROOT / "ml" / "outputs" / "sbr_val_20261001T071305Z.csv"
OUTPUT_DIR = REPO_ROOT / "ml" / "outputs"
EPS = 1e-6
P_MIN, P_MAX = 0.01, 0.99
FOLDS = 5
SENSITIVITY_EPS = (1e-6, 1e-9, 1e-12)


def apply_map(score: np.ndarray, a: float, b: float, eps: float = EPS) -> np.ndarray:
    """What the backend shows: the map, then the [1 %, 99 %] cap."""
    return np.clip(cm.sigmoid(a * cm.logit(score, eps) + b), P_MIN, P_MAX)


def cv_predictions(score: np.ndarray, y: np.ndarray, seed: int, eps: float = EPS) -> np.ndarray:
    out = np.empty(len(y))
    for train, test in StratifiedKFold(FOLDS, shuffle=True, random_state=seed).split(score, y):
        a, b, _ = cm.platt_fit(cm.logit(score[train], eps), y[train])
        out[test] = apply_map(score[test], a, b, eps)
    return out


def score_at(p: float, a: float, b: float) -> float:
    """The S the (uncapped) map sends to P(AI) = p."""
    return float(cm.sigmoid((math.log(p / (1 - p)) - b) / a))


def p_at_tau_ci(score: np.ndarray, y: np.ndarray, tau: float, seed: int) -> list[float]:
    """Bootstrap the whole fit (stratified) and read P(AI | S = tau) off each refit."""
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(cm.BOOTSTRAP_RESAMPLES):
        idx = cm.stratified_indices(y, rng)
        a, b, _ = cm.platt_fit(cm.logit(score[idx], EPS), y[idx])
        values.append(float(cm.sigmoid(a * cm.logit(np.array([tau]), EPS)[0] + b)))
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def band_report(p: np.ndarray, score: np.ndarray, y: np.ndarray, tau: float, band: float) -> dict:
    confident = (p >= band) | (p <= 1 - band)
    correct = (score >= tau).astype(int) == y
    n_conf, n_inc = int(confident.sum()), int((~confident).sum())
    k_conf, k_inc = int(correct[confident].sum()), int(correct[~confident].sum())
    return {
        "band": band,
        "coverage": n_conf / len(p), "coverage_ci": cm.wilson(n_conf, len(p)),
        "n_confident": n_conf, "n_inconclusive": n_inc,
        "accuracy_confident": k_conf / n_conf if n_conf else None,
        "accuracy_confident_ci": cm.wilson(k_conf, n_conf),
        "accuracy_inconclusive": k_inc / n_inc if n_inc else None,
        "accuracy_inconclusive_ci": cm.wilson(k_inc, n_inc),
        "confident_real_said_ai": int((confident & (y == 0) & (score >= tau)).sum()),
        "confident_ai_said_real": int((confident & (y == 1) & (score < tau)).sum()),
    }


def fit_map(name: str, score: np.ndarray, y: np.ndarray, tau: float, band: float, seed: int) -> dict:
    x = cm.logit(score, EPS)
    a, b, warns = cm.platt_fit(x, y)
    a_mle, b_mle, warns_mle = cm.platt_fit(x, y, C=1e6)
    p_in = apply_map(score, a, b)
    p_cv = cv_predictions(score, y, seed)
    p_tau = float(cm.sigmoid(a * cm.logit(np.array([tau]), EPS)[0] + b))
    verdict_real = score < tau
    return {
        "map": name, "n": int(len(y)), "eps": EPS,
        "a": a, "b": b, "fit_warnings": warns,
        "near_mle": {"a": a_mle, "b": b_mle, "warnings": warns_mle},
        "before_raw_score": cm.metric_block(np.clip(score, 0, 1), y, seed),
        "after_cv": cm.metric_block(p_cv, y, seed),
        "after_in_sample": cm.metric_block(p_in, y, seed),
        "after_cv_minus_before": cm.paired_difference(p_cv, np.clip(score, 0, 1), y, seed),
        "sanity": {
            "monotonic_increasing": a > 0,
            "p_ai_at_tau": p_tau, "p_ai_at_tau_ci": p_at_tau_ci(score, y, tau, seed), "tau": tau,
            "score_for_p": {str(p): score_at(p, a, b) for p in (0.1, 0.5, 0.9)},
            "real_verdicts_with_p_above_half_in_sample": int((verdict_real & (p_in > 0.5)).sum()),
            "real_verdicts_total": int(verdict_real.sum()),
        },
        "band_cv": band_report(p_cv, score, y, tau, band),
        "band_in_sample": band_report(p_in, score, y, tau, band),
        "reliability_cv": cm.reliability_bins(p_cv, y),
        "reliability_raw": cm.reliability_bins(np.clip(score, 0, 1), y),
        "ref": "platt-" + hashlib.sha256(f"{name},{a!r},{b!r},{EPS!r}".encode()).hexdigest()[:12],
        "_p_cv": p_cv,
    }


def semantic_sensitivity(semantic: np.ndarray, y: np.ndarray) -> dict:
    out = {}
    for eps in SENSITIVITY_EPS:
        at_bound = int(((semantic <= eps) | (semantic >= 1 - eps)).sum())
        a, b, warns = cm.platt_fit(cm.logit(semantic, eps), y)
        out[f"{eps:g}"] = {"n_at_clip_bound": at_bound, "fraction_at_clip_bound": at_bound / len(y),
                           "a": a, "b": b, "warnings": warns}
    return out


def fmt(block: dict) -> str:
    return f"{block['value']:.4f} [{block['ci'][0]:.4f}, {block['ci'][1]:.4f}]"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path, nargs="?", default=DEFAULT_CSV)
    parser.add_argument("--band", type=float, default=0.90, help="pre-registered certainty band (default 0.90)")
    args = parser.parse_args()

    w, tau, seed = config.FUSION_WEIGHT, config.FUSION_TAU, config.SEED
    data = cm.load_scores(args.csv, w)
    y = data["labels"]
    if data["semantic_only"].any():
        raise SystemExit("validation CSV has semantic-only rows; the fused map must be fitted on fused scores only")

    fused = fit_map("fused", data["combined"], y, tau, args.band, seed)
    semantic = fit_map("semantic_only", data["semantic"], y, tau, args.band, seed)
    sensitivity = semantic_sensitivity(data["semantic"], y)

    ac2_band = fused["band_cv"]
    ac2 = {
        "criterion": "tau-verdict accuracy within certainty='confident' >= 0.85 on validation (5-fold CV)",
        "accuracy": ac2_band["accuracy_confident"], "wilson_ci": ac2_band["accuracy_confident_ci"],
        "pass_point_estimate": ac2_band["accuracy_confident"] is not None and ac2_band["accuracy_confident"] >= 0.85,
        "pass_wilson_lower_bound": ac2_band["accuracy_confident_ci"][0] is not None
                                   and ac2_band["accuracy_confident_ci"][0] >= 0.85,
    }

    rel_csv = args.csv.resolve().relative_to(REPO_ROOT).as_posix()
    provenance = {
        "validation_csv": rel_csv,
        "validation_csv_sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
        "files_sha256": cm.files_sha256(data["paths"], y),
        "n_fit": int(len(y)), "n_real": int((y == 0).sum()), "n_fake": int((y == 1).sum()),
        "fit_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fusion_weight": w, "tau": tau, "seed": seed, "folds": FOLDS,
        "semantic_sha256": registry.semantic_weights_digest(),
        "frequency_sha256": config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST,
        "frequency_ai_is_positive": config.DETECTOR_FREQUENCY_AI_IS_POSITIVE,
        "frequency_resize_to": config.DETECTOR_FREQUENCY_RESIZE_TO,
    }
    if provenance["semantic_sha256"] is None:
        raise SystemExit("semantic weights digest unavailable (no HF cache at the pinned revision)")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUTPUT_DIR / f"reliability_val_{stamp}.png"
    cm.reliability_diagram([
        {"title": f"Combined score S (w = {w}), n = {len(y)}",
         "series": [("raw S", np.clip(data["combined"], 0, 1), y), ("P(AI), 5-fold CV", fused["_p_cv"], y)]},
        {"title": f"Semantic score alone (proxy), n = {len(y)}",
         "series": [("raw semantic", data["semantic"], y), ("P(AI), 5-fold CV", semantic["_p_cv"], y)]},
    ], png, "Validation split (scenes 99-296), equal-count bins, Wilson 95 % intervals")

    for m in (fused, semantic):
        m.pop("_p_cv")
    report = {"provenance": provenance, "pre_registered_band": args.band, "p_cap": [P_MIN, P_MAX],
              "fused": fused, "semantic_only": semantic, "semantic_eps_sensitivity": sensitivity,
              "ac2": ac2, "reliability_png": png.relative_to(REPO_ROOT).as_posix(),
              "note": "ECE has a noise floor of a few points at n~400; Brier and log loss are primary."}
    out_json = OUTPUT_DIR / f"calibration_fit_{stamp}.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for m in (fused, semantic):
        s = m["sanity"]
        print(f"\n== {m['map']} map  (n = {m['n']}) ==")
        print(f"a = {m['a']:.6f}  b = {m['b']:.6f}  warnings: {m['fit_warnings'] or 'none'}")
        print(f"near-MLE a = {m['near_mle']['a']:.6f}  b = {m['near_mle']['b']:.6f}")
        for metric in ("brier", "log_loss", "ece_equal_count", "calibration_in_the_large"):
            print(f"  {metric:26s} raw {fmt(m['before_raw_score'][metric])}   CV P(AI) {fmt(m['after_cv'][metric])}"
                  f"   in-sample {fmt(m['after_in_sample'][metric])}")
        for metric in ("brier", "log_loss"):
            print(f"  {metric:26s} CV - raw  {fmt(m['after_cv_minus_before'][metric])}")
        print(f"  monotonic: {s['monotonic_increasing']}   P(AI | S = tau {tau}) = {s['p_ai_at_tau']:.4f} "
              f"[{s['p_ai_at_tau_ci'][0]:.4f}, {s['p_ai_at_tau_ci'][1]:.4f}]")
        print("  S giving P = 0.1 / 0.5 / 0.9: " + " / ".join(f"{v:.4g}" for v in s["score_for_p"].values()))
        print(f"  Real verdicts with P(AI) > 0.5 (in-sample): {s['real_verdicts_with_p_above_half_in_sample']}"
              f" of {s['real_verdicts_total']}")
        for kind in ("band_cv", "band_in_sample"):
            bd = m[kind]
            acc = lambda v, ci: "n/a" if v is None else f"{v:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"  # noqa: E731
            print(f"  {kind:15s} coverage {bd['coverage']:.3f} [{bd['coverage_ci'][0]:.3f}, {bd['coverage_ci'][1]:.3f}]"
                  f" ({bd['n_confident']}/{bd['n_confident'] + bd['n_inconclusive']})"
                  f"  acc confident {acc(bd['accuracy_confident'], bd['accuracy_confident_ci'])}"
                  f"  acc inconclusive {acc(bd['accuracy_inconclusive'], bd['accuracy_inconclusive_ci'])}")
    print("\n== semantic-only eps sensitivity ==")
    for eps, v in sensitivity.items():
        print(f"  eps {eps:>6}: at clip bound {v['n_at_clip_bound']} ({v['fraction_at_clip_bound']:.3f})"
              f"  a = {v['a']:.6f}  b = {v['b']:.6f}")
    print(f"\nAC2: accuracy within confident = {ac2['accuracy']:.4f} "
          f"[{ac2['wilson_ci'][0]:.4f}, {ac2['wilson_ci'][1]:.4f}]  "
          f"pass (point) {ac2['pass_point_estimate']}  pass (Wilson lower) {ac2['pass_wilson_lower_bound']}")
    print(f"\nwrote {out_json.relative_to(REPO_ROOT)} and {png.relative_to(REPO_ROOT)}")

    print("\n# ---- paste into backend/app/shared/config.py ----")
    p = provenance
    print(f'CALIBRATION_FIT_SOURCE = "{p["validation_csv"]}"')
    print(f'CALIBRATION_FIT_FILES_SHA256 = "{p["files_sha256"]}"')
    print(f'CALIBRATION_FIT_N = {p["n_fit"]}')
    print(f'CALIBRATION_FIT_DATE = "{p["fit_date"]}"')
    print(f'CALIBRATION_FIT_WEIGHT = {p["fusion_weight"]!r}')
    print(f'CALIBRATION_FIT_SEMANTIC_SHA256 = "{p["semantic_sha256"]}"')
    print(f'CALIBRATION_FIT_FREQUENCY_SHA256 = "{p["frequency_sha256"]}"')
    print(f'CALIBRATION_FIT_FREQUENCY_AI_IS_POSITIVE = {p["frequency_ai_is_positive"]!r}')
    print(f'CALIBRATION_FIT_FREQUENCY_RESIZE_TO = {p["frequency_resize_to"]!r}')
    print(f'CALIBRATION_FUSED_A = {fused["a"]!r}')
    print(f'CALIBRATION_FUSED_B = {fused["b"]!r}')
    print(f'CALIBRATION_FUSED_REF = "{fused["ref"]}"')
    print(f'CALIBRATION_SEMANTIC_ONLY_A = {semantic["a"]!r}')
    print(f'CALIBRATION_SEMANTIC_ONLY_B = {semantic["b"]!r}')
    print(f'CALIBRATION_SEMANTIC_ONLY_REF = "{semantic["ref"]}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
