"""Brute-force throttling for sign-in and OTP (Phase 6-pre, changes.md 6.13).

Three limits, all IN MEMORY in this process. They reset on restart, and with
more than one worker each worker counts separately (the app runs one worker
deliberately: the GPU). That is enough to stop online guessing at the rate
the API can serve; it is not a distributed rate limiter.

* Sign-in (``/auth/login`` and ``/auth/admin/login`` share the counter):
  keyed by (normalised email, client IP). The first ``LOGIN_FREE_FAILURES``
  failures cost nothing; each later failure makes the key wait
  1, 2, 4, ... up to ``LOGIN_MAX_DELAY_S`` seconds before the next attempt is
  even checked (429 ``AUTH_RATE_LIMITED`` with Retry-After). There is no hard
  lockout: after the wait one more attempt is allowed, so an attacker
  cannot lock a real user out for long. A successful sign-in clears the key.
* OTP codes: ``OTP_MAX_WRONG`` wrong codes invalidate the code (the caller
  must request a new one). Counted per account; reset whenever a new code
  is issued.
* ``/auth/otp/send``: keyed by the normalised email WHETHER OR NOT the account
  exists - a cooldown of ``SEND_COOLDOWN_S`` between sends and at most
  ``SEND_HOURLY_CAP`` per rolling hour. A throttled request gets the same
  200 answer as a successful one; it just sends nothing.

The client IP is ``request.client.host`` - the address uvicorn resolved,
which honours X-Forwarded-For ONLY from the proxy addresses given to
``--forwarded-allow-ips``. Never read X-Forwarded-For here directly.

Throttle events are logged to D6 at most once per ``LOG_INTERVAL_S`` per key,
so a guessing run cannot flood the audit log. Memory is bounded: at most
``MAX_KEYS`` keys per table, expired entries pruned first.

``clock`` is injectable (tests replace it; nothing here sleeps).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Callable

from app.shared.errors import AppException
from app.shared.logging import emit

LOGIN_FREE_FAILURES = 3
LOGIN_MAX_DELAY_S = 60.0
LOGIN_FORGET_AFTER_S = 15 * 60  # an idle key starts again from zero
OTP_MAX_WRONG = 5
SEND_COOLDOWN_S = 60.0
SEND_HOURLY_CAP = 5
LOG_INTERVAL_S = 60.0
MAX_KEYS = 10_000

clock: Callable[[], float] = time.monotonic
_lock = threading.Lock()


class RateLimited(AppException):
    def __init__(self, retry_after: float):
        seconds = max(1, int(retry_after + 0.999))
        super().__init__(code="AUTH_RATE_LIMITED", status_code=429,
                         message=f"Too many attempts. Try again in {seconds} s.")
        self.headers = {"Retry-After": str(seconds)}


class _Table(OrderedDict):
    """Bounded per-key state; least recently touched keys go first."""

    def touch(self, key, default_factory, expired: Callable[[object], bool]):
        if key in self:
            self.move_to_end(key)
            return self[key]
        if len(self) >= MAX_KEYS:
            for stale in [k for k, v in self.items() if expired(v)]:
                del self[stale]
            while len(self) >= MAX_KEYS:
                self.popitem(last=False)
        self[key] = default_factory()
        return self[key]


_login = _Table()      # key -> [failures, next_allowed, last_seen]
_otp_wrong = _Table()  # user_id -> wrong count for the current code
_sends = _Table()      # email -> deque of send times (last hour)
_logged = _Table()     # key -> last D6 log time


def reset() -> None:
    """Tests only."""
    with _lock:
        for table in (_login, _otp_wrong, _sends, _logged):
            table.clear()


def _log_once(key: str, detail: str, user_id: int | None = None) -> None:
    now = clock()
    with _lock:
        last = _logged.touch(key, lambda: None, lambda v: v is None or now - v > LOG_INTERVAL_S)
        if last is not None and now - last < LOG_INTERVAL_S:
            return
        _logged[key] = now
    emit("authentication", detail, severity="warning", user_id=user_id)


# ---- sign-in --------------------------------------------------------------

def login_key(email: str, client_ip: str | None) -> str:
    return f"{email.strip().lower()}|{client_ip or 'unknown'}"


def check_login(key: str) -> None:
    """Raise RateLimited if this key must still wait."""
    now = clock()
    with _lock:
        state = _login.get(key)
        if state and now - state[2] > LOGIN_FORGET_AFTER_S:
            del _login[key]
            state = None
        wait = state[1] - now if state else 0.0
    if wait > 0:
        _log_once(f"login:{key}", f"Sign-in throttled ({state[0]} recent failures) for {key}")
        raise RateLimited(wait)


def login_failed(key: str) -> None:
    now = clock()
    with _lock:
        state = _login.touch(key, lambda: [0, 0.0, now],
                             lambda v: now - v[2] > LOGIN_FORGET_AFTER_S)
        state[0] += 1
        state[2] = now
        over = state[0] - LOGIN_FREE_FAILURES
        if over > 0:
            state[1] = now + min(2.0 ** (over - 1), LOGIN_MAX_DELAY_S)


def login_succeeded(key: str) -> None:
    with _lock:
        _login.pop(key, None)


# ---- OTP codes ------------------------------------------------------------

def new_code_issued(user_id: int) -> None:
    with _lock:
        _otp_wrong.pop(user_id, None)


def otp_wrong(user_id: int) -> bool:
    """Record a wrong code; True when the code must now be invalidated."""
    with _lock:
        count = _otp_wrong.get(user_id, 0) + 1
        if count >= OTP_MAX_WRONG:
            _otp_wrong.pop(user_id, None)
        else:
            _otp_wrong[user_id] = count
            _otp_wrong.move_to_end(user_id)
    if count >= OTP_MAX_WRONG:
        _log_once(f"otp:{user_id}", f"OTP invalidated after {OTP_MAX_WRONG} wrong codes: user_id={user_id}",
                  user_id=user_id)
        return True
    return False


# ---- /otp/send ------------------------------------------------------------

def may_send(email: str) -> bool:
    """Consume a send slot for this address if one is free. Same rules whether
    or not an account exists, so the answer reveals nothing."""
    key = email.strip().lower()
    now = clock()
    with _lock:
        times = _sends.touch(key, deque, lambda v: not v or now - v[-1] > 3600)
        while times and now - times[0] >= 3600:
            times.popleft()
        allowed = (not times or now - times[-1] >= SEND_COOLDOWN_S) and len(times) < SEND_HOURLY_CAP
        if allowed:
            times.append(now)
    if not allowed:
        _log_once(f"send:{key}", f"OTP send throttled for {key}")
    return allowed
