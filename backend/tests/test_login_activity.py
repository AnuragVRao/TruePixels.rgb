"""Login activity (migration 0005): every sign-in attempt and password change
is recorded with time, outcome, portal, client address and browser. A user
sees their own rows; an administrator sees every row."""

from __future__ import annotations

import itertools
import typing

import pytest
from fastapi.testclient import TestClient

from app.m1_access import email_service, login_activity, router_auth
from app.m1_access.models import LOGIN_OUTCOMES, LoginEvent, User
from app.m1_access.security import hash_password
from app.m3_results.router_admin import LoginOutcome
from app.main import app
from app.shared.db import SessionLocal

client = TestClient(app)
_n = itertools.count()
PASSWORD = "Activity12345"
UA = {"User-Agent": "Mozilla/5.0 (TestBrowser) TruePixelsTest/1.0"}


def make_user(role="User", status="active") -> str:
    email = f"act-{next(_n)}@example.com"
    with SessionLocal() as db:
        db.add(User(full_name="Act", email=email, password_hash=hash_password(PASSWORD), role=role,
                    account_status=status, is_email_verified=True))
        db.commit()
    return email


def login(email, password=PASSWORD, admin=False):
    path = "/api/v1/auth/admin/login" if admin else "/api/v1/auth/login"
    return client.post(path, json={"email": email, "password": password}, headers=UA)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def events(email=None) -> list[LoginEvent]:
    with SessionLocal() as db:
        q = db.query(LoginEvent)
        if email:
            q = q.filter(LoginEvent.email == email)
        return q.order_by(LoginEvent.event_id).all()


def test_every_sign_in_outcome_is_recorded_with_address_and_browser():
    user, admin, disabled = make_user(), make_user("Admin"), make_user(status="disabled")
    login(user, "WrongPassword123")
    login(user)
    login("ghost@example.com")
    login(disabled)
    login(user, admin=True)
    login(admin, admin=True)
    seen = [(e.email, e.portal, e.outcome) for e in events()]
    assert seen == [
        (user, "user", "wrong_password"),
        (user, "user", "success"),
        ("ghost@example.com", "user", "unknown_account"),
        (disabled, "user", "account_disabled"),
        (user, "admin", "not_admin"),
        (admin, "admin", "success"),
    ]
    for e in events():
        assert e.ip_address == "testclient" and e.user_agent == UA["User-Agent"]
        assert (e.user_id is None) == (e.email == "ghost@example.com")


def test_two_factor_sign_in_records_the_code_step(monkeypatch):
    codes: list[str] = []
    monkeypatch.setattr(router_auth, "REQUIRE_2FA", True, raising=False)
    monkeypatch.setattr(email_service.EmailService, "send_otp_email",
                        staticmethod(lambda email, code, name=None: codes.append(code) or True))
    email = make_user()
    login(email)
    wrong = "111111" if codes[-1] != "111111" else "222222"
    client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": wrong, "purpose": "login"}, headers=UA)
    client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": codes[-1], "purpose": "login"}, headers=UA)
    assert [e.outcome for e in events(email)] == ["otp_sent", "otp_failed", "success"]


def test_a_user_sees_only_their_own_activity():
    mine, theirs = make_user(), make_user()
    login(theirs, "WrongPassword123")
    token = login(mine).json()["token"]
    r = client.get("/api/v1/users/me/login-activity", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and {i["email"] for i in body["items"]} == {mine}
    assert body["items"][0]["outcome"] == "success" and body["items"][0]["user_agent"] == UA["User-Agent"]


def test_own_activity_needs_a_session():
    assert client.get("/api/v1/users/me/login-activity").status_code == 401


def test_password_change_is_recorded():
    email = make_user()
    token = login(email).json()["token"]
    client.post("/api/v1/auth/password/change", headers={**auth(token), **UA},
                json={"current_password": PASSWORD, "new_password": "Changed24680"})
    assert [e.outcome for e in events(email)] == ["success", "password_changed"]


def test_admin_sees_everyone_with_filters_and_users_are_refused():
    user, admin = make_user(), make_user("Admin")
    login("ghost@example.com")
    user_token = login(user).json()["token"]
    admin_token = login(admin, admin=True).json()["token"]

    r = client.get("/api/v1/admin/login-activity", headers=auth(admin_token))
    assert r.status_code == 200
    assert {i["email"] for i in r.json()["items"]} == {"ghost@example.com", user, admin}

    r = client.get("/api/v1/admin/login-activity", params={"outcome": "unknown_account"}, headers=auth(admin_token))
    assert [i["email"] for i in r.json()["items"]] == ["ghost@example.com"]
    r = client.get("/api/v1/admin/login-activity", params={"email": user[:8]}, headers=auth(admin_token))
    assert {i["email"] for i in r.json()["items"]} == {user}
    assert client.get("/api/v1/admin/login-activity", params={"outcome": "bogus"},
                      headers=auth(admin_token)).status_code == 422

    assert client.get("/api/v1/admin/login-activity", headers=auth(user_token)).status_code == 403


def test_pagination_is_newest_first():
    email = make_user()
    for _ in range(3):
        login(email, "WrongPassword123")
    token = login(email).json()["token"]
    r = client.get("/api/v1/users/me/login-activity", params={"page_size": 2}, headers=auth(token)).json()
    assert r["total"] == 4 and r["total_pages"] == 2
    assert [i["outcome"] for i in r["items"]] == ["success", "wrong_password"]


def test_a_recorder_failure_never_breaks_sign_in(monkeypatch, capsys):
    email = make_user()

    class Broken:
        def __call__(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(login_activity, "SessionLocal", Broken())
    assert login(email).status_code == 200
    assert "LOGIN-ACTIVITY-FAIL" in capsys.readouterr().err


def test_old_rows_are_purged():
    from datetime import datetime, timedelta, timezone

    email = make_user()
    login(email)
    with SessionLocal() as db:
        db.query(LoginEvent).update({LoginEvent.created_at: datetime.now(timezone.utc) - timedelta(days=91)})
        db.commit()
        login(email)
        assert login_activity.purge_older_than(db) == 1
    assert len(events(email)) == 1


def test_admin_filter_values_match_the_recorded_outcomes():
    assert set(typing.get_args(LoginOutcome)) == set(LOGIN_OUTCOMES)
