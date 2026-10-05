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
                if "throttle" in r.event_detail or "invalidated" in r.event_detail]
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

def verify(email, code, purpose):
    return client.post("/api/v1/auth/otp/verify", json={"email": email, "otp": code, "purpose": purpose})


def test_fifth_wrong_code_invalidates_the_code(clock, codes):
    email = register()                       # registration challenge
    good = codes[-1]
    wrong = "000000" if good != "000000" else "111111"
    for attempt in range(throttle.OTP_MAX_WRONG):
        r = verify(email, wrong, "register")
        assert r.status_code == 401, (attempt, r.text)
    dead = verify(email, good, "register")
    assert dead.status_code == 401, "the right code must not work after 5 wrong ones"
    assert any("invalidated after" in d for d in throttle_rows())
    # /otp/send cannot revive it: no pending challenge -> nothing is sent.
    sent = len(codes)
    client.post("/api/v1/auth/otp/send", json={"email": email})
    assert len(codes) == sent
    # A new challenge needs the password again.
    assert login(email, PASSWORD).json()["requires_otp"] is True
    fresh = verify(email, codes[-1], "login")
    assert fresh.status_code == 200 and fresh.json()["token"]


def test_four_wrong_codes_then_the_right_one_still_works(clock, codes):
    email = register()
    good = codes[-1]
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(throttle.OTP_MAX_WRONG - 1):
        verify(email, wrong, "register")
    assert verify(email, good, "register").status_code == 200


# ---- /otp/send ---------------------------------------------------------------

def test_send_cooldown_and_hourly_cap_with_identical_answers(clock, codes):
    real, ghost = register(), f"ghost-{next(_n)}@example.com"  # real has a pending registration challenge
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
    assert len(throttle._pairs) <= 50 and len(throttle._accounts) <= 50


# ---- per-account counter (independent of the client address) ---------------------

def test_account_counter_catches_address_rotation_without_locking_out(clock):
    email = register()
    for i in range(throttle.ACCOUNT_FREE_FAILURES):  # one failure per address: no pair counter trips
        r = TestClient(app, client=(f"198.51.100.{i + 1}", 40000)).post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password-1"})
        assert r.status_code == 401
    fresh_ip = TestClient(app, client=("192.0.2.200", 40000))
    assert fresh_ip.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-1"}).status_code == 401
    blocked = fresh_ip.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "1"  # delay, not lockout
    clock.advance(1)
    ok = fresh_ip.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert ok.status_code == 200  # the owner gets in after the wait; success clears both counters
    assert not throttle._accounts.get(email.lower())


# ---- eviction: flooding other keys cannot reset an existing counter --------------

def test_flooding_other_keys_cannot_reset_an_active_counter(clock, monkeypatch):
    monkeypatch.setattr(throttle, "MAX_KEYS", 50)
    victim = throttle.login_key("victim@example.com", "203.0.113.5")
    for _ in range(throttle.PAIR_FREE_FAILURES + 3):  # victim's pair counter now enforces a delay
        throttle.login_failed(victim)
    before = list(throttle._pairs["victim@example.com|203.0.113.5"])
    for i in range(throttle.MAX_KEYS * 4):  # 200 fresh keys through a 50-key table
        throttle.login_failed(throttle.login_key(f"flood{i}@example.com", f"10.0.{i // 250}.{i % 250}"))
    assert throttle._pairs["victim@example.com|203.0.113.5"] == before
    with pytest.raises(throttle.RateLimited):
        throttle.check_login(victim)


def test_flooding_evicts_lighter_entries_before_a_heavier_one(clock, monkeypatch):
    """Below the delay threshold a counter is not protected outright, but fresh
    flood keys (1 failure) always go before it (2 failures)."""
    monkeypatch.setattr(throttle, "MAX_KEYS", 50)
    victim = throttle.login_key("slow@example.com", "203.0.113.6")
    throttle.login_failed(victim)
    throttle.login_failed(victim)
    for i in range(throttle.MAX_KEYS * 4):
        throttle.login_failed(throttle.login_key(f"f{i}@example.com", "10.1.1.1"))
    assert throttle._pairs["slow@example.com|203.0.113.6"][0] == 2


def test_a_table_full_of_active_delays_does_not_track_new_keys(clock, monkeypatch):
    monkeypatch.setattr(throttle, "MAX_KEYS", 5)
    for i in range(5):
        key = throttle.login_key(f"busy{i}@example.com", "10.2.2.2")
        for _ in range(throttle.PAIR_FREE_FAILURES + 1):
            throttle.login_failed(key)
    held = dict(throttle._pairs)
    throttle.login_failed(throttle.login_key("newcomer@example.com", "10.3.3.3"))
    assert dict(throttle._pairs) == held  # nobody evicted; the newcomer is simply not tracked
    assert any("table is full" in d for d in throttle_rows())


def test_untracked_keys_fall_back_to_per_ip_then_global_limits(clock, monkeypatch):
    """Table saturated with enforcing counters: newcomers are NOT unthrottled."""
    monkeypatch.setattr(throttle, "MAX_KEYS", 5)
    for i in range(5):  # fill every table with active delays
        key = throttle.login_key(f"busy{i}@example.com", f"10.9.9.{i}")
        for _ in range(throttle.ACCOUNT_FREE_FAILURES + 1):
            throttle.login_failed(key)
    for i in range(5):  # fallback-IP table full of active delays too
        for _ in range(throttle.FALLBACK_IP_FREE_FAILURES + 1):
            throttle.login_failed(throttle.login_key(f"x{i}@example.com", f"10.8.8.{i}"))
    # A newcomer whose own keys cannot be tracked is limited by the global window.
    newcomer = throttle.login_key("new@example.com", "10.7.7.7")
    for _ in range(throttle.GLOBAL_UNTRACKED_PER_MIN):
        throttle.login_failed(newcomer)
    with pytest.raises(throttle.RateLimited):
        throttle.check_login(newcomer)
    clock.advance(61)  # the window slides; nothing is locked for good
    throttle.check_login(newcomer)


def test_untracked_key_is_limited_per_ip_while_the_fallback_table_has_room(clock, monkeypatch):
    monkeypatch.setattr(throttle, "MAX_KEYS", 5)
    for i in range(5):
        key = throttle.login_key(f"busy{i}@example.com", f"10.9.9.{i}")
        for _ in range(throttle.ACCOUNT_FREE_FAILURES + 1):
            throttle.login_failed(key)
    newcomer = throttle.login_key("solo@example.com", "10.6.6.6")
    for _ in range(throttle.FALLBACK_IP_FREE_FAILURES + 1):
        throttle.login_failed(newcomer)
    assert "10.6.6.6" in throttle._fallback_ips and "solo@example.com|10.6.6.6" not in throttle._pairs
    with pytest.raises(throttle.RateLimited):
        throttle.check_login(newcomer)
