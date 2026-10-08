"""The displayed P(AI) and its certainty label (app/m2_analysis/calibration.py).

P(AI) is shown for BOTH verdicts and never decides one: the verdict stays
"AI iff S >= tau". These tests pin the map's shape (monotonic, capped, finite
at the ends), the separate semantic-only map, the prior, the certainty band,
and the rule that a map is used only with the configuration it was fitted on.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from app.m2_analysis import calibration, fusion, registry
from app.shared import config

GRID = [i / 200 for i in range(201)]


@pytest.fixture
def fitted_set():
    """The published baseline with the hashes the map was fitted on."""
    base = registry.baseline()
    return replace(
        base,
        primary=replace(base.primary, artifact_sha256=config.CALIBRATION_FIT_SEMANTIC_SHA256),
        frequency_detector=replace(base.frequency_detector,
                                   artifact_sha256=config.CALIBRATION_FIT_FREQUENCY_SHA256),
    )


@pytest.mark.parametrize("semantic_only", [False, True])
def test_monotonic_in_the_score(semantic_only):
    values = [calibration.p_ai(s, semantic_only=semantic_only) for s in GRID]
    assert all(b >= a for a, b in zip(values, values[1:]))
    assert values[-1] > values[0]


@pytest.mark.parametrize("semantic_only", [False, True])
@pytest.mark.parametrize("score", [0.0, 1e-300, 1e-12, 0.5, 1 - 1e-12, 1.0])
def test_output_is_finite_and_within_the_cap(score, semantic_only):
    p = calibration.p_ai(score, semantic_only=semantic_only)
    assert math.isfinite(p)
    assert config.CALIBRATION_P_MIN <= p <= config.CALIBRATION_P_MAX


def test_the_cap_is_reached_by_the_fused_map_at_both_ends():
    assert calibration.p_ai(0.0, semantic_only=False) == config.CALIBRATION_P_MIN
    assert calibration.p_ai(1.0, semantic_only=False) == config.CALIBRATION_P_MAX


def test_the_fused_map_is_the_fitted_formula():
    s = 0.52
    logit = math.log(s / (1 - s))
    expected = 1 / (1 + math.exp(-(config.CALIBRATION_FUSED_A * logit + config.CALIBRATION_FUSED_B)))
    assert calibration.p_ai(s, semantic_only=False) == pytest.approx(expected, abs=1e-12)


def test_semantic_only_uses_its_own_constants(monkeypatch):
    before_fused = calibration.p_ai(0.8, semantic_only=False)
    monkeypatch.setattr(config, "CALIBRATION_SEMANTIC_ONLY_A", 1.0)
    monkeypatch.setattr(config, "CALIBRATION_SEMANTIC_ONLY_B", 0.0)
    assert calibration.p_ai(0.8, semantic_only=True) == pytest.approx(0.8)
    assert calibration.p_ai(0.8, semantic_only=False) == before_fused


def test_the_semantic_only_map_differs_from_the_fused_map():
    assert calibration.p_ai(0.95, semantic_only=True) != pytest.approx(
        calibration.p_ai(0.95, semantic_only=False))


def test_prior_of_one_half_is_a_no_op():
    for s in (0.05, 0.5, 0.7558, 0.95):
        assert calibration.p_ai(s, semantic_only=False, prior=0.5) == calibration.p_ai(s, semantic_only=False)


def test_prior_shifts_the_logit_by_the_prior_log_odds():
    s, prior = 0.6, 0.2
    base = calibration.p_ai(s, semantic_only=False)
    shifted = calibration.p_ai(s, semantic_only=False, prior=prior)
    delta = math.log(shifted / (1 - shifted)) - math.log(base / (1 - base))
    assert delta == pytest.approx(math.log(prior / (1 - prior)))


@pytest.mark.parametrize("prior", [0.0, 1.0, -0.1])
def test_impossible_priors_are_refused(prior):
    with pytest.raises(ValueError):
        calibration.p_ai(0.5, semantic_only=False, prior=prior)


def test_certainty_boundaries_are_inclusive_and_read_from_config(monkeypatch):
    band = config.CERTAINTY_CONFIDENT_P
    assert calibration.certainty(band) == "confident"
    assert calibration.certainty(1 - band) == "confident"
    assert calibration.certainty(band - 1e-9) == "inconclusive"
    assert calibration.certainty(1 - band + 1e-9) == "inconclusive"
    monkeypatch.setattr(config, "CERTAINTY_CONFIDENT_P", 0.95)
    assert calibration.certainty(0.92) == "inconclusive"


def test_the_semantic_only_map_is_confident_only_at_the_extremes():
    """The map is so flat that 'confident' needs a semantic score <= ~6e-5 or >= ~0.9999.

    No validation image came that close (range 0.0032 - 0.9997), so in practice
    a semantic-only result is inconclusive.
    """
    for s in [i / 1000 for i in range(1, 1000)] + [0.0032, 0.9997]:
        assert calibration.certainty(calibration.p_ai(s, semantic_only=True)) == "inconclusive"
    assert calibration.certainty(calibration.p_ai(1.0, semantic_only=True)) == "confident"
    assert calibration.certainty(calibration.p_ai(0.0, semantic_only=True)) == "confident"


def test_the_fitted_configuration_is_calibrated(fitted_set):
    out = calibration.calibrated(fitted_set, 0.9, semantic_only=False)
    assert out.p_ai == calibration.p_ai(0.9, semantic_only=False)
    assert out.certainty == calibration.certainty(out.p_ai)
    assert out.ref == config.CALIBRATION_FUSED_REF
    assert calibration.calibrated(fitted_set, 0.9, semantic_only=True).ref == config.CALIBRATION_SEMANTIC_ONLY_REF


@pytest.mark.parametrize("change", [
    "weight", "semantic_hash", "frequency_hash", "missing_semantic_hash", "missing_frequency_hash",
    "sign", "resize", "no_frequency_branch",
])
def test_any_other_configuration_gets_null_not_a_stale_number(fitted_set, change):
    m = fitted_set
    if change == "weight":
        m = replace(m, fusion=replace(m.fusion, weight=0.5))
    elif change == "semantic_hash":
        m = replace(m, primary=replace(m.primary, artifact_sha256="0" * 64))
    elif change == "missing_semantic_hash":
        m = replace(m, primary=replace(m.primary, artifact_sha256=None))
    elif change == "frequency_hash":
        m = replace(m, frequency_detector=replace(m.frequency_detector, artifact_sha256="0" * 64))
    elif change == "missing_frequency_hash":
        m = replace(m, frequency_detector=replace(m.frequency_detector, artifact_sha256=None))
    elif change == "sign":
        m = replace(m, frequency_detector=replace(m.frequency_detector, ai_is_positive=False))
    elif change == "resize":
        m = replace(m, frequency_detector=replace(m.frequency_detector, resize_to=1024))
    elif change == "no_frequency_branch":
        m = replace(m, frequency_detector=None)
    assert calibration.calibrated(m, 0.9, semantic_only=False) == calibration.NOT_CALIBRATED


def test_semantic_only_map_checks_only_the_semantic_hash(fitted_set):
    other = replace(fitted_set, fusion=replace(fitted_set.fusion, weight=0.5),
                    frequency_detector=replace(fitted_set.frequency_detector, artifact_sha256="0" * 64))
    assert calibration.calibrated(other, 0.9, semantic_only=True).p_ai is not None
    no_sem = replace(fitted_set, primary=replace(fitted_set.primary, artifact_sha256="0" * 64))
    assert calibration.calibrated(no_sem, 0.9, semantic_only=True) == calibration.NOT_CALIBRATED


def test_weight_is_compared_with_a_float_tolerance(fitted_set):
    nudged = replace(fitted_set, fusion=replace(fitted_set.fusion, weight=config.CALIBRATION_FIT_WEIGHT + 1e-12))
    assert calibration.calibrated(nudged, 0.9, semantic_only=False).p_ai is not None


def test_the_verdict_does_not_depend_on_the_map(fitted_set):
    """The verdict is fusion's 'S >= tau' alone, on a grid around tau."""
    tau = fitted_set.fusion.tau
    for s in GRID + [tau - 1e-9, tau, tau + 1e-9]:
        _, predicted, *_ = fusion.combine(s, s, fitted_set.fusion)
        assert predicted == ("AI Generated" if s >= tau else "Real")


def test_p_ai_at_tau_is_above_one_half():
    """tau holds FPR <= 10 %, so it sits above even odds: P(AI | S = tau) = 0.70 on validation."""
    assert calibration.p_ai(config.FUSION_TAU, semantic_only=False) == pytest.approx(0.6957, abs=1e-3)
