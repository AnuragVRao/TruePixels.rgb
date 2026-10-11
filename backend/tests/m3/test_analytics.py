"""
Unit & Integration Tests for Module M3 Admin Dashboard and System Analytics (F.16, F.17, F.18, F.19).
"""
from __future__ import annotations
from fastapi.testclient import TestClient

AUTH_ADMIN = {"Authorization": "Bearer test-admin-token-1"}


def test_admin_summary_endpoint(client: TestClient, seeded_db):
    """Validates Admin Dashboard summary metrics."""
    resp = client.get("/api/v1/admin/summary", headers=AUTH_ADMIN)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_predictions"] == 5  # 3 from A + 2 from B
    assert "Real" in data["class_distribution"]
    assert "AI Generated" in data["class_distribution"]
    assert len(data["active_models"]) >= 1


def test_admin_logs_filtering_and_pagination(client: TestClient, seeded_db):
    """Validates admin log explorer filtering by event_type and severity."""
    resp = client.get("/api/v1/admin/logs?page=1&page_size=10", headers=AUTH_ADMIN)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


def test_admin_analytics_confidence_histogram(client: TestClient, seeded_db):
    """Ten 5-point bins from 50% (confidence in the predicted class is never
    below one half); every prediction is counted exactly once."""
    resp = client.get("/api/v1/admin/analytics?days=30", headers=AUTH_ADMIN)
    assert resp.status_code == 200
    data = resp.json()
    bins = [b for b in data["confidence_distribution"] if b["bin_range"] != "under 50%"]
    assert [b["bin_range"] for b in bins] == [f"{lo}-{lo + 5}%" for lo in range(50, 100, 5)]
    assert sum(b["count"] for b in data["confidence_distribution"]) == data["total_predictions"] == 5


def test_admin_user_account_status_change(client: TestClient, seeded_db):
    """Validates admin enabling, disabling, or removing a user account."""
    user_a_id = seeded_db["user_a"].user_id
    resp = client.patch(
        f"/api/v1/admin/users/{user_a_id}/status",
        json={"action": "disable"},
        headers=AUTH_ADMIN,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_status"] == "disabled"


def test_admin_cannot_disable_own_account(client: TestClient, seeded_db):
    """Validates policy check preventing an admin from disabling or removing their own account."""
    admin_id = seeded_db["admin"].user_id
    resp = client.patch(
        f"/api/v1/admin/users/{admin_id}/status",
        json={"action": "disable"},
        headers=AUTH_ADMIN,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ADM_ACTION_NOT_PERMITTED"
