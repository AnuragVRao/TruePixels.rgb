"""PRD2 section 13.1 - fusion arithmetic and the confidence inversion.

The inversion gets its own dedicated test because PRD2 FR-04 names it the
single most likely integration bug in the project, and because it fails
quietly: a confidently-real image displayed at 8% confidence looks like a weak
model, not like a wiring error.
"""

from __future__ import annotations

import pytest

from app.m2_analysis.fusion import combine
from app.m2_analysis.registry import FusionModelConfig


def config(tau: float = 0.5, weight: float = 0.5, temperature: float = 1.0):
    return FusionModelConfig(
        model_id=None,
        strategy="weighted_average",
        weight=weight,
        tau=tau,
        temperature=temperature,
    )


def test_confidence_inversion_for_a_confidently_real_image():
    """PRD2 section 8.3, stated verbatim: 0.08 must yield ("Real", 0.92)."""
    fusion_score, predicted_class, confidence = combine(0.08, 0.08, config())

    assert fusion_score == pytest.approx(0.08)
    assert predicted_class == "Real"
    assert confidence == pytest.approx(0.92)


def test_confidence_is_the_fused_score_when_the_class_is_ai_generated():
    fusion_score, predicted_class, confidence = combine(0.9, 0.9, config())

    assert predicted_class == "AI Generated"
    assert confidence == pytest.approx(fusion_score)
    assert confidence == pytest.approx(0.9)


def test_threshold_boundary_resolves_to_ai_generated():
    """FR-04 uses >=, so a score exactly at tau is 'AI Generated'."""
    _, predicted_class, confidence = combine(0.5, 0.5, config(tau=0.5))

    assert predicted_class == "AI Generated"
    assert confidence == pytest.approx(0.5)


def test_tau_is_honoured_rather_than_hard_coded_at_half():
    """tau is selected on validation to hold FPR <= MM2.6; it is not always 0.5."""
    _, at_default, _ = combine(0.6, 0.6, config(tau=0.5))
    _, at_strict, _ = combine(0.6, 0.6, config(tau=0.7))

    assert at_default == "AI Generated"
    assert at_strict == "Real"


@pytest.mark.parametrize("semantic", [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("frequency", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_grid_of_branch_pairs_including_the_boundaries(semantic, frequency):
    """Every combination stays in range and obeys the inversion rule."""
    fusion_score, predicted_class, confidence = combine(
        semantic, frequency, config()
    )

    assert 0.0 <= fusion_score <= 1.0
    assert 0.0 <= confidence <= 1.0
    assert predicted_class in {"Real", "AI Generated"}

    if predicted_class == "AI Generated":
        assert confidence == pytest.approx(fusion_score)
    else:
        assert confidence == pytest.approx(1.0 - fusion_score)

    # Confidence in the predicted class can never be below the coin flip.
    assert confidence >= 0.5 - 1e-9


def test_weighted_average_respects_the_weight():
    """Strategy A: fusion = w * semantic + (1 - w) * frequency."""
    fusion_score, _, _ = combine(1.0, 0.0, config(weight=0.75))
    assert fusion_score == pytest.approx(0.75)

    fusion_score, _, _ = combine(0.0, 1.0, config(weight=0.75))
    assert fusion_score == pytest.approx(0.25)


def test_missing_frequency_score_is_a_passthrough_not_an_average_with_zero():
    """With the frequency branch disabled, the semantic score IS the verdict.

    Treating None as 0.0 would silently halve every score; treating it as 0.5
    would invent an opinion. Neither is acceptable.
    """
    fusion_score, predicted_class, confidence = combine(0.9, None, config())

    assert fusion_score == pytest.approx(0.9)
    assert predicted_class == "AI Generated"
    assert confidence == pytest.approx(0.9)

    fusion_score, predicted_class, confidence = combine(0.1, None, config())

    assert fusion_score == pytest.approx(0.1)
    assert predicted_class == "Real"
    assert confidence == pytest.approx(0.9)


def test_temperature_of_one_is_a_no_op():
    fusion_score, _, _ = combine(0.3, 0.7, config(temperature=1.0))
    assert fusion_score == pytest.approx(0.5)


def test_temperature_above_one_softens_confidence():
    """Higher T pulls probabilities toward 0.5 - the point of calibration."""
    raw, _, _ = combine(0.95, 0.95, config(temperature=1.0))
    softened, _, _ = combine(0.95, 0.95, config(temperature=2.0))

    assert 0.5 < softened < raw
