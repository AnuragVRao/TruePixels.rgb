"""
Unit & Integration Tests for Module M3 PDF Report Generation (F.14, MM3.5).
"""
from __future__ import annotations
from fastapi.testclient import TestClient
from app.m3_results.reporting import build_pdf_report
from app.m3_results.models import Prediction, Explainability


def test_build_pdf_report_buffer(seeded_db):
    """Validates that build_pdf_report produces a non-empty, valid PDF byte buffer."""
    db = seeded_db["db"]
    pred = db.query(Prediction).first()
    explainabilities = db.query(Explainability).filter(Explainability.prediction_id == pred.prediction_id).all()

    pdf_buffer = build_pdf_report(prediction=pred, explainabilities=explainabilities)
    pdf_bytes = pdf_buffer.getvalue()

    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")  # Standard PDF Magic Header


def test_download_report_endpoint(client: TestClient, seeded_db):
    """Validates streaming download of forensic PDF report via HTTP endpoint."""
    pred_id = seeded_db["a_preds"][0].prediction_id
    resp = client.get(
        f"/api/v1/reports/{pred_id}",
        headers={"Authorization": "Bearer test-user-token-1"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert resp.content.startswith(b"%PDF-")


# --- Batch download: several reports in one ZIP (2026-10-14) -------------------

import io
import zipfile

USER_A = {"Authorization": "Bearer test-user-token-1"}
ADMIN = {"Authorization": "Bearer test-admin-token-1"}


def _zip_names(resp) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        assert all(archive.read(n).startswith(b"%PDF-") for n in archive.namelist())
        return archive.namelist()


def test_zip_of_own_reports(client: TestClient, seeded_db):
    ids = [p.prediction_id for p in seeded_db["a_preds"]]
    resp = client.post("/api/v1/reports/zip", json={"prediction_ids": ids + [ids[0]]}, headers=USER_A)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert 'filename="TruePixels_Reports.zip"' in resp.headers["content-disposition"]
    # One PDF per prediction, duplicates included once, in the order asked.
    assert _zip_names(resp) == [f"TruePixels_Report_{i}.pdf" for i in ids]


def test_zip_refuses_anyone_elses_prediction_as_not_found(client: TestClient, seeded_db):
    own = seeded_db["a_preds"][0].prediction_id
    other = seeded_db["b_preds"][0].prediction_id
    resp = client.post("/api/v1/reports/zip", json={"prediction_ids": [own, other]}, headers=USER_A)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INF_PREDICTION_NOT_FOUND"
    missing = client.post("/api/v1/reports/zip", json={"prediction_ids": [own, 999999]}, headers=USER_A)
    # A prediction that does not exist gets the same answer as someone else's.
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == resp.json()["error"]["code"]


def test_zip_admin_may_include_any_users_reports(client: TestClient, seeded_db):
    ids = [seeded_db["a_preds"][0].prediction_id, seeded_db["b_preds"][0].prediction_id]
    resp = client.post("/api/v1/reports/zip", json={"prediction_ids": ids}, headers=ADMIN)
    assert resp.status_code == 200
    assert len(_zip_names(resp)) == 2


def test_zip_limits_and_session(client: TestClient, seeded_db):
    own = seeded_db["a_preds"][0].prediction_id
    assert client.post("/api/v1/reports/zip", json={"prediction_ids": []}, headers=USER_A).status_code == 422
    assert client.post("/api/v1/reports/zip", json={"prediction_ids": [own] * 11}, headers=USER_A).status_code == 422
    assert client.post("/api/v1/reports/zip", json={"prediction_ids": [own]}).status_code == 401
