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
from app.m2_analysis.models import ModelRegistry, Prediction
from app.main import app
from app.shared import config
from app.shared.db import SessionLocal
from conftest import make_image, png_bytes

pytestmark = pytest.mark.slow
# History: these two tests were committed first as strict xfail, failing on the
# config-driven registry (commit "reproduce stale D3 provenance"). The second
# is rewritten below for D3 authority: config edits no longer change what runs.
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


def _linked(prediction_id: int) -> dict:
    db = SessionLocal()
    try:
        p = db.get(Prediction, prediction_id)
        assert p.branch_model_ids == {"semantic": p.semantic_model_id, "frequency": p.frequency_model_id}
        return {"semantic": db.get(ModelRegistry, p.semantic_model_id),
                "frequency": db.get(ModelRegistry, p.frequency_model_id),
                "fusion": db.get(ModelRegistry, p.model_id),
                "frequency_score": p.frequency_score}
    finally:
        db.close()


def test_semantic_row_pins_revision_and_weights():
    row = _linked(_predict(_auth(), 1))["semantic"]
    assert row.artifact_sha256, "semantic D3 row has no weights digest"
    assert row.model_version != "main", "semantic D3 row is the floating 'main' branch"


def test_editing_config_no_longer_changes_what_runs(monkeypatch):
    """The old defect's trigger - a config edit - is now inert: what runs and
    what D4 links are the ACTIVE D3 rows, so both stay as they were."""
    headers = _auth()
    first = _linked(_predict(headers, 2))
    monkeypatch.setattr(config, "DETECTOR_FREQUENCY_AI_IS_POSITIVE", False)
    second = _linked(_predict(headers, 2))
    assert second["frequency"].model_id == first["frequency"].model_id
    assert second["frequency"].hyperparameters["ai_is_positive"] is True
    assert second["frequency_score"] == first["frequency_score"]


def test_linked_frequency_row_records_the_sign_convention_that_ran():
    """Activating a D3 row with the opposite sign convention changes what runs,
    and D4 links exactly that row (forced past the gate: it is deliberately bad)."""
    from app.m2_analysis import registry

    headers = _auth()
    before = _linked(_predict(headers, 3))
    db = SessionLocal()
    try:
        base = before["frequency"]
        flipped = ModelRegistry(
            model_name=base.model_name, model_version="test-sign-flipped",
            model_type=base.model_type, artifact_ref=base.artifact_ref,
            artifact_sha256=base.artifact_sha256,
            hyperparameters={**base.hyperparameters, "ai_is_positive": False},
            training_reference="test: inverted sign convention", is_active=False)
        db.add(flipped)
        db.commit()
        registry.activate(db, flipped.model_id, actor_id=None, force=True, reason="provenance test")
        flipped_id = flipped.model_id
    finally:
        db.close()

    after = _linked(_predict(headers, 3))
    assert after["frequency"].model_id == flipped_id
    assert after["frequency"].hyperparameters["ai_is_positive"] is False
    assert after["frequency_score"] == pytest.approx(1.0 - before["frequency_score"], abs=1e-9)
