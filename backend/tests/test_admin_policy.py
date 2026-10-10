"""Phase 5b: account-status policy and warm-only latency analytics.

The UI hides some of these actions; these tests prove the API refuses them
regardless (both M1's /users and M3's /admin/users endpoints).
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.m1_access.account_policy import apply_status_change
from app.m1_access.models import Image, User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis.models import ModelRegistry, Prediction
from app.m3_results.analytics import _percentile, latency_stats
from app.main import app
from app.shared.db import SessionLocal
from app.shared.errors import AppException

client = TestClient(app)
_emails = itertools.count()
ENDPOINTS = ("/api/v1/users/{id}/status", "/api/v1/admin/users/{id}/status")


def make_user(role: str = "User", status: str = "active") -> tuple[int, dict[str, str]]:
    db = SessionLocal()
    try:
        user = User(full_name="Policy Test", email=f"policy-{next(_emails)}@example.com",
                    password_hash=hash_password("PolicyTest12345"), role=role,
                    account_status=status, is_email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        token, _, _ = create_session_token(user)
        return user.user_id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def status_of(user_id: int) -> str:
    db = SessionLocal()
    try:
        return db.get(User, user_id).account_status
    finally:
        db.close()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("action", ["disable"])
def test_admin_cannot_disable_themselves(endpoint, action):
    admin_id, headers = make_user("Admin")
    make_user("Admin")  # another admin exists, so only the self rule can refuse
    r = client.patch(endpoint.format(id=admin_id), headers=headers, json={"action": action})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ADM_ACTION_NOT_PERMITTED"
    assert status_of(admin_id) == "active"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_missing_user_is_user_not_found(endpoint):
    _, headers = make_user("Admin")
    r = client.patch(endpoint.format(id=987654), headers=headers, json={"action": "disable"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_admin_can_disable_another_admin_while_one_remains(endpoint):
    _, headers = make_user("Admin")
    other_id, _ = make_user("Admin")
    r = client.patch(endpoint.format(id=other_id), headers=headers, json={"action": "disable"})
    assert r.status_code == 200, r.text
    assert status_of(other_id) == "disabled"


def test_last_active_admin_cannot_be_disabled():
    """Not reachable over HTTP (the actor is itself an active admin and cannot
    target itself), so the invariant is asserted on the shared policy, which
    both endpoints call."""
    last_id, _ = make_user("Admin")
    make_user("Admin", status="disabled")  # inactive admins do not count
    actor_id, _ = make_user("User")
    db = SessionLocal()
    try:
        # Only active admins count: here `last_id` is the only one.
        assert db.query(User).filter(User.role == "Admin", User.account_status == "active").count() == 1
        for action in ("disable",):
            with pytest.raises(AppException) as exc:
                apply_status_change(db, actor_id, last_id, action)
            assert exc.value.code == "ADM_ACTION_NOT_PERMITTED"
        db.rollback()
        assert db.get(User, last_id).account_status == "active"
        # Enabling is never blocked by the invariant.
        disabled_admin = db.query(User).filter(User.role == "Admin", User.account_status == "disabled").first()
        apply_status_change(db, actor_id, disabled_admin.user_id, "enable")
        db.rollback()
    finally:
        db.close()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_remove_action_no_longer_exists(endpoint):
    """'remove' did exactly what 'disable' does, so it was dropped (2026-10-10)."""
    _, admin = make_user("Admin")
    user_id, _ = make_user("User")
    r = client.patch(endpoint.format(id=user_id), headers=admin, json={"action": "remove"})
    assert r.status_code == 422, r.text
    assert status_of(user_id) == "active"


def test_legacy_removed_account_stays_blocked_and_can_be_enabled():
    """Rows marked 'removed' before the action was dropped keep working as before."""
    _, admin = make_user("Admin")
    user_id, user_headers = make_user("User", status="removed")
    assert client.get("/api/v1/auth/me", headers=user_headers).status_code == 403
    r = client.patch(f"/api/v1/admin/users/{user_id}/status", headers=admin, json={"action": "enable"})
    assert r.status_code == 200 and r.json()["account_status"] == "active"
    assert client.get("/api/v1/auth/me", headers=user_headers).status_code == 200


def test_disabled_user_keeps_data_but_loses_access():
    """'Disable' is a soft state change: sessions stop working, data stays."""
    _, admin = make_user("Admin")
    user_id, user_headers = make_user("User")
    db = SessionLocal()
    try:
        db.add(Image(user_id=user_id, file_reference="uploads/kept.png", content_sha256="0" * 64,
                     file_format="PNG", file_size=10, width=64, height=64, validation_status="valid"))
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/auth/me", headers=user_headers).status_code == 200
    r = client.patch(f"/api/v1/admin/users/{user_id}/status", headers=admin, json={"action": "disable"})
    assert r.status_code == 200 and r.json()["account_status"] == "disabled"
    assert client.get("/api/v1/auth/me", headers=user_headers).status_code == 403
    db = SessionLocal()
    try:
        assert db.query(Image).filter(Image.user_id == user_id).count() == 1
    finally:
        db.close()
    r = client.patch(f"/api/v1/admin/users/{user_id}/status", headers=admin, json={"action": "enable"})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=user_headers).status_code == 200


def test_percentile_matches_linear_interpolation():
    assert _percentile([], 0.5) is None
    assert _percentile([7], 0.95) == 7.0
    assert _percentile([10, 20, 30, 40], 0.5) == 25.0
    assert _percentile(list(range(1, 101)), 0.95) == pytest.approx(95.05)


def test_latency_excludes_cold_and_unknown_rows():
    user_id, _ = make_user("User")
    db = SessionLocal()
    try:
        image = Image(user_id=user_id, file_reference="uploads/l.png", content_sha256="1" * 64,
                      file_format="PNG", file_size=10, width=64, height=64, validation_status="valid")
        db.add(image)
        model = db.query(ModelRegistry).first()
        if model is None:
            model = ModelRegistry(model_name="latency test", model_version="t", model_type="fusion-configuration",
                                  artifact_ref="test", is_active=False)
            db.add(model)
        db.flush()
        now = datetime.now(timezone.utc)
        rows = [(100, False), (200, False), (300, False), (9000, True), (5000, None)]
        for latency, cold in rows:
            db.add(Prediction(image_id=image.image_id, model_id=model.model_id, semantic_score=0.1,
                              frequency_score=0.1, fusion_score=0.1, predicted_class="Real",
                              confidence_score=0.9, latency_ms=latency, cold_start=cold,
                              prediction_timestamp=now))
        db.commit()
        summary, points = latency_stats(db, now - timedelta(days=1))
    finally:
        db.close()
    assert (summary.warm_count, summary.cold_count, summary.unknown_count) == (3, 1, 1)
    assert summary.p50_ms == 200.0
    assert summary.p95_ms == pytest.approx(290.0)
    assert len(points) == 1 and points[0].warm_count == 3


def test_analytics_endpoint_reports_null_latency_without_warm_rows():
    _, admin = make_user("Admin")
    r = client.get("/api/v1/admin/analytics?days=7", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7
    assert body["latency"]["warm_count"] == 0
    assert body["latency"]["p50_ms"] is None and body["latency"]["p95_ms"] is None
