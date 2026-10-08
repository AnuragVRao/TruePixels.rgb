"""PRD2 section 13.1 - fusion arithmetic and the verdict.

Since C2 v2 (2026-10-08) fusion decides the VERDICT only: (fusion_score,
predicted_class). The number shown beside it is P(AI) for either verdict,
from calibration.py - tested in test_calibration.py. The old "confidence in
the predicted class" survives only as ``legacy_confidence_score``, filling
D4's legacy column until the migration that drops it.
"""

from __future__ import annotations

import pytest

from app.m2_analysis import fusion
from app.m2_analysis.fusion import combine, legacy_confidence_score
from app.m2_analysis.registry import FusionModelConfig

OPERATING_TAU = 0.7558  # the active operating point


def config(tau: float = 0.5, weight: float = 0.5, temperature: float = 1.0):
    return FusionModelConfig(
        model_id=None,
        strategy="weighted_average",
        weight=weight,
        tau=tau,
        temperature=temperature,
    )


def test_combine_returns_the_score_and_the_verdict_only():
    out = combine(0.08, 0.08, config())
    assert len(out) == 2
    assert out[0] == pytest.approx(0.08)
    assert out[1] == "Real"


def test_threshold_boundary_resolves_to_ai_generated():
    """FR-04 uses >=, so a score exactly at tau is 'AI Generated'."""
    _, predicted_class = combine(0.5, 0.5, config(tau=0.5))
    assert predicted_class == "AI Generated"


def test_tau_is_honoured_rather_than_hard_coded_at_half():
    """tau is selected on validation to hold FPR <= MM2.6; it is not always 0.5."""
    _, at_default = combine(0.6, 0.6, config(tau=0.5))
    _, at_strict = combine(0.6, 0.6, config(tau=0.7))

    assert at_default == "AI Generated"
    assert at_strict == "Real"


@pytest.mark.parametrize("semantic", [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("frequency", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_grid_of_branch_pairs_including_the_boundaries(semantic, frequency):
    fusion_score, predicted_class = combine(semantic, frequency, config(tau=OPERATING_TAU, weight=0.25))

    assert 0.0 <= fusion_score <= 1.0
    assert predicted_class == ("AI Generated" if fusion_score >= OPERATING_TAU else "Real")


def test_weighted_average_respects_the_weight():
    """Strategy A: fusion = w * semantic + (1 - w) * frequency."""
    fusion_score, _ = combine(1.0, 0.0, config(weight=0.75))
    assert fusion_score == pytest.approx(0.75)

    fusion_score, _ = combine(0.0, 1.0, config(weight=0.75))
    assert fusion_score == pytest.approx(0.25)


def test_missing_frequency_score_is_a_passthrough_not_an_average_with_zero():
    """With no frequency score, the semantic score IS the combined score.

    Treating None as 0.0 would silently scale every score down; treating it as
    0.5 would invent an opinion. Neither is acceptable.
    """
    assert combine(0.9, None, config()) == (pytest.approx(0.9), "AI Generated")
    assert combine(0.1, None, config()) == (pytest.approx(0.1), "Real")


def test_temperature_of_one_is_a_no_op():
    fusion_score, _ = combine(0.3, 0.7, config(temperature=1.0))
    assert fusion_score == pytest.approx(0.5)


def test_temperature_above_one_softens_the_score():
    raw, _ = combine(0.95, 0.95, config(temperature=1.0))
    softened, _ = combine(0.95, 0.95, config(temperature=2.0))

    assert 0.5 < softened < raw


def test_the_old_confidence_is_gone_from_the_public_path():
    """C2 v2: no confidence in the predicted class anywhere a user can see it."""
    assert not hasattr(fusion, "confidence_in_prediction")
    from app.shared.contracts.c2 import InferenceOutput
    from app.m2_analysis.schemas import PredictionResponse

    assert "confidence_score" not in InferenceOutput.model_fields
    assert "confidence_score" not in PredictionResponse.model_fields
    assert {"p_ai", "certainty"} <= set(PredictionResponse.model_fields)


@pytest.mark.parametrize("score", [0.0, 0.3, 0.52, OPERATING_TAU, 0.9, 1.0])
def test_legacy_confidence_still_fills_d4_until_the_column_is_dropped(score):
    """DEPRECATED path, pinned so the legacy D4 column keeps its 0004 meaning meanwhile."""
    _, predicted = combine(score, score, config(tau=OPERATING_TAU))
    legacy = legacy_confidence_score(score, OPERATING_TAU, predicted)
    assert 0.5 <= legacy <= 1.0
    if score == OPERATING_TAU:
        assert legacy == pytest.approx(0.5)
