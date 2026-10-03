"""D6 audit rows are really written - and a swallowed write fails the test.

emit_log never raises (a logging fault must not fail a request), which also
meant a broken log write could pass every test unnoticed: the model-backed
suite wrote no D6 rows at all, because its logger pointed at a database
without a ``logs`` table. These tests point the logger at the same database
as the request and use ``strict_audit_log``, so a failed write is a failed
test.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.m2_analysis.models import ModelRegistry, Prediction
from app.m3_results import logging_service
from app.m3_results.models import Explainability, LogEntry
from app.main import app
from app.shared import config
from app.shared.db import SessionLocal
from app.shared.logging import emit
from conftest import assert_no_swallowed_log_writes, make_image, png_bytes

client = TestClient(app)
_n = itertools.count()
PASSWORD = "AuditLogTest12345"


@pytest.fixture
def sessions():
    """The shared test database - the same one the logger writes to, with no
    patching: since Phase 2 there is only one engine (app/shared/db.py)."""
    return SessionLocal


def register_and_login() -> tuple[int, dict[str, str]]:
    email = f"audit-{next(_n)}@example.com"
    r = client.post("/api/v1/auth/register",
                    json={"full_name": "Audit Test", "email": email, "password": PASSWORD})
    assert r.status_code in (200, 201), r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["user_id"], {"Authorization": f"Bearer {body['token']}"}


def rows(factory, user_id: int) -> list[tuple[str, str, str]]:
    db = factory()
    try:
        return [(r.event_type, r.severity, r.event_detail)
                for r in db.query(LogEntry).filter(LogEntry.user_id == user_id)
                .order_by(LogEntry.log_id)]
    finally:
        db.close()


def has(entries, event_type: str, severity: str, fragment: str) -> bool:
    return any(t == event_type and s == severity and fragment in d for t, s, d in entries)


def add_panel(factory, image_id: int) -> int:
    """A D4 row with one semantic D5 panel; no model is needed to serve it."""
    config.EXPLAINABILITY_DIR.mkdir(parents=True, exist_ok=True)
    panel = config.EXPLAINABILITY_DIR / f"audit_{next(_n)}.png"
    panel.write_bytes(png_bytes(make_image(width=32, height=32)))
    db = factory()
    try:
        model = ModelRegistry(model_name=f"audit {next(_n)}", model_version="t",
                              model_type="fusion-configuration", artifact_ref="t",
                              is_active=False)
        db.add(model)
        db.flush()
        prediction = Prediction(image_id=image_id, model_id=model.model_id, branch_model_ids={},
                                predicted_class="Real", confidence_score=0.9,
                                semantic_score=0.1, frequency_score=0.1, fusion_score=0.1,
                                latency_ms=1, prediction_timestamp=datetime.now(timezone.utc))
        db.add(prediction)
        db.flush()
        db.add(Explainability(prediction_id=prediction.prediction_id, branch="semantic",
                              technique="t", visualization_reference=str(panel.resolve()),
                              generated_at=datetime.now(timezone.utc)))
        db.commit()
        return prediction.prediction_id
    finally:
        db.close()


def test_login_upload_and_file_access_write_d6_rows(sessions):
    owner_id, owner = register_and_login()
    stranger_id, stranger = register_and_login()

    image_id = client.post("/api/v1/images", headers=owner, files={
        "file": ("x.png", png_bytes(make_image(seed=3)), "image/png")}).json()["image_id"]
    assert client.get(f"/api/v1/images/{image_id}/file", headers=owner).status_code == 200
    assert client.get(f"/api/v1/images/{image_id}/file", headers=stranger).status_code == 404
    assert client.get(f"/api/v1/images/{image_id}/thumbnail", headers=owner).status_code == 200
    assert client.get(f"/api/v1/images/{image_id}/thumbnail", headers=stranger).status_code == 404

    prediction_id = add_panel(sessions, image_id)
    url = f"/api/v1/explainability/{prediction_id}/semantic"
    assert client.get(url, headers=owner).status_code == 200
    assert client.get(url, headers=stranger).status_code == 404

    mine, theirs = rows(sessions, owner_id), rows(sessions, stranger_id)
    assert has(mine, "authentication", "info", "User registered successfully")
    assert has(mine, "authentication", "info", "User logged in successfully")
    assert has(mine, "prediction-request", "info",
               f"Image validated and stored: image_id={image_id}")
    assert has(mine, "prediction-request", "info", f"Image file served: image_id={image_id}")
    assert has(mine, "prediction-request", "info",
               f"Explainability file served: prediction_id={prediction_id} branch=semantic")
    assert has(theirs, "error", "warning", f"Image file refused: image_id={image_id}")
    assert has(theirs, "error", "warning",
               f"Explainability file refused: prediction_id={prediction_id} branch=semantic")
    # Thumbnails: refusals audited, routine successful serves deliberately not.
    assert has(theirs, "error", "warning", f"Image thumbnail refused: image_id={image_id}")
    assert not any("thumbnail" in d for t, _, d in mine)
    # Redaction: nothing that looks like a credential reached D6.
    for _, _, detail in mine + theirs:
        assert PASSWORD not in detail and "eyJ" not in detail


def test_a_swallowed_log_write_is_caught(monkeypatch):
    """The safety net works: a write that raises is recorded and fails the check."""
    def broken_session():
        raise RuntimeError("database unavailable")

    logging_service.WRITE_FAILURES.clear()
    monkeypatch.setattr(logging_service, "SessionLocal", broken_session)
    emit("authentication", "this write cannot succeed", severity="info")  # must not raise
    assert any("database unavailable" in f for f in logging_service.WRITE_FAILURES)
    with pytest.raises(pytest.fail.Exception, match="database unavailable"):
        assert_no_swallowed_log_writes()
    logging_service.WRITE_FAILURES.clear()
