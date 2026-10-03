"""Records whose stored files are gone degrade gracefully - never a 500.

The fixture mirrors the two migrated dev rows: a D2 image row (and its D4
prediction) whose file_reference points inside storage/uploads at a file that
no longer exists, plus a D5 panel row whose PNG is gone.
"""

from __future__ import annotations

import io
import itertools
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.m1_access.models import Image, User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis.models import ModelRegistry, Prediction
from app.m3_results.models import Explainability
from app.main import app
from app.shared import config
from app.shared.db import SessionLocal

client = TestClient(app)
_n = itertools.count()


def _user() -> tuple[int, dict[str, str]]:
    db = SessionLocal()
    try:
        user = User(full_name="Missing", email=f"missing-{next(_n)}@example.com",
                    password_hash=hash_password("MissingFiles123"), role="User",
                    account_status="active", is_email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.user_id, {"Authorization": f"Bearer {create_session_token(user)[0]}"}
    finally:
        db.close()


@pytest.fixture
def orphaned_record():
    """An owner, a stranger, and a prediction whose files are all gone."""
    owner_id, owner = _user()
    _, stranger = _user()
    gone_upload = config.UPLOADS_DIR / "5a" / "9f" / f"{'5a9f' + '0' * 60}.png"
    gone_panel = config.EXPLAINABILITY_DIR / "pred_gone_semantic.png"
    assert not gone_upload.exists() and not gone_panel.exists()
    db = SessionLocal()
    try:
        image = Image(user_id=owner_id, file_reference=str(gone_upload), content_sha256="5a" * 32,
                      file_format="PNG", file_size=1, width=640, height=480,
                      validation_status="valid")
        model = ModelRegistry(model_name=f"m{next(_n)}", model_version="t",
                              model_type="fusion-configuration", artifact_ref="t", is_active=False)
        db.add_all([image, model])
        db.flush()
        prediction = Prediction(image_id=image.image_id, model_id=model.model_id,
                                branch_model_ids={}, predicted_class="Real",
                                confidence_score=0.8, semantic_score=0.2, frequency_score=0.1,
                                fusion_score=0.2, latency_ms=900,
                                prediction_timestamp=datetime.now(timezone.utc))
        db.add(prediction)
        db.flush()
        db.add(Explainability(prediction_id=prediction.prediction_id, branch="semantic",
                              technique="t", visualization_reference=str(gone_panel),
                              generated_at=datetime.now(timezone.utc)))
        db.commit()
        return {"owner": owner, "stranger": stranger, "image_id": image.image_id,
                "prediction_id": prediction.prediction_id}
    finally:
        db.close()


def test_result_view_says_the_original_is_gone(orphaned_record):
    r = client.get(f"/api/v1/results/{orphaned_record['prediction_id']}",
                   headers=orphaned_record["owner"])
    assert r.status_code == 200
    assert r.json()["original_available"] is False
    assert r.json()["predicted_class"] == "Real"  # the recorded outcome is still served


@pytest.mark.parametrize("kind", ["file", "thumbnail"])
def test_owner_gets_a_structured_410_for_the_missing_original(orphaned_record, kind):
    url = f"/api/v1/images/{orphaned_record['image_id']}/{kind}"
    owner = client.get(url, headers=orphaned_record["owner"])
    assert owner.status_code == 410
    assert owner.json()["error"]["code"] == "IMG_FILE_MISSING"
    stranger = client.get(url, headers=orphaned_record["stranger"])  # existence not leaked
    assert stranger.status_code == 404 and stranger.json()["error"]["code"] == "IMG_NOT_FOUND"


def test_owner_gets_a_structured_410_for_a_missing_panel(orphaned_record):
    url = f"/api/v1/explainability/{orphaned_record['prediction_id']}/semantic"
    owner = client.get(url, headers=orphaned_record["owner"])
    assert owner.status_code == 410 and owner.json()["error"]["code"] == "XAI_FILE_MISSING"
    stranger = client.get(url, headers=orphaned_record["stranger"])
    assert stranger.status_code == 404 and stranger.json()["error"]["code"] == "INF_PREDICTION_NOT_FOUND"


def test_pdf_report_is_produced_and_says_the_original_is_gone(orphaned_record):
    from pypdf import PdfReader

    r = client.get(f"/api/v1/reports/{orphaned_record['prediction_id']}",
                   headers=orphaned_record["owner"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(r.content)).pages)
    assert "no longer stored" in " ".join(text.split())


def test_overlay_refuses_instead_of_drawing_on_a_placeholder(tmp_path):
    import numpy as np

    from app.m3_results.overlay import generate_semantic_overlay
    from app.shared.errors import AppException

    with pytest.raises(AppException) as raised:
        generate_semantic_overlay(original_image_path=str(tmp_path / "gone.png"),
                                  relevance_2d=np.ones((14, 14), dtype=np.float32),
                                  target_width=64, target_height=64,
                                  output_path=str(tmp_path / "out.png"))
    assert raised.value.code == "XAI_UNAVAILABLE"
    assert not (tmp_path / "out.png").exists()
