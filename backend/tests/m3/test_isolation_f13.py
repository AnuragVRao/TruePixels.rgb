"""
Module M3 Isolation Suite (F.13, PRD Section 10.2, Metric MM3.1).
Validates 8/8 test cases proving zero cross-user data access and zero ID-probing enumeration leaks.
"""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient

AUTH_HEADER_A = {"Authorization": "Bearer test-user-token-1"}
AUTH_HEADER_B = {"Authorization": "Bearer test-user-token-2"}


def test_isolation_case_1_user_a_gets_only_own_history(client: TestClient, seeded_db):
    """Case 1: User A requests GET /history -> Only A's rows returned at every page."""
    resp = client.get("/api/v1/history", headers=AUTH_HEADER_A)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    a_pred_ids = {p.prediction_id for p in seeded_db["a_preds"]}
    for item in data["items"]:
        assert item["prediction_id"] in a_pred_ids


def test_isolation_case_2_user_a_requests_user_b_prediction(client: TestClient, seeded_db):
    """Case 2: User A requests User B's prediction by ID -> returns 404 INF_PREDICTION_NOT_FOUND."""
    b_pred_id = seeded_db["b_preds"][0].prediction_id
    resp = client.get(f"/api/v1/results/{b_pred_id}", headers=AUTH_HEADER_A)
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "INF_PREDICTION_NOT_FOUND"


def test_isolation_case_3_user_a_requests_user_b_pdf_report(client: TestClient, seeded_db):
    """Case 3: User A requests PDF report of User B's prediction -> returns 404 INF_PREDICTION_NOT_FOUND."""
    b_pred_id = seeded_db["b_preds"][0].prediction_id
    resp = client.get(f"/api/v1/reports/{b_pred_id}", headers=AUTH_HEADER_A)
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "INF_PREDICTION_NOT_FOUND"


def test_isolation_case_4_user_a_requests_user_b_explainability(client: TestClient, seeded_db):
    """Case 4: User A requests User B's explainability by prediction ID -> returns 404 INF_PREDICTION_NOT_FOUND."""
    b_pred_id = seeded_db["b_preds"][0].prediction_id
    resp = client.get(f"/api/v1/explainability/{b_pred_id}", headers=AUTH_HEADER_A)
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "INF_PREDICTION_NOT_FOUND"


def test_isolation_case_5_user_a_appends_tampered_user_id_param(client: TestClient, seeded_db):
    """Case 5: User A appends ?user_id=2 (User B's id) -> Parameter ignored; only A's data returned."""
    resp = client.get("/api/v1/history?user_id=2", headers=AUTH_HEADER_A)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    a_pred_ids = {p.prediction_id for p in seeded_db["a_preds"]}
    for item in data["items"]:
        assert item["prediction_id"] in a_pred_ids


def test_isolation_case_6_user_a_requests_admin_endpoint(client: TestClient, seeded_db):
    """Case 6: User A requests any /admin/* endpoint -> returns 403 AUTH_FORBIDDEN."""
    resp1 = client.get("/api/v1/admin/summary", headers=AUTH_HEADER_A)
    assert resp1.status_code == 403
    assert resp1.json()["error"]["code"] == "AUTH_FORBIDDEN"

    resp2 = client.get("/api/v1/admin/logs", headers=AUTH_HEADER_A)
    assert resp2.status_code == 403
    assert resp2.json()["error"]["code"] == "AUTH_FORBIDDEN"


def test_isolation_case_7_user_a_pages_past_end_of_own_history(client: TestClient, seeded_db):
    """Case 7: User A pages past the end of their history -> Empty items, never a spill into others' rows."""
    resp = client.get("/api/v1/history?page=100&page_size=20", headers=AUTH_HEADER_A)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 3


def test_isolation_case_8_user_a_requests_nonexistent_prediction_id(client: TestClient, seeded_db):
    """Case 8: User A requests a non-existent prediction ID -> 404 INF_PREDICTION_NOT_FOUND (identical to Case 2)."""
    resp_nonexistent = client.get("/api/v1/results/999999", headers=AUTH_HEADER_A)
    assert resp_nonexistent.status_code == 404
    assert resp_nonexistent.json()["error"]["code"] == "INF_PREDICTION_NOT_FOUND"

    b_pred_id = seeded_db["b_preds"][0].prediction_id
    resp_case_2 = client.get(f"/api/v1/results/{b_pred_id}", headers=AUTH_HEADER_A)

    # Indistinguishable error code and HTTP status code prevents enumeration oracle
    assert resp_nonexistent.status_code == resp_case_2.status_code
    assert resp_nonexistent.json()["error"]["code"] == resp_case_2.json()["error"]["code"]
