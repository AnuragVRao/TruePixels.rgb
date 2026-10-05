"""OTP is a second factor, never an email-only sign-in (Phase 6-pre, changes.md 6.15).

Codes exist only inside a challenge created by a correct password ('login')
or by registration ('register', role User); purposes and accounts are not
interchangeable; with 2FA off the OTP endpoints are refused; in production
no code is issued without real e-mail delivery.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from app.m1_access import email_service, router_auth
from app.m1_access.models import User
from app.m1_access.security import hash_password
from app.main import app
from app.shared.db import SessionLocal

client = TestClient(app)
_n = itertools.count()
PASSWORD = "OtpChallenge12345"


@pytest.fixture
def sent(monkeypatch):
    """2FA on; capture (email, code) instead of delivering."""
    out: list[tuple[str, str]] = []
    monkeypatch.setattr(router_auth, "REQUIRE_2FA", True, raising=False)
    monkeypatch.setattr(email_service.EmailService, "send_otp_email",
                        staticmethod(lambda email, code, name=None: out.append((email, code)) or True))
    return out


def make_user(role="User") -> str:
    email = f"otp-{next(_n)}@example.com"
    db = SessionLocal()
    try:
        db.add(User(full_name="Otp", email=email, password_hash=hash_password(PASSWORD), role=role,
                    account_status="active", is_email_verified=True))
        db.commit()
    finally:
        db.close()
    return email


def row(email) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).one()
    finally:
        db.close()


def send(email):
    return client.post("/api/v1/auth/otp/send", json={"email": email})


def verify(email, code, purpose="login"):
    return client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": code, "purpose": purpose})


def login(email, admin=False):
    path = "/api/v1/auth/admin/login" if admin else "/api/v1/auth/login"
    return client.post(path, json={"email": email, "password": PASSWORD})


# ---- email-only paths are closed ---------------------------------------------

@pytest.mark.parametrize("role", ["User", "Admin"])
def test_email_only_send_creates_no_code_and_verify_is_refused(sent, role):
    email = make_user(role)
    assert send(email).status_code == 200            # same answer as always...
    assert sent == [] and row(email).otp_hash is None  # ...but nothing was issued
    for purpose in ("login", "register"):
        for guess in ("000000", "123456"):
            r = verify(email, guess, purpose)
            assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
            assert "token" not in r.text


@pytest.mark.parametrize("role", ["User", "Admin"])
def test_otp_endpoints_are_refused_entirely_with_2fa_off(monkeypatch, role):
    monkeypatch.setattr(router_auth, "REQUIRE_2FA", False, raising=False)
    email = make_user(role)
    for r in (send(email), verify(email, "123456", "login"), verify(email, "123456", "register")):
        assert r.status_code == 403 and r.json()["error"]["code"] == "AUTH_FORBIDDEN", r.text


def test_admin_session_never_comes_from_an_email_only_path(sent):
    email = make_user("Admin")
    send(email)
    assert verify(email, "000000").status_code == 401
    # Even a registration-purpose challenge on an Admin row (impossible via the
    # API - registration creates Users) is refused, with the correct code.
    from app.m1_access import otp_challenge
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        user.role = "User"
        otp_challenge.issue(db, user, "register")
        user.role = "Admin"
        db.commit()
    finally:
        db.close()
    r = verify(email, sent[-1][1], "register")
    assert r.status_code == 401 and "token" not in r.text


def test_password_then_code_still_works_for_users_and_admins(sent):
    for role, admin in (("User", False), ("Admin", True)):
        email = make_user(role)
        assert login(email, admin).json()["requires_otp"] is True
        assert row(email).otp_purpose == "login"
        r = verify(email, sent[-1][1], "login")
        assert r.status_code == 200 and r.json()["role"] == role
        assert row(email).otp_hash is None and row(email).otp_purpose is None  # consumed
        assert verify(email, sent[-1][1], "login").status_code == 401        # single use


def test_registration_code_is_redeemable_for_registration_only(sent):
    email = f"reg-{next(_n)}@example.com"
    r = client.post("/api/v1/auth/register", json={"full_name": "Reg", "email": email, "password": PASSWORD})
    assert r.status_code == 201 and r.json()["requires_2fa"] is True
    code = sent[-1][1]
    assert row(email).otp_purpose == "register"
    assert verify(email, code, "login").status_code == 401          # cross-purpose refused...
    ok = verify(email, code, "register")                             # ...right purpose works
    assert ok.status_code == 200 and ok.json()["role"] == "User"


def test_login_code_is_not_redeemable_as_registration(sent):
    email = make_user()
    login(email)
    code = sent[-1][1]
    assert verify(email, code, "register").status_code == 401
    assert verify(email, code, "login").status_code == 200          # the mismatch did not consume it


def test_one_accounts_code_cannot_be_redeemed_for_another(sent):
    a, b = make_user(), make_user()
    login(a)
    code_a = sent[-1][1]
    login(b)
    code_b = sent[-1][1]
    if code_a == code_b:  # 1 in 900,000 - make the case meaningful
        login(b)
        code_b = sent[-1][1]
    assert verify(b, code_a, "login").status_code == 401
    assert verify(a, code_b, "login").status_code == 401
    assert verify(a, code_a, "login").status_code == 200
    assert verify(b, code_b, "login").status_code == 200


def test_send_resends_only_a_pending_challenge_with_its_own_purpose(sent):
    email = make_user()
    login(email)
    first = sent[-1][1]
    send(email)
    second = sent[-1][1]
    assert row(email).otp_purpose == "login" and len(sent) == 2
    assert verify(email, second, "login").status_code == 200 or first == second


# ---- production delivery ----------------------------------------------------------

def test_production_refuses_to_issue_codes_without_real_email(monkeypatch, capsys):
    monkeypatch.setattr(router_auth, "REQUIRE_2FA", True, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    email = make_user()
    r = login(email)
    assert r.status_code == 503 and r.json()["error"]["code"] == "OTP_DELIVERY_UNAVAILABLE"
    assert row(email).otp_hash is None
    new = f"prod-{next(_n)}@example.com"
    reg = client.post("/api/v1/auth/register", json={"full_name": "Prod", "email": new, "password": PASSWORD})
    assert reg.status_code == 503
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == new).count() == 0  # refused before creating it
    finally:
        db.close()
    assert "code=" not in capsys.readouterr().out


def test_production_never_falls_back_to_console_when_smtp_fails(monkeypatch, capsys):
    """SMTP 'configured' but failing: no console code, challenge cleared, 503."""
    import smtplib

    monkeypatch.setattr(router_auth, "REQUIRE_2FA", True, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    for key, value in {"EMAIL_BACKEND": "smtp", "SMTP_HOST": "smtp.invalid", "SMTP_USER": "u",
                       "SMTP_PASSWORD": "p", "SMTP_FROM": "noreply@example.com"}.items():
        monkeypatch.setenv(key, value)

    def refuse(*_a, **_k):
        raise OSError("no network in tests")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    monkeypatch.setattr(smtplib, "SMTP_SSL", refuse)
    email = make_user()
    r = login(email)
    assert r.status_code == 503 and r.json()["error"]["code"] == "OTP_DELIVERY_UNAVAILABLE"
    assert row(email).otp_hash is None and row(email).otp_purpose is None
    assert "code=" not in capsys.readouterr().out
