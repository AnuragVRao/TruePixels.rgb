"""The startup warm-up: loads both branches, and never blocks startup."""

from __future__ import annotations

import pytest

from app.m2_analysis import detectors, frequency_detector, warmup
from app.shared import config


def test_a_failing_branch_does_not_stop_the_warm_up(monkeypatch):
    """A branch that cannot load is reported, not raised: the server still starts."""
    def broken(*_args, **_kwargs):
        raise RuntimeError("checkpoint unavailable")

    calls = []
    monkeypatch.setattr(detectors.primary, "score", broken)
    monkeypatch.setattr(frequency_detector.frequency, "score",
                        lambda path, **_: calls.append(path))
    timings = warmup.warm_up()
    assert timings["semantic"] == "failed: checkpoint unavailable"
    if config.DETECTOR_FREQUENCY_ENABLED:
        assert isinstance(timings["frequency"], float) and len(calls) == 1


def test_each_enabled_branch_gets_one_forward_pass(monkeypatch):
    seen = {}
    monkeypatch.setattr(detectors.primary, "score", lambda path, **_: seen.setdefault("semantic", path))
    monkeypatch.setattr(frequency_detector.frequency, "score",
                        lambda path, **_: seen.setdefault("frequency", path))
    warmup.warm_up()
    expected = {"semantic", "frequency"} if config.DETECTOR_FREQUENCY_ENABLED else {"semantic"}
    assert set(seen) == expected
    assert len(set(seen.values())) == 1  # the same synthetic image for both


@pytest.mark.slow
def test_warm_up_leaves_both_branches_resident():
    if not frequency_detector.frequency.present_on_disk:
        pytest.skip("SPAI weights not present; see CLAUDE.md section 4")
    timings = warmup.warm_up()
    assert all(isinstance(v, float) for v in timings.values()), timings
    assert detectors.primary.is_loaded
    assert frequency_detector.frequency.is_loaded or not config.DETECTOR_FREQUENCY_ENABLED
