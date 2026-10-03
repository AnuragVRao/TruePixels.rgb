"""The startup warm-up: loads both branches, and never blocks startup."""

from __future__ import annotations

import pytest

from app.m2_analysis import detectors, frequency_detector, warmup
from app.shared import config


@pytest.fixture(autouse=True)
def _restore_warmup_state():
    """STATE is process-global; leave it as each test found it."""
    saved = {"status": warmup.STATE["status"], "branches": dict(warmup.STATE["branches"])}
    yield
    warmup.STATE.update(saved)


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


# --------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------

def _client():
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)  # no context manager: lifespan (and the real warm-up) not run


def test_ready_is_503_and_failure_is_loud_when_warm_up_fails(monkeypatch, caplog):
    import logging

    from app.shared import logging as audit

    audited = []
    monkeypatch.setattr(audit, "emit", lambda *a, **k: audited.append((a, k)))

    def broken(*_args, **_kwargs):
        raise RuntimeError("checkpoint unavailable")

    monkeypatch.setattr(detectors.primary, "score", broken)
    monkeypatch.setattr(frequency_detector.frequency, "score", lambda path, **_: None)
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        warmup.warm_up()

    assert warmup.STATE["status"] == "failed"
    assert any(r.levelno == logging.ERROR and "semantic" in r.getMessage() for r in caplog.records)
    assert audited and audited[0][0][0] == "error" and audited[0][1]["severity"] == "error"
    response = _client().get("/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False and response.json()["warmup"] == "failed"
    assert _client().get("/health").json()["ready"] is False


def test_ready_is_200_after_a_successful_warm_up(monkeypatch):
    monkeypatch.setattr(detectors.primary, "score", lambda path, **_: None)
    monkeypatch.setattr(frequency_detector.frequency, "score", lambda path, **_: None)
    warmup.warm_up()
    response = _client().get("/ready")
    assert response.status_code == 200 and response.json()["warmup"] == "ok"


def test_ready_when_warm_up_is_disabled_by_configuration():
    warmup.mark_disabled()
    response = _client().get("/ready")
    assert response.status_code == 200 and response.json()["warmup"] == "disabled"
