"""Stored files are served only through owner-checked endpoints.

Regression tests for the unauthenticated ``/static`` mount, which served the
whole storage tree - every user's uploads, and the model weights - to anyone
who had the URL. Now:

* ``GET /api/v1/images/{id}/file`` (M1) serves an original to its owner, or
  to an Admin (M1's existing visibility rule for image metadata);
* ``GET /api/v1/explainability/{prediction_id}/{branch}`` (M3) serves a panel
  to the owner of the prediction only (M3's existing rule for results);
* everything else - another user, no session, a missing id, a reference
  outside the storage tree - gets the same not-found answer, and ``/static``
  no longer exists.

No model is needed: upload goes through M1 only, and predictions are D4 rows
written directly.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.m1_access.models import Image, User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis.models import ModelRegistry, Prediction
from app.m3_results.models import Explainability
from app.main import app
from app.shared import config
from app.shared.db import Base, get_db
from conftest import make_image, png_bytes

client = TestClient(app)
_emails = itertools.count()
_sessions: sessionmaker | None = None


@pytest.fixture(autouse=True, scope="module")
def _database(tmp_path_factory):
    """A private database, through get_db - same reasoning as test_api_predict."""
    global _sessions
    path = tmp_path_factory.mktemp("storage_access") / "test.db"
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


def make_user(role: str = "User") -> tuple[int, dict[str, str]]:
    db = _sessions()
    try:
        user = User(
            full_name="Storage Test",
            email=f"storage-{next(_emails)}@example.com",
            password_hash=hash_password("StorageTest12345"),
            role=role,
            account_status="active",
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token, _, _ = create_session_token(user)
        return user.user_id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def upload(headers: dict[str, str], seed: int) -> tuple[int, bytes]:
    payload = png_bytes(make_image(seed=seed))
    response = client.post("/api/v1/images", headers=headers,
                           files={"file": ("x.png", payload, "image/png")})
    assert response.status_code == 201, response.text
    return response.json()["image_id"], payload


def add_prediction(image_id: int, panel_reference: str) -> int:
    """A D4 row plus one semantic D5 row pointing at ``panel_reference``."""
    db = _sessions()
    try:
        model = db.query(ModelRegistry).first()
        if model is None:
            model = ModelRegistry(model_name="test fusion", model_version="t",
                                  model_type="fusion-configuration", artifact_ref="test",
                                  is_active=True)
            db.add(model)
            db.flush()
        prediction = Prediction(image_id=image_id, model_id=model.model_id,
                                branch_model_ids={}, predicted_class="Real",
                                confidence_score=0.9, semantic_score=0.1,
                                frequency_score=0.1, fusion_score=0.1, latency_ms=1,
                                prediction_timestamp=datetime.now(timezone.utc))
        db.add(prediction)
        db.flush()
        db.add(Explainability(prediction_id=prediction.prediction_id, branch="semantic",
                              technique="attention-rollout",
                              visualization_reference=panel_reference,
                              generated_at=datetime.now(timezone.utc)))
        db.commit()
        return prediction.prediction_id
    finally:
        db.close()


def assert_not_found(response, code: str) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == code


# --------------------------------------------------------------------------
# /static is gone
# --------------------------------------------------------------------------

def test_static_mount_no_longer_serves_storage():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=11)
    db = _sessions()
    reference = db.get(Image, image_id).file_reference
    db.close()
    relative = config.UPLOADS_DIR.name + "/" + "/".join(reference.replace("\\", "/").split("/")[-3:])
    for url in (f"/static/{relative}", "/static/models/spai.safetensors", "/static/models/spai.pth"):
        response = client.get(url)
        assert response.status_code == 404, url
        assert not response.content.startswith(b"\x89PNG")


# --------------------------------------------------------------------------
# Originals: GET /api/v1/images/{id}/file
# --------------------------------------------------------------------------

def test_owner_downloads_their_original():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=12)
    response = client.get(f"/api/v1/images/{image_id}/file", headers=owner)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content.startswith(b"\x89PNG")


def test_other_user_gets_the_same_answer_as_a_missing_image():
    _, owner = make_user()
    _, stranger = make_user()
    image_id, _ = upload(owner, seed=13)
    not_yours = client.get(f"/api/v1/images/{image_id}/file", headers=stranger)
    missing = client.get("/api/v1/images/999999/file", headers=stranger)
    assert_not_found(not_yours, "IMG_NOT_FOUND")
    assert_not_found(missing, "IMG_NOT_FOUND")
    assert not_yours.json()["error"]["message"].replace(str(image_id), "N") == \
        missing.json()["error"]["message"].replace("999999", "N")


def test_no_session_is_rejected():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=14)
    assert client.get(f"/api/v1/images/{image_id}/file").status_code == 401


def test_admin_can_view_an_original():
    """Mirrors M1's metadata rule (owner or Admin), on purpose."""
    _, owner = make_user()
    _, admin = make_user(role="Admin")
    image_id, _ = upload(owner, seed=15)
    assert client.get(f"/api/v1/images/{image_id}/file", headers=admin).status_code == 200


def test_reference_outside_uploads_is_refused(tmp_path):
    """Defence in depth: a D2 row pointing outside the uploads tree serves nothing."""
    user_id, owner = make_user()
    image_id, _ = upload(owner, seed=16)
    outside = tmp_path / "secret.png"
    outside.write_bytes(png_bytes(make_image(seed=99)))
    db = _sessions()
    db.get(Image, image_id).file_reference = str(outside)
    db.commit()
    db.close()
    assert_not_found(client.get(f"/api/v1/images/{image_id}/file", headers=owner), "IMG_NOT_FOUND")


def test_results_and_history_link_to_the_authenticated_endpoint():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=17)
    prediction_id = add_prediction(image_id, "unused.png")
    result = client.get(f"/api/v1/results/{prediction_id}", headers=owner).json()
    assert result["original_image_url"] == f"/api/v1/images/{image_id}/file"
    assert result["visualizations"][0]["visualization_url"] == \
        f"/api/v1/explainability/{prediction_id}/semantic"
    history = client.get("/api/v1/history", headers=owner).json()["items"]
    assert history[0]["thumbnail_url"] == f"/api/v1/images/{image_id}/file"
    assert not any("/static" in str(v) for v in [result, history])


# --------------------------------------------------------------------------
# Explainability panels: GET /api/v1/explainability/{prediction_id}/{branch}
# --------------------------------------------------------------------------

@pytest.fixture
def panel() -> str:
    config.EXPLAINABILITY_DIR.mkdir(parents=True, exist_ok=True)
    path = config.EXPLAINABILITY_DIR / f"test_panel_{next(_emails)}.png"
    path.write_bytes(png_bytes(make_image(width=64, height=64, seed=5)))
    return str(path.resolve())


def test_owner_downloads_a_panel(panel):
    _, owner = make_user()
    image_id, _ = upload(owner, seed=21)
    prediction_id = add_prediction(image_id, panel)
    response = client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=owner)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_panel_not_yours_missing_branch_and_missing_prediction_look_alike(panel):
    _, owner = make_user()
    _, stranger = make_user()
    image_id, _ = upload(owner, seed=22)
    prediction_id = add_prediction(image_id, panel)
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=stranger),
                     "INF_PREDICTION_NOT_FOUND")
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/frequency", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")
    assert_not_found(client.get("/api/v1/explainability/999999/semantic", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")
    assert client.get(f"/api/v1/explainability/{prediction_id}/semantic").status_code == 401


def test_panel_reference_outside_explainability_dir_is_refused():
    """A D5 row that points at an upload (or anything else) serves nothing."""
    _, owner = make_user()
    image_id, _ = upload(owner, seed=23)
    db = _sessions()
    upload_path = db.get(Image, image_id).file_reference
    db.close()
    prediction_id = add_prediction(image_id, upload_path)
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")
