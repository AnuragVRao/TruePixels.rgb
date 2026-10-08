"""D4 dual-write during the C2 v2 expand step (migration 0006).

Every prediction the pipeline writes must carry the new columns (p_ai,
certainty, calibration_ref - all set, or all NULL) AND still satisfy the
legacy NOT NULL confidence_score column, on every path: fused, semantic-only
(image under SPAI's 224 px patch) and "no map applies" (NULL p_ai).
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.m1_access.models import User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis import calibration, fusion
from app.m2_analysis.models import Prediction
from app.main import app
from app.shared import config
from app.shared.db import SessionLocal
from conftest import make_image, png_bytes

client = TestClient(app)
_n = itertools.count()
REPO = Path(__file__).resolve().parents[2]


def _auth() -> dict[str, str]:
    db = SessionLocal()
    try:
        user = User(full_name="D4", email=f"d4-{next(_n)}@example.com",
                    password_hash=hash_password("D4-p_ai-12345"), role="User",
                    account_status="active", is_email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"Authorization": f"Bearer {create_session_token(user)[0]}"}
    finally:
        db.close()


def _predict_row(width: int, height: int, seed: int) -> tuple[dict, Prediction]:
    headers = _auth()
    image = client.post("/api/v1/images", headers=headers,
                        files={"file": ("x.png", png_bytes(make_image(width=width, height=height, seed=seed)),
                                        "image/png")})
    assert image.status_code == 201, image.text
    r = client.post("/api/v1/predictions", headers=headers,
                    json={"image_id": image.json()["image_id"], "xai": False})
    assert r.status_code == 201, r.text
    body = r.json()
    db = SessionLocal()
    try:
        return body, db.get(Prediction, body["prediction_id"])
    finally:
        db.close()


def _legacy_ok(body: dict, row: Prediction) -> None:
    assert row.confidence_score is not None
    assert row.confidence_score == pytest.approx(
        fusion.legacy_confidence_score(row.fusion_score, config.FUSION_TAU, row.predicted_class))


@pytest.mark.slow
def test_fused_prediction_writes_p_ai_and_the_legacy_column():
    body, row = _predict_row(700, 500, 61)
    assert row.frequency_score is not None
    assert row.p_ai == body["p_ai"] == calibration.p_ai(row.fusion_score, semantic_only=False)
    assert row.certainty == body["certainty"] == calibration.certainty(row.p_ai)
    assert row.calibration_ref == config.CALIBRATION_FUSED_REF
    _legacy_ok(body, row)


@pytest.mark.slow
def test_semantic_only_prediction_writes_p_ai_and_the_legacy_column():
    body, row = _predict_row(160, 160, 62)
    assert row.frequency_score is None
    assert row.p_ai == body["p_ai"] == calibration.p_ai(row.fusion_score, semantic_only=True)
    assert row.certainty == body["certainty"] == "inconclusive"
    assert row.calibration_ref == config.CALIBRATION_SEMANTIC_ONLY_REF
    _legacy_ok(body, row)


@pytest.mark.slow
def test_no_map_applies_writes_null_p_ai_and_still_the_legacy_column(monkeypatch):
    monkeypatch.setattr(calibration, "applies", lambda models, *, semantic_only: False)
    body, row = _predict_row(700, 500, 63)
    assert (row.p_ai, row.certainty, row.calibration_ref) == (None, None, None)
    assert (body["p_ai"], body["certainty"]) == (None, None)
    _legacy_ok(body, row)


def test_nothing_outside_m2_reads_the_legacy_confidence_function():
    """legacy_confidence_score exists only to fill D4's legacy column in the
    pipeline until the contract migration drops it. M3, the stubs and both
    front ends must never call it."""
    roots = [REPO / "backend" / "app" / "m3_results", REPO / "backend" / "app" / "stubs",
             REPO / "frontend" / "src", REPO / "frontend" / "m3_dashboard"]
    offenders = []
    for root in roots:
        assert root.is_dir(), root
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".html"}:
                if re.search(r"legacy_confidence_score", path.read_text(encoding="utf-8", errors="ignore")):
                    offenders.append(str(path.relative_to(REPO)))
    assert offenders == []
    users = [p for p in (REPO / "backend" / "app").rglob("*.py")
             if "legacy_confidence_score" in p.read_text(encoding="utf-8")]
    assert sorted(p.name for p in users) == ["fusion.py", "pipeline.py"]
