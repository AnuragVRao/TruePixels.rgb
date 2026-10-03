"""End-to-end test of POST /api/v1/predictions, through M1 and into M3.

Every image takes the integrated path: authenticated upload through M1
(POST /api/v1/images), prediction by image_id through M2, and - for the D4
checks - the stored row read back through M3's GET /api/v1/results/{id}.

Downloads the SigLIP 2 checkpoint on first run and needs the converted SPAI
weights on disk (see CLAUDE.md section 4 for the one-time setup), so this
module is far slower than the rest of the suite. It proves the thing the whole
slice exists to prove: an image goes in, a verdict from genuinely pretrained
models comes out.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.m1_access.models import User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis import frequency_detector
from app.main import app
from app.shared import config
from app.shared.db import Base, get_db

pytestmark = pytest.mark.slow

client = TestClient(app)
_emails = itertools.count()
_sessions: sessionmaker | None = None


@pytest.fixture(autouse=True, scope="module")
def _database(tmp_path_factory):
    """A private database for this module, through get_db like M1/M3's suites.

    The global engine cannot be relied on here: M1's conftest sets
    DATABASE_URL=sqlite:///:memory: when it is collected, and an in-memory
    SQLite database without a StaticPool is a different, empty database on
    every connection.
    """
    global _sessions
    path = tmp_path_factory.mktemp("m2_api") / "test.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    _sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = _sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def make_user() -> dict[str, str]:
    """A fresh account with its own session; returns the auth header."""
    db = _sessions()
    try:
        user = User(
            full_name="M2 Test User",
            email=f"m2-test-{next(_emails)}@example.com",
            password_hash=hash_password("M2TestPassword123"),
            role="User",
            account_status="active",
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token, _, _ = create_session_token(user)
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def auth() -> dict[str, str]:
    return make_user()


@pytest.fixture(autouse=True, scope="module")
def _require_frequency_weights():
    """Skip - not fail - when the converted SPAI weights are absent.

    A missing local artefact is an environment condition, not a defect in the
    code under test, and the error path itself is covered without weights in
    test_frequency_detector.py.
    """
    if not frequency_detector.frequency.present_on_disk:
        pytest.skip(
            f"SPAI weights not present at {frequency_detector.frequency.path}; "
            "see CLAUDE.md section 4 for the one-time download and conversion"
        )


def upload(payload: bytes, headers: dict[str, str]) -> int:
    """Upload through M1; returns the D2 image_id."""
    response = client.post(
        "/api/v1/images",
        headers=headers,
        files={"file": ("sample.png", payload, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["image_id"]


def predict(image_id: int, headers: dict[str, str], *, xai: bool = False):
    return client.post(
        "/api/v1/predictions",
        headers=headers,
        json={"image_id": image_id, "xai": xai},
    )


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["device"] in {"cpu", "cuda"}
    assert body["trains_models"] is False
    assert body["detectors"]["primary"]["checkpoint"]
    assert body["detectors"]["frequency"]["name"] == "SPAI"
    assert body["detectors"]["frequency"]["present_on_disk"] is True


def test_upload_returns_a_complete_prediction(sample_png, auth):
    response = predict(upload(sample_png, auth), auth)

    assert response.status_code == 201
    body = response.json()

    # Every field of the public half of Contract C2 is present - and nothing
    # that is not in PRD2 section 7.3 any more.
    for field in (
        "image_id",
        "user_id",
        "predicted_class",
        "confidence_score",
        "semantic_score",
        "frequency_score",
        "fusion_score",
        "prediction_timestamp",
        "latency_ms",
    ):
        assert field in body, f"missing C2 field: {field}"
    assert "secondary_score" not in body

    # AC-01: binary only, never 'uncertain', never a third class.
    assert body["predicted_class"] in {"Real", "AI Generated"}

    # AC-02: both branch scores present even when one would have decided.
    for field in (
        "confidence_score",
        "semantic_score",
        "frequency_score",
        "fusion_score",
    ):
        assert body[field] is not None, f"{field} is null"
        assert 0.0 <= body[field] <= 1.0, f"{field} out of range: {body[field]}"

    assert body["latency_ms"] >= 0


def test_both_branches_load_after_a_prediction(sample_png, auth):
    """After a prediction, /health shows both models resident.

    The primary reports the AI index it resolved from its own labels; the
    frequency detector reports the sign convention it is running under.
    """
    predict(upload(sample_png, auth), auth)

    detectors = client.get("/health").json()["detectors"]

    assert detectors["primary"]["loaded"] is True
    assert detectors["primary"]["ai_index"] == 1
    assert detectors["frequency"]["loaded"] is True
    assert detectors["frequency"]["ai_is_positive"] is True


def test_scores_are_not_all_identical(sample_png, auth):
    """Two independent branches should not agree to the last decimal.

    If they did, it would suggest one of them is not actually running.
    """
    body = predict(upload(sample_png, auth), auth).json()

    assert body["semantic_score"] != body["frequency_score"]


def test_fusion_is_the_documented_average_of_the_two_branches(sample_png, auth):
    """PRD2 FR-03 strategy A with the configured w, asserted over HTTP.

    w is an operating-point constant (0.25 since 2026-10-01, chosen on a
    validation split), so the expectation reads it from config rather than
    hard-coding the old 0.5 - which is what this test did until 2026-10-02.
    """
    body = predict(upload(sample_png, auth), auth).json()

    w = config.FUSION_WEIGHT
    expected = w * body["semantic_score"] + (1.0 - w) * body["frequency_score"]
    assert body["fusion_score"] == pytest.approx(expected, abs=1e-6)


def test_confidence_follows_the_inversion_rule_over_http(sample_png, auth):
    """AC-05, asserted from outside the module - the same check M3 runs."""
    body = predict(upload(sample_png, auth), auth).json()

    if body["predicted_class"] == "AI Generated":
        assert body["confidence_score"] == pytest.approx(body["fusion_score"])
    else:
        assert body["confidence_score"] == pytest.approx(1.0 - body["fusion_score"])


def test_the_activation_bundle_never_crosses_the_http_boundary(sample_png, auth):
    """Contract C2 section 5.4 - in-process only, even when xai is requested."""
    body = predict(upload(sample_png, auth), auth, xai=True).json()

    assert "activations" not in body


def test_identical_images_produce_identical_scores(sample_png, auth):
    """AC-04 and PRD2 section 8.4 determinism, for BOTH branches."""
    first = predict(upload(sample_png, auth), auth).json()
    second = predict(upload(sample_png, auth), auth).json()

    assert first["semantic_score"] == second["semantic_score"]
    assert first["frequency_score"] == second["frequency_score"]
    assert first["fusion_score"] == second["fusion_score"]
    assert first["predicted_class"] == second["predicted_class"]

    # Different uploads are still distinct images in the (future) D2 store.
    assert first["image_id"] != second["image_id"]


def test_different_images_produce_different_scores(sample_png, auth):
    """A pipeline that ignores its input would pass every test above."""
    from conftest import make_image, png_bytes

    other = png_bytes(make_image(seed=99))

    first = predict(upload(sample_png, auth), auth).json()
    second = predict(upload(other, auth), auth).json()

    assert first["fusion_score"] != second["fusion_score"]


def test_prediction_is_persisted_and_readable_through_m3(sample_png, auth):
    """PRD4 4.2.4: M2 commits D4 before returning; M3 reads the same row."""
    body = predict(upload(sample_png, auth), auth).json()

    assert isinstance(body["prediction_id"], int)
    assert isinstance(body["model_id"], int)

    view = client.get(f"/api/v1/results/{body['prediction_id']}", headers=auth)
    assert view.status_code == 200, view.text
    stored = view.json()
    for field in ("predicted_class", "confidence_score", "semantic_score", "frequency_score", "fusion_score"):
        assert stored[field] == pytest.approx(body[field]), field

    history = client.get("/api/v1/history", headers=auth).json()
    assert body["prediction_id"] in {item["prediction_id"] for item in history["items"]}


def test_explainability_is_reported_unavailable_not_fabricated(sample_png, auth):
    """Step 6 is not built: M3 must say so rather than draw a synthetic map."""
    body = predict(upload(sample_png, auth), auth, xai=True).json()

    view = client.get(f"/api/v1/results/{body['prediction_id']}", headers=auth).json()
    assert view["visualizations"] == []

    xai = client.get(f"/api/v1/explainability/{body['prediction_id']}", headers=auth)
    assert xai.status_code == 501
    assert xai.json()["error"]["code"] == "XAI_UNAVAILABLE"


def test_prediction_requires_a_session(sample_png, auth):
    image_id = upload(sample_png, auth)

    response = client.post("/api/v1/predictions", json={"image_id": image_id})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_another_users_image_is_indistinguishable_from_a_missing_one(sample_png, auth):
    """Owner only, and no id-probing oracle: same code as a nonexistent id."""
    image_id = upload(sample_png, auth)
    intruder = make_user()

    theirs = predict(image_id, intruder)
    missing = predict(10**9, intruder)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json()["error"]["code"] == missing.json()["error"]["code"] == "IMG_NOT_FOUND"


def test_prediction_writes_its_d6_audit_rows(sample_png, auth, monkeypatch, strict_audit_log):
    """F.15: upload and prediction each leave a D6 row - and a swallowed write fails.

    The logger is pointed at this module's database for the test; elsewhere in
    this module it still writes to the global engine (fixed in Phase 2).
    """
    from app.m3_results import logging_service
    from app.m3_results.models import LogEntry

    monkeypatch.setattr(logging_service, "SessionLocal", _sessions)
    image_id = upload(sample_png, auth)
    prediction_id = predict(image_id, auth).json()["prediction_id"]

    db = _sessions()
    try:
        details = [r.event_detail for r in db.query(LogEntry)
                   .filter(LogEntry.event_type == "prediction-request")]
    finally:
        db.close()
    assert any(d.startswith(f"Image validated and stored: image_id={image_id},") for d in details)
    assert any(d.startswith(f"Prediction {prediction_id} for image_id={image_id}:") for d in details)


def test_no_clip_tensor_is_written_at_upload_or_prediction(sample_png, auth):
    """The dead C1 tensor (changes.md 6.3): no .npy appears anywhere in storage."""
    from app.shared import config as shared_config

    before = set(shared_config.STORAGE_ROOT.rglob("*.npy"))
    image_id = upload(sample_png, auth)
    assert predict(image_id, auth).status_code in (200, 201)
    assert set(shared_config.STORAGE_ROOT.rglob("*.npy")) == before == set()
    assert not (shared_config.STORAGE_ROOT / "tensors").exists()
