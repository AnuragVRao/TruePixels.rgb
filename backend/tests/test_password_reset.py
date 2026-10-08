"""Forgot password, reset and change (migration 0005).

A reset code is e-mailed, lives apart from the sign-in / registration
challenge, can only set a new password (never open a session), and both a
reset and a change end every existing session.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from app.m1_access import email_service, router_auth, throttle
from app.m1_access.models import PasswordReset, User
from app.m1_access.security import hash_password
from app.main import app
from app.shared.db import SessionLocal

client = TestClient(app)
_n = itertools.count()
PASSWORD = "ResetMe12345"
NEW = "BrandNew67890"


@pytest.fixture
def mailed(monkeypatch):
    """Capture (email, code) for reset and sign-in codes instead of delivering."""
    resets: list[tuple[str, str]] = []
    otps: list[tuple[str, str]] = []
    monkeypatch.setattr(email_service.EmailService, "send_password_reset_email",
                        staticmethod(lambda email, code, name=None: resets.append((email, code)) or True))
    monkeypatch.setattr(email_service.EmailService, "send_otp_email",
                        staticmethod(lambda email, code, name=None: otps.append((email, code)) or True))
    return resets, otps


def make_user(role="User", status="active") -> str:
    email = f"reset-{next(_n)}@example.com"
    with SessionLocal() as db:
        db.add(User(full_name="Reset", email=email, password_hash=hash_password(PASSWORD), role=role,
                    account_status=status, is_email_verified=True))
        db.commit()
    return email


def login(email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def token_for(email, password=PASSWORD) -> str:
    r = login(email, password)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def me(token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def forgot(email):
    return client.post("/api/v1/auth/password/forgot", json={"email": email})


def reset(email, code, new=NEW):
    return client.post("/api/v1/auth/password/reset", json={"email": email, "otp": code, "new_password": new})


def change(token, current=PASSWORD, new=NEW):
    return client.post("/api/v1/auth/password/change", json={"current_password": current, "new_password": new},
                       headers={"Authorization": f"Bearer {token}"})


# ---- forgot ------------------------------------------------------------------

def test_forgot_gives_the_same_answer_for_known_unknown_and_disabled_addresses(mailed):
    resets, _ = mailed
    known, disabled = make_user(), make_user(status="disabled")
    answers = {forgot(e).json()["message"] for e in (known, "nobody@example.com", disabled)}
    assert len(answers) == 1
    assert [e for e, _ in resets] == [known]  # only the active account got a code


def test_forgot_is_throttled_per_address(mailed):
    resets, _ = mailed
    email = make_user()
    assert forgot(email).status_code == 200 and forgot(email).status_code == 200
    assert len(resets) == 1  # the second request fell inside the 60 s cooldown


def test_forgot_in_production_without_email_delivery_is_refused_for_everyone(monkeypatch, mailed):
    monkeypatch.setenv("ENVIRONMENT", "production")
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)
    for email in (make_user(), "nobody@example.com"):
        r = forgot(email)
        assert r.status_code == 503 and r.json()["error"]["code"] == "OTP_DELIVERY_UNAVAILABLE"


# ---- reset -------------------------------------------------------------------

def test_reset_with_the_right_code_sets_the_password_and_ends_every_session(mailed):
    resets, _ = mailed
    email = make_user()
    old_token = token_for(email)
    forgot(email)
    r = reset(email, resets[-1][1])
    assert r.status_code == 200 and "token" not in r.json()  # no session from a reset
    assert login(email).status_code == 401
    assert login(email, NEW).status_code == 200
    assert me(old_token).status_code == 401
    with SessionLocal() as db:
        assert db.get(PasswordReset, db.query(User).filter(User.email == email).one().user_id) is None


def test_a_reset_code_works_once(mailed):
    resets, _ = mailed
    email = make_user()
    forgot(email)
    code = resets[-1][1]
    assert reset(email, code).status_code == 200
    assert reset(email, code, "AnotherOne13579").status_code == 401


def test_a_weak_new_password_is_refused_before_the_code_is_checked(mailed):
    resets, _ = mailed
    email = make_user()
    forgot(email)
    assert reset(email, resets[-1][1], "short").status_code == 422
    assert reset(email, resets[-1][1]).status_code == 200  # the code was not spent


def test_five_wrong_codes_kill_the_reset_code(mailed):
    resets, _ = mailed
    email = make_user()
    forgot(email)
    right = resets[-1][1]
    wrong = "111111" if right != "111111" else "222222"
    for _ in range(throttle.OTP_MAX_WRONG):
        r = reset(email, wrong)
        assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
    assert reset(email, right).status_code == 401
    assert login(email).status_code == 200  # password unchanged


def test_a_reset_code_never_opens_a_session_and_is_not_resent_by_otp_send(monkeypatch, mailed):
    resets, otps = mailed
    monkeypatch.setattr(router_auth, "REQUIRE_2FA", True, raising=False)
    email = make_user()
    forgot(email)
    code = resets[-1][1]
    for purpose in ("login", "register"):
        r = client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": code, "purpose": purpose})
        assert r.status_code == 401 and "token" not in r.text
    throttle.reset()  # clear the per-address send cooldown the forgot request used
    client.post("/api/v1/auth/otp/send", json={"email": email})
    assert otps == []  # a pending reset is not a sign-in challenge


def test_a_reset_request_does_not_replace_a_pending_sign_in_code(monkeypatch, mailed):
    resets, otps = mailed
    monkeypatch.setattr(router_auth, "REQUIRE_2FA", True, raising=False)
    email = make_user()
    assert login(email).json()["requires_otp"] is True
    forgot(email)
    r = client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": otps[-1][1], "purpose": "login"})
    assert r.status_code == 200 and r.json()["token"]


def test_a_disabled_account_cannot_reset(mailed):
    resets, _ = mailed
    email = make_user()
    forgot(email)
    with SessionLocal() as db:
        db.query(User).filter(User.email == email).one().account_status = "disabled"
        db.commit()
    r = reset(email, resets[-1][1])
    assert r.status_code == 403 and r.json()["error"]["code"] == "AUTH_ACCOUNT_DISABLED"


# ---- change ------------------------------------------------------------------

def test_change_password_returns_a_working_token_and_ends_other_sessions():
    email = make_user()
    this_tab, other_tab = token_for(email), token_for(email)
    r = change(this_tab)
    assert r.status_code == 200, r.text
    fresh = r.json()["token"]
    assert me(fresh).status_code == 200
    assert me(this_tab).status_code == 401 and me(other_tab).status_code == 401
    assert login(email).status_code == 401 and login(email, NEW).status_code == 200


def test_change_password_needs_the_current_password_and_is_throttled():
    email = make_user()
    token = token_for(email)
    statuses = [change(token, current="WrongGuess12345").status_code for _ in range(8)]
    assert statuses[0] == 400  # not 401: the session is fine, and a 401 would sign the client out
    assert 429 in statuses  # guesses through a session slow down like sign-in
    assert me(token).status_code == 200  # nothing changed


@pytest.mark.parametrize("new,why", [(PASSWORD, "same"), ("short", "weak")])
def test_change_password_refuses_a_same_or_weak_password(new, why):
    email = make_user()
    r = change(token_for(email), new=new)
    assert r.status_code == 422 and r.json()["error"]["code"] == "AUTH_WEAK_PASSWORD"  # readable in the UI


def test_change_password_needs_a_session():
    assert client.post("/api/v1/auth/password/change",
                       json={"current_password": PASSWORD, "new_password": NEW}).status_code == 401
