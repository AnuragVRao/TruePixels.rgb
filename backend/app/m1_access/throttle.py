"""Brute-force throttling for sign-in and OTP (Phase 6-pre, changes.md 6.13, 6.16).

All state is IN MEMORY in this process. It RESETS ON RESTART, and with more
than one worker each worker counts separately (the app runs one worker
deliberately: the GPU). That is enough to slow online guessing to the rate
the API can serve; it is not a distributed rate limiter.

Sign-in (``/auth/login`` and ``/auth/admin/login`` share the counters). Two
independent counters, and a request waits for the LONGER of the two:

* per (email, client IP): the first ``PAIR_FREE_FAILURES`` failures are free;
  each later one doubles the wait - 1, 2, 4 ... ``MAX_DELAY_S`` seconds;
* per ACCOUNT (email only, any IP): the same doubling after
  ``ACCOUNT_FREE_FAILURES`` failures, so rotating client addresses does not
  escape it.

Delay only - never a hard lockout: after the wait one more attempt is
checked, so an attacker cannot lock the real owner out for longer than the
current wait. A correct password clears both counters of that email. An
idle counter is forgotten after ``FORGET_AFTER_S``. A waiting request gets
429 ``AUTH_RATE_LIMITED`` with Retry-After, before any password work.

OTP: ``OTP_MAX_WRONG`` wrong codes (or wrong purposes) invalidate the
challenge. ``/auth/otp/send``: ``SEND_COOLDOWN_S`` between sends and at most
``SEND_HOURLY_CAP`` per hour per address, whether or not the account exists.

The client IP is ``request.client.host`` - the address uvicorn resolved,
which honours X-Forwarded-For ONLY from ``--forwarded-allow-ips``. Never read
X-Forwarded-For here.

Eviction (each table holds at most ``MAX_KEYS`` keys). When a NEW key arrives
at a full table:
1. entries that have expired are dropped;
2. otherwise the entry with the LOWEST weight goes (fewest failures / sends;
   the least recently used first among equals) - but an entry that is
   currently ENFORCING a delay or a cap is never evicted;
3. if every entry is enforcing, the new key is not tracked (logged once a
   minute). Flooding with fresh keys therefore cannot reset a counter that
   matters: fresh keys weigh 1, and active counters are protected.

Throttle events reach D6 at most once per ``LOG_INTERVAL_S`` per key.
``clock`` is injectable (tests replace it; nothing here sleeps).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Callable

from app.shared.errors import AppException
from app.shared.logging import emit

PAIR_FREE_FAILURES = 3
ACCOUNT_FREE_FAILURES = 10
LOGIN_FREE_FAILURES = PAIR_FREE_FAILURES  # name kept for callers/tests
MAX_DELAY_S = 60.0
LOGIN_MAX_DELAY_S = MAX_DELAY_S
FORGET_AFTER_S = 15 * 60
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
    """Bounded per-key state with the eviction rule in the module docstring."""

    def __init__(self, expired: Callable[[object, float], bool], weight: Callable[[object], int],
                 enforcing: Callable[[object, float], bool]):
        super().__init__()
        self.expired, self.weight, self.enforcing = expired, weight, enforcing

    def touch(self, key, factory, now: float):
        """The state for ``key`` (created if needed), or None if it cannot be tracked."""
        if key in self:
            self.move_to_end(key)
            return self[key]
        if len(self) >= MAX_KEYS:
            for stale in [k for k, v in self.items() if self.expired(v, now)]:
                del self[stale]
        if len(self) >= MAX_KEYS:
            victims = [(self.weight(v), i, k) for i, (k, v) in enumerate(self.items())
                       if not self.enforcing(v, now)]
            if not victims:
                return None
            del self[min(victims)[2]]
        self[key] = factory()
        return self[key]


def _counter_table() -> _Table:
    # state: [failures, next_allowed, last_seen]
    return _Table(expired=lambda v, now: now - v[2] > FORGET_AFTER_S,
                  weight=lambda v: v[0],
                  enforcing=lambda v, now: v[1] > now)


_pairs = _counter_table()     # "email|ip" -> counter
_accounts = _counter_table()  # "email"    -> counter
_otp_wrong = _Table(expired=lambda v, now: False, weight=lambda v: v, enforcing=lambda v, now: False)
_sends = _Table(expired=lambda v, now: not v or now - v[-1] >= 3600, weight=lambda v: len(v),
                enforcing=lambda v, now: bool(v) and (now - v[-1] < SEND_COOLDOWN_S or len(v) >= SEND_HOURLY_CAP))
_logged = _Table(expired=lambda v, now: v is None or now - v >= LOG_INTERVAL_S, weight=lambda v: 0,
                 enforcing=lambda v, now: False)


def reset() -> None:
    """Tests only."""
    with _lock:
        for table in (_pairs, _accounts, _otp_wrong, _sends, _logged):
            table.clear()


def _log_once(key: str, detail: str, user_id: int | None = None) -> None:
    now = clock()
    with _lock:
        last = _logged.touch(key, lambda: None, now)
        if key not in _logged or (last is not None and now - last < LOG_INTERVAL_S):
            return
        _logged[key] = now
    emit("authentication", detail, severity="warning", user_id=user_id)


# ---- sign-in --------------------------------------------------------------

def login_key(email: str, client_ip: str | None) -> tuple[str, str]:
    return email.strip().lower(), client_ip or "unknown"


def _wait(table: _Table, key: str, now: float) -> float:
    state = table.get(key)
    if state is None:
        return 0.0
    if table.expired(state, now):
        del table[key]
        return 0.0
    return max(0.0, state[1] - now)


def check_login(key: tuple[str, str]) -> None:
    """Raise RateLimited while either counter for this attempt must still wait."""
    email, ip = key
    now = clock()
    with _lock:
        pair_wait = _wait(_pairs, f"{email}|{ip}", now)
        account_wait = _wait(_accounts, email, now)
    wait = max(pair_wait, account_wait)
    if wait > 0:
        which = "account" if account_wait >= pair_wait else "address"
        _log_once(f"login:{which}:{email}|{ip if which == 'address' else '*'}",
                  f"Sign-in throttled ({which} counter) for {email}")
        raise RateLimited(wait)


def _fail(table: _Table, key: str, free: int, now: float) -> bool:
    state = table.touch(key, lambda: [0, 0.0, now], now)
    if state is None:
        return False
    state[0] += 1
    state[2] = now
    over = state[0] - free
    if over > 0:
        state[1] = now + min(2.0 ** (over - 1), MAX_DELAY_S)
    return True


def login_failed(key: tuple[str, str]) -> None:
    email, ip = key
    now = clock()
    with _lock:
        tracked = _fail(_pairs, f"{email}|{ip}", PAIR_FREE_FAILURES, now)
        tracked = _fail(_accounts, email, ACCOUNT_FREE_FAILURES, now) and tracked
    if not tracked:
        _log_once("table-full", "Sign-in throttle table is full of active delays; a new key was not tracked")


def login_succeeded(key: tuple[str, str]) -> None:
    email, ip = key
    with _lock:
        _pairs.pop(f"{email}|{ip}", None)
        _accounts.pop(email, None)


# ---- OTP codes ------------------------------------------------------------

def new_code_issued(user_id: int) -> None:
    with _lock:
        _otp_wrong.pop(user_id, None)


def otp_wrong(user_id: int) -> bool:
    """Record a wrong code; True when the challenge must now be invalidated."""
    now = clock()
    with _lock:
        count = (_otp_wrong.get(user_id) or 0) + 1
        if count >= OTP_MAX_WRONG:
            _otp_wrong.pop(user_id, None)
        elif _otp_wrong.touch(user_id, lambda: 0, now) is not None:
            _otp_wrong[user_id] = count
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
        times = _sends.touch(key, deque, now)
        if times is None:
            allowed = False
        else:
            while times and now - times[0] >= 3600:
                times.popleft()
            allowed = (not times or now - times[-1] >= SEND_COOLDOWN_S) and len(times) < SEND_HOURLY_CAP
            if allowed:
                times.append(now)
    if not allowed:
        _log_once(f"send:{key}", f"OTP send throttled for {key}")
    return allowed
