"""D4 must link to D3 rows that describe exactly what ran (F.12 provenance).

Phase 4, item (i): written BEFORE the fix, against the config-driven registry,
to reproduce the stale-provenance defect found in Phase 0:

- the semantic row was always version "main" with a null hash, so a change
  of weights on the hub was invisible;
- registry._upsert keyed rows on (name, version) and never updated them, so
  changing a setting that is not part of the version string (here SPAI's
  ai_is_positive sign convention) linked new predictions to an OLD row whose
  recorded hyperparameters no longer matched what ran.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from app.m1_access.models import User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis import frequency_detector
from app.m2_analysis.models import ModelRegistry, Prediction
from app.main import app
from app.shared import config
from app.shared.db import SessionLocal
from conftest import make_image, png_bytes

pytestmark = [
    pytest.mark.slow,
    # Reproduction committed BEFORE the fix (Phase 4 item i); both fail on the
    # config-driven registry. strict=True: the suite goes red if they pass
    # without the fix commit removing this marker.
    pytest.mark.xfail(strict=True, reason="stale D3 provenance - fixed by the D3-authority registry"),
]
client = TestClient(app)
_n = itertools.count()


def _auth() -> dict[str, str]:
    db = SessionLocal()
    try:
        user = User(full_name="P", email=f"prov-{next(_n)}@example.com",
                    password_hash=hash_password("Provenance12345"), role="User",
                    account_status="active", is_email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"Authorization": f"Bearer {create_session_token(user)[0]}"}
    finally:
        db.close()


def _predict(headers, seed: int) -> int:
    image = client.post("/api/v1/images", headers=headers,
                        files={"file": ("x.png", png_bytes(make_image(seed=seed)), "image/png")})
    r = client.post("/api/v1/predictions", headers=headers,
                    json={"image_id": image.json()["image_id"], "xai": False})
    assert r.status_code == 201, r.text
    return r.json()["prediction_id"]


def _linked(prediction_id: int) -> dict[str, ModelRegistry]:
    db = SessionLocal()
    try:
        p = db.get(Prediction, prediction_id)
        ids = p.branch_model_ids or {}
        return {"semantic": db.get(ModelRegistry, ids["semantic"]),
                "frequency": db.get(ModelRegistry, ids["frequency"]),
                "fusion": db.get(ModelRegistry, p.model_id)}
    finally:
        db.close()


def test_semantic_row_pins_revision_and_weights():
    row = _linked(_predict(_auth(), 1))["semantic"]
    assert row.artifact_sha256, "semantic D3 row has no weights digest"
    assert row.model_version != "main", "semantic D3 row is the floating 'main' branch"


def test_linked_frequency_row_records_the_sign_convention_that_ran(monkeypatch):
    headers = _auth()
    first = _linked(_predict(headers, 2))["frequency"]
    assert first.hyperparameters["ai_is_positive"] is True

    # Flip the convention the way the old system allowed: in config.
    monkeypatch.setattr(config, "DETECTOR_FREQUENCY_AI_IS_POSITIVE", False)
    monkeypatch.setattr(frequency_detector.frequency, "ai_is_positive", False)
    second = _linked(_predict(headers, 3))["frequency"]
    assert second.hyperparameters["ai_is_positive"] is False, (
        f"prediction ran with ai_is_positive=False but links D3 row #{second.model_id} "
        f"recording {second.hyperparameters}"
    )
