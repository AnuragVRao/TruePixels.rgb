"""Calibration metrics shared by fit_calibration.py and evaluate_calibration.py.

Everything here scores a column of P(AI) against 0/1 labels. Nothing fits
anything except ``platt_fit`` (two constants on logit(S); no model weight is
touched - CLAUDE.md section 0) and ``diagnostic_refit`` (reported, never applied).

Primary metrics are Brier score and log loss. ECE is reported too, but at
n ~ 400 an equal-count 10-bin ECE has a noise floor of a few points even for a
perfectly calibrated score (each bin holds ~40 images, so the observed
fraction in a bin has a standard error of up to ~0.08), so small ECE
differences are not evidence of anything.
"""

from __future__ import annotations

import csv
import hashlib
import math
import warnings
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

BOOTSTRAP_RESAMPLES = 2000
ECE_BINS = 10
Z95 = 1.959963985


def logit(p: np.ndarray, eps: float) -> np.ndarray:
    clipped = np.clip(np.asarray(p, dtype=float), eps, 1.0 - eps)
    return np.log(clipped / (1.0 - clipped))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def load_scores(csv_path: Path, weight: float) -> dict:
    """Per-image labels and scores from an evaluate.py CSV.

    The combined score is RECOMPUTED as w*semantic + (1-w)*frequency from the
    stored branch scores, so a CSV written at another fusion weight can be read
    at the current one. Rows without a frequency score are semantic-only: their
    combined score is the semantic score (the production passthrough).
    """
    paths, labels, semantic, frequency = [], [], [], []
    with csv_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            paths.append(row["path"].replace("\\", "/"))
            labels.append(int(row["label"]))
            semantic.append(float(row["semantic"]))
            frequency.append(float(row["frequency"]) if row["frequency"] else math.nan)
    s, f = np.array(semantic), np.array(frequency)
    semantic_only = np.isnan(f)
    combined = np.where(semantic_only, s, weight * s + (1.0 - weight) * np.nan_to_num(f))
    return {"paths": paths, "labels": np.array(labels), "semantic": s, "frequency": f,
            "combined": combined, "semantic_only": semantic_only}


def files_sha256(paths: list[str], labels: np.ndarray) -> str:
    """SHA-256 of the sorted 'relative/path,label' lines - OS-independent ('/' separators)."""
    lines = sorted(f"{p.replace(chr(92), '/')},{int(l)}" for p, l in zip(paths, labels))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(p: np.ndarray, y: np.ndarray, eps: float = 1e-6) -> float:
    return float(log_loss(y, np.clip(p, eps, 1 - eps), labels=[0, 1]))


def ece_equal_count(p: np.ndarray, y: np.ndarray, bins: int = ECE_BINS) -> float:
    """ECE on P(AI) itself (not top-label), equal-count bins."""
    order = np.argsort(p, kind="stable")
    return float(sum(len(b) / len(p) * abs(p[b].mean() - y[b].mean())
                     for b in np.array_split(order, bins) if len(b)))


def calibration_in_the_large(p: np.ndarray, y: np.ndarray) -> float:
    """Mean predicted P(AI) minus the observed AI fraction (0 = right on average)."""
    return float(np.mean(p) - np.mean(y))


def reliability_bins(p: np.ndarray, y: np.ndarray, bins: int = ECE_BINS) -> list[dict]:
    order = np.argsort(p, kind="stable")
    out = []
    for b in np.array_split(order, bins):
        if len(b):
            k = int(y[b].sum())
            out.append({"n": len(b), "mean_p": float(p[b].mean()), "frac_ai": k / len(b),
                        "frac_ai_ci": wilson(k, len(b))})
    return out


def wilson(successes: int, total: int, z: float = Z95) -> list[float | None]:
    """95% Wilson score interval (same as ml/evaluation/evaluate.py)."""
    if total == 0:
        return [None, None]
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return [float(max(0.0, centre - spread)), float(min(1.0, centre + spread))]


def stratified_indices(y: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    return np.concatenate([rng.choice(pos, len(pos), replace=True),
                           rng.choice(neg, len(neg), replace=True)])


def bootstrap_ci(fn, arrays: tuple, y: np.ndarray, seed: int,
                 resamples: int = BOOTSTRAP_RESAMPLES) -> list[float]:
    """95% percentile bootstrap of fn(*arrays_resampled, y_resampled), stratified by class."""
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(resamples):
        idx = stratified_indices(y, rng)
        values.append(fn(*(a[idx] for a in arrays), y[idx]))
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def metric_block(p: np.ndarray, y: np.ndarray, seed: int) -> dict:
    """Brier, log loss, ECE and calibration-in-the-large, each with a bootstrap CI."""
    out = {}
    for name, fn in (("brier", brier), ("log_loss", logloss), ("ece_equal_count", ece_equal_count),
                     ("calibration_in_the_large", calibration_in_the_large)):
        out[name] = {"value": fn(p, y), "ci": bootstrap_ci(fn, (p,), y, seed)}
    return out


def paired_difference(p_after: np.ndarray, p_before: np.ndarray, y: np.ndarray, seed: int) -> dict:
    """AFTER minus BEFORE for Brier and log loss, with a paired bootstrap CI (negative = better)."""
    out = {}
    for name, fn in (("brier", brier), ("log_loss", logloss)):
        diff = lambda a, b, yy, fn=fn: fn(a, yy) - fn(b, yy)  # noqa: E731
        out[name] = {"value": diff(p_after, p_before, y),
                     "ci": bootstrap_ci(diff, (p_after, p_before), y, seed)}
    return out


# --------------------------------------------------------------------------
# Fitting (two constants; never a model weight)
# --------------------------------------------------------------------------

def platt_fit(x: np.ndarray, y: np.ndarray, C: float = 1.0) -> tuple[float, float, list[str]]:
    """Fit P(AI) = sigmoid(a*x + b) with light L2 (C=1.0). Returns (a, b, warnings)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = LogisticRegression(C=C, max_iter=1000).fit(x.reshape(-1, 1), y)
    return float(model.coef_[0, 0]), float(model.intercept_[0]), [str(w.message) for w in caught]


def diagnostic_refit(p: np.ndarray, y: np.ndarray, eps: float = 1e-6) -> dict:
    """Calibration slope and intercept: refit y ~ sigmoid(slope*logit(p) + intercept).

    Slope 1 / intercept 0 means p is calibrated on this data. DIAGNOSTIC ONLY -
    the result is reported and never applied (applying it would be fitting on
    the set being evaluated). Near-unpenalised (C=1e6).
    """
    a, b, warns = platt_fit(logit(p, eps), y, C=1e6)
    return {"slope": a, "intercept": b, "warnings": warns}


# --------------------------------------------------------------------------
# Reliability diagram
# --------------------------------------------------------------------------

SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ("#2a78d6", "#eb6834")  # categorical slots 1 and 2 (dataviz reference palette)
MARKERS = ("o", "s")


def reliability_diagram(panels: list[dict], path: Path, title: str) -> None:
    """One panel per map; each panel overlays up to two series (before / after).

    panels: [{"title": str, "series": [(label, p, y), ...]}]. Equal-count bins,
    Wilson 95% intervals on the observed fraction.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 5.2), squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, panel in zip(axes[0], panels):
        ax.set_facecolor(SURFACE)
        ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1, linestyle="--", label="perfect calibration")
        for i, (label, p, y) in enumerate(panel["series"]):
            bins = reliability_bins(p, y)
            xs = [b["mean_p"] for b in bins]
            ys = [b["frac_ai"] for b in bins]
            lo = [b["frac_ai"] - b["frac_ai_ci"][0] for b in bins]
            hi = [b["frac_ai_ci"][1] - b["frac_ai"] for b in bins]
            ax.errorbar(xs, ys, yerr=[lo, hi], color=SERIES[i], marker=MARKERS[i], markersize=6,
                        linewidth=2, elinewidth=1, capsize=2, label=label)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.set_xlabel("mean predicted P(AI) in bin", color=MUTED)
        ax.set_ylabel("observed fraction AI-generated", color=MUTED)
        ax.set_title(panel["title"], color=INK, fontsize=11)
        ax.grid(color=GRID, linewidth=0.6)
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.tick_params(colors=MUTED)
        ax.legend(frameon=False, fontsize=8, loc="upper left", labelcolor=INK)
    fig.suptitle(title, color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
