"""Explainability end to end through the API (real models; slow).

Runs on whichever database the suite uses - run the suite with
TEST_DATABASE_URL as well to cover PostgreSQL (the forced-failure cases in
particular: D4 must commit, D5 must not, on both backends).
"""

from __future__ import annotations

import io
import itertools

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.m1_access.models import User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis import detectors, frequency_detector
from app.m2_analysis.models import Prediction
from app.m3_results.models import Explainability, LogEntry
from app.main import app
from app.shared.db import SessionLocal
from conftest import make_image, png_bytes

pytestmark = pytest.mark.slow

client = TestClient(app)
_n = itertools.count()


@pytest.fixture(autouse=True)
def _weights():
    if not frequency_detector.frequency.present_on_disk:
        pytest.skip("SPAI weights not present; see CLAUDE.md section 4")


def _user() -> dict[str, str]:
    db = SessionLocal()
    try:
        user = User(full_name="XAI", email=f"xai-{next(_n)}@example.com",
                    password_hash=hash_password("XaiTesting12345"), role="User",
                    account_status="active", is_email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"Authorization": f"Bearer {create_session_token(user)[0]}"}
    finally:
        db.close()


def _upload(headers, payload: bytes) -> int:
    r = client.post("/api/v1/images", headers=headers, files={"file": ("x.png", payload, "image/png")})
    assert r.status_code == 201, r.text
    return r.json()["image_id"]


def _predict(headers, image_id: int, xai: bool):
    r = client.post("/api/v1/predictions", headers=headers, json={"image_id": image_id, "xai": xai})
    assert r.status_code == 201, r.text
    return r


def _d5(prediction_id: int) -> list[Explainability]:
    db = SessionLocal()
    try:
        return db.query(Explainability).filter(Explainability.prediction_id == prediction_id).all()
    finally:
        db.close()


SCORE_FIELDS = ("predicted_class", "confidence_score", "semantic_score", "frequency_score", "fusion_score")


def test_xai_on_and_off_give_bit_identical_predictions():
    headers = _user()
    image_id = _upload(headers, png_bytes(make_image(width=700, height=500, seed=21)))
    off = _predict(headers, image_id, xai=False).json()
    on = _predict(headers, image_id, xai=True).json()
    for field in SCORE_FIELDS:
        a, b = off[field], on[field]
        assert (a.hex() if isinstance(a, float) else a) == (b.hex() if isinstance(b, float) else b), field
    assert off["xai_status"] == "not_requested" and on["xai_status"] == "generated"


def test_generated_panels_are_linked_served_captioned_and_in_the_pdf():
    from pypdf import PdfReader

    owner, stranger = _user(), _user()
    image_id = _upload(owner, png_bytes(make_image(width=900, height=600, seed=22)))
    r = _predict(owner, image_id, xai=True)
    body = r.json()
    assert body["xai_status"] == "generated" and body["xai_reasons"] == []
    assert float(r.headers["X-XAI-Time-Ms"]) > 0

    rows = {row.branch: row for row in _d5(body["prediction_id"])}
    assert set(rows) == {"semantic", "frequency"}
    assert rows["semantic"].technique == "attention-rollout"
    assert rows["frequency"].technique == "spai-patch-spectrum"
    for row in rows.values():  # stored relative, never an absolute machine path
        assert not row.visualization_reference.startswith(("/", "\\")) and ":" not in row.visualization_reference

    result = client.get(f"/api/v1/results/{body['prediction_id']}", headers=owner).json()
    assert {v["branch"] for v in result["visualizations"]} == {"semantic", "frequency"}
    assert all("not" in v["caption"] for v in result["visualizations"])  # says what it does NOT show
    for item in result["visualizations"]:
        served = client.get(item["visualization_url"], headers=owner)
        assert served.status_code == 200 and served.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(served.content)) as png:
            assert not {k for k in png.info if k != "dpi"}
        assert client.get(item["visualization_url"], headers=stranger).status_code == 404

    pdf = client.get(f"/api/v1/reports/{body['prediction_id']}", headers=owner)
    assert pdf.status_code == 200
    reader = PdfReader(io.BytesIO(pdf.content))
    images = sum(len(page.images) for page in reader.pages)
    assert images == 3  # original + semantic overlay + spectrum
    text = " ".join(" ".join(p.extract_text() for p in reader.pages).split())
    assert "not available" not in text.lower() and "not generated" not in text.lower()


def test_an_image_below_one_spai_patch_gets_a_partial_result():
    headers = _user()
    image_id = _upload(headers, png_bytes(make_image(width=160, height=160, seed=23)))
    body = _predict(headers, image_id, xai=True).json()
    assert body["frequency_score"] is None
    assert body["xai_status"] == "partial"
    assert body["xai_reasons"] == ["frequency:not_applicable"]
    assert {row.branch for row in _d5(body["prediction_id"])} == {"semantic"}


def _assert_failed_softly(headers, image_id, expected_reason_prefix):
    r = _predict(headers, image_id, xai=True)
    body = r.json()
    assert body["xai_status"] == "unavailable"
    assert body["xai_reasons"][0].startswith(expected_reason_prefix)
    db = SessionLocal()
    try:
        assert db.get(Prediction, body["prediction_id"]) is not None  # D4 committed
        warnings = [e.event_detail for e in db.query(LogEntry).filter(LogEntry.severity == "warning")]
    finally:
        db.close()
    assert _d5(body["prediction_id"]) == []  # no D5 rows
    assert any(f"prediction {body['prediction_id']}" in w for w in warnings)
    # The prediction is still fully usable afterwards.
    assert client.get(f"/api/v1/results/{body['prediction_id']}", headers=headers).status_code == 200


def test_render_failure_returns_the_prediction_with_xai_unavailable(monkeypatch):
    from app.m3_results import overlay

    def explode(*_a, **_k):
        raise RuntimeError("renderer crashed")

    monkeypatch.setattr(overlay, "persist_explainability", explode)
    headers = _user()
    _assert_failed_softly(headers, _upload(headers, png_bytes(make_image(seed=24))), "render_failed")


def test_failure_after_d5_rows_are_staged_rolls_back_only_d5(monkeypatch):
    """The D5 commit itself fails: D4 stays, no half-written D5."""
    from sqlalchemy.orm import Session

    real_commit = Session.commit

    def failing_commit(self):
        if any(isinstance(o, Explainability) for o in self.new):
            raise RuntimeError("database refused the D5 write")
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)
    headers = _user()
    _assert_failed_softly(headers, _upload(headers, png_bytes(make_image(seed=25))), "render_failed")


def test_capture_failure_returns_the_prediction_with_xai_unavailable(monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("hooks saw nothing")

    monkeypatch.setattr(detectors.primary, "attention_maps", explode)
    headers = _user()
    _assert_failed_softly(headers, _upload(headers, png_bytes(make_image(seed=26))), "capture_failed")
