"""Label resolution for pretrained Hugging Face detectors.

The single most important test in this module is the one asserting that the
AI-class index is read from each checkpoint's own labels. Real checkpoints do
not agree on the ordering:

    prithivMLmods/AIorNot-SigLIP2      {0: "Real",       1: "AI"}     -> 1
    Organika/sdxl-detector            {0: "artificial", 1: "human"}  -> 0

Hard-coding either index would invert a checkpoint of the other kind while
still returning plausible-looking probabilities. Nothing downstream would
catch it - the same quiet-failure shape as the confidence inversion. The
second checkpoint is no longer in use; it stays in this table because it is
the evidence that the hazard is real.
"""

from __future__ import annotations

import pytest

from app.m2_analysis.detectors import resolve_ai_index
from app.shared.contracts.errors import ModelUnavailableError


# The exact id2label maps published by each checkpoint, verified against the
# Hugging Face API. If an upstream checkpoint ever changes its labels, this is
# where it should break.
AIORNOT_SIGLIP2 = {0: "Real", 1: "AI"}
ORGANIKA_SDXL = {0: "artificial", 1: "human"}
ATEEQQ_AI_VS_HUMAN = {0: "ai", 1: "hum"}


@pytest.mark.parametrize(
    ("id2label", "expected", "checkpoint"),
    [
        (AIORNOT_SIGLIP2, 1, "prithivMLmods/AIorNot-SigLIP2"),
        (ORGANIKA_SDXL, 0, "Organika/sdxl-detector"),
        (ATEEQQ_AI_VS_HUMAN, 0, "Ateeqq/ai-vs-human-image-detector"),
    ],
)
def test_ai_index_is_resolved_from_real_checkpoint_labels(
    id2label, expected, checkpoint
):
    """Real checkpoints disagree on index order; every one must resolve."""
    assert resolve_ai_index(id2label) == expected, (
        f"{checkpoint} resolved to the wrong index - every prediction from "
        "this detector would be inverted"
    )


def test_real_checkpoints_genuinely_disagree_on_index():
    """Guards the premise. If this ever fails, the hazard has gone away."""
    assert resolve_ai_index(AIORNOT_SIGLIP2) != resolve_ai_index(ORGANIKA_SDXL)


def test_labels_are_matched_case_and_separator_insensitively():
    assert resolve_ai_index({0: "REAL", 1: "AI_Generated"}) == 1
    assert resolve_ai_index({0: "Fake", 1: "Authentic"}) == 0
    assert resolve_ai_index({0: "human", 1: "synthetic"}) == 1


def test_string_keys_are_accepted():
    """HF configs round-trip through JSON, so indices arrive as strings."""
    assert resolve_ai_index({"0": "Real", "1": "AI"}) == 1


@pytest.mark.parametrize(
    ("id2label", "reason"),
    [
        ({0: "cat", 1: "dog"}, "neither label is about AI or real"),
        ({0: "LABEL_0", 1: "LABEL_1"}, "unlabelled checkpoint"),
        ({0: "ai", 1: "fake"}, "two AI labels, no real label"),
        ({0: "real", 1: "human"}, "two real labels, no AI label"),
        ({0: "ai", 1: "real", 2: "fake"}, "three classes, ambiguous"),
        ({0: "ai"}, "single class"),
    ],
)
def test_unresolvable_labels_raise_rather_than_guess(id2label, reason):
    """Refusing to guess is the whole point - a wrong guess is invisible."""
    with pytest.raises(ModelUnavailableError):
        resolve_ai_index(id2label)


def test_the_error_names_the_labels_it_could_not_resolve():
    """An operator swapping in a new checkpoint needs to see why it failed."""
    with pytest.raises(ModelUnavailableError, match="cat"):
        resolve_ai_index({0: "cat", 1: "dog"})


def test_three_class_deepfake_style_checkpoint_is_rejected():
    """PRD2 constraint C.2 is binary only.

    Checkpoints like AI-vs-Deepfake-vs-Real exist and are tempting, but they
    do not fit a binary contract. Rejecting them here is better than silently
    collapsing a class.
    """
    with pytest.raises(ModelUnavailableError):
        resolve_ai_index({0: "AI", 1: "Deepfake", 2: "Real"})
