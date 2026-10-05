"""Sign-in and OTP throttling (Phase 6-pre). Injectable clock - no sleeps.

The TestClient's client address is "testclient"; X-Forwarded-For is NOT
honoured here (no trusted proxy), which the spoofing test relies on.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from app.m1_access import email_service, router_auth, throttle
from app.m3_results.models import LogEntry
from app.main import app
from app.shared.db import SessionLocal

client = TestClient(app)
_n = itertools.count()
PASSWORD = "Throttle12345"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(throttle, "clock", fake)
    return fake


@pytest.fixture
def codes(monkeypatch):
    """Capture issued OTP codes; 2FA on, nothing actually delivered."""
    issued: list[str] = []
    monkeypatch.setattr(router_auth, "REQUIRE_2FA", True, raising=False)
    monkeypatch.setattr(email_service.EmailService, "send_otp_email",
                        staticmethod(lambda email, code, name=None: issued.append(code) or True))
    return issued


def register(email=None) -> str:
    email = email or f"thr-{next(_n)}@example.com"
    r = client.post("/api/v1/auth/register", json={"full_name": "Throttle", "email": email, "password": PASSWORD})
    assert r.status_code in (200, 201), r.text
    return email


def login(email, password, **kw):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, **kw)


def throttle_rows() -> list[str]:
    db = SessionLocal()
    try:
        return [r.event_detail for r in db.query(LogEntry)
                if "throttled" in r.event_detail or "invalidated" in r.event_detail]
    finally:
        db.close()


# ---- sign-in ---------------------------------------------------------------

def test_login_delay_grows_and_never_locks_out(clock):
    email = register()
    for _ in range(throttle.LOGIN_FREE_FAILURES):  # free failures
        assert login(email, "wrong-password-1").status_code == 401
    for wait in [1, 2, 4, 8]:
        assert login(email, "wrong-password-1").status_code == 401   # this failure sets the wait
        blocked = login(email, PASSWORD)                              # even the right password must wait
        assert blocked.status_code == 429, blocked.text
        assert blocked.json()["error"]["code"] == "AUTH_RATE_LIMITED"
        assert blocked.headers["Retry-After"] == str(wait)
        clock.advance(wait)
    ok = login(email, PASSWORD)  # no lockout: after the wait the right password works
    assert ok.status_code == 200 and ok.json()["token"]
    assert login(email, "wrong-password-1").status_code == 401  # success cleared the counter


def test_login_delay_is_capped(clock):
    email = register()
    for _ in range(throttle.LOGIN_FREE_FAILURES + 12):
        login(email, "nope-nope-1")
        clock.advance(throttle.LOGIN_MAX_DELAY_S)
    login(email, "nope-nope-1")
    r = login(email, PASSWORD)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) <= throttle.LOGIN_MAX_DELAY_S


def test_unknown_email_is_throttled_exactly_like_a_real_one(clock):
    real, ghost = register(), f"ghost-{next(_n)}@example.com"
    answers = {}
    for email in (real, ghost):
        seq = [login(email, "wrong-password-1") for _ in range(throttle.LOGIN_FREE_FAILURES + 2)]
        answers[email] = [(r.status_code, r.json()["error"]["code"], r.headers.get("Retry-After")) for r in seq]
    assert answers[real] == answers[ghost]
    assert answers[real][-1][0] == 429


def test_admin_login_shares_the_counter(clock):
    email = register()
    for _ in range(throttle.LOGIN_FREE_FAILURES + 1):
        client.post("/api/v1/auth/admin/login", json={"email": email, "password": "wrong-password-1"})
    assert login(email, PASSWORD).status_code == 429


def test_key_includes_the_client_address_and_ignores_spoofed_forwarded_for(clock):
    email = register()
    for _ in range(throttle.LOGIN_FREE_FAILURES + 1):
        login(email, "wrong-password-1")
    # A forged X-Forwarded-For from a direct client does not change the key.
    assert login(email, PASSWORD, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429
    # Another (resolved) client address is a different key.
    other = TestClient(app, client=("198.51.100.7", 50000))
    assert other.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_throttle_events_reach_d6_at_most_once_per_minute_per_key(clock):
    email = register()
    for _ in range(throttle.LOGIN_FREE_FAILURES + 1):
        login(email, "wrong-password-1")
    for _ in range(20):
        assert login(email, PASSWORD).status_code == 429
    assert len([d for d in throttle_rows() if "Sign-in throttled" in d]) == 1
    clock.advance(throttle.LOG_INTERVAL_S + 1)
    login(email, "wrong-password-1")
    assert login(email, PASSWORD).status_code == 429
    assert len([d for d in throttle_rows() if "Sign-in throttled" in d]) == 2


# ---- OTP codes --------------------------------------------------------------

def test_fifth_wrong_code_invalidates_the_code(clock, codes):
    email = register()
    good = codes[-1]
    wrong = "000000" if good != "000000" else "111111"
    for attempt in range(throttle.OTP_MAX_WRONG):
        r = client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": wrong})
        assert r.status_code == 401, (attempt, r.text)
    dead = client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": good})
    assert dead.status_code == 401, "the right code must not work after 5 wrong ones"
    assert any("invalidated after" in d for d in throttle_rows())
    client.post("/api/v1/auth/otp/send", json={"email": email})
    fresh = client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": codes[-1]})
    assert fresh.status_code == 200 and fresh.json()["token"]


def test_four_wrong_codes_then_the_right_one_still_works(clock, codes):
    email = register()
    good = codes[-1]
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(throttle.OTP_MAX_WRONG - 1):
        client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": wrong})
    assert client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": good}).status_code == 200


# ---- /otp/send ---------------------------------------------------------------

def test_send_cooldown_and_hourly_cap_with_identical_answers(clock, codes):
    real, ghost = register(), f"ghost-{next(_n)}@example.com"
    sent_before = len(codes)
    bodies = set()
    for email in (real, ghost):
        r1 = client.post("/api/v1/auth/otp/send", json={"email": email})
        r2 = client.post("/api/v1/auth/otp/send", json={"email": email})  # inside the cooldown
        bodies |= {(r1.status_code, r1.text), (r2.status_code, r2.text)}
    assert len(bodies) == 1, bodies                     # one answer for all four
    assert len(codes) == sent_before + 1                 # only the real, un-throttled send went out
    for _ in range(10):                                  # hourly cap
        clock.advance(throttle.SEND_COOLDOWN_S)
        client.post("/api/v1/auth/otp/send", json={"email": real})
    assert len(codes) == sent_before + throttle.SEND_HOURLY_CAP
    clock.advance(3600)
    client.post("/api/v1/auth/otp/send", json={"email": real})
    assert len(codes) == sent_before + throttle.SEND_HOURLY_CAP + 1


def test_send_throttle_logs_once_per_minute(clock, codes):
    email = register()
    for _ in range(30):
        client.post("/api/v1/auth/otp/send", json={"email": email})
    assert len([d for d in throttle_rows() if "OTP send throttled" in d]) == 1


def test_memory_is_bounded(clock, monkeypatch):
    monkeypatch.setattr(throttle, "MAX_KEYS", 50)
    for i in range(500):
        throttle.login_failed(throttle.login_key(f"spray{i}@example.com", "203.0.113.1"))
    assert len(throttle._login) <= 50
