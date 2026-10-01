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
