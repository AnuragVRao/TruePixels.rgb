# Sign-in, OTP and throttling: how it works (2026-10-05)

Written for the M1 owner and the Phase 8 requirements matrix. Code:
`backend/app/m1_access/otp_challenge.py`, `throttle.py`, `router_auth.py`.
History: `changes.md` 6.13 and 6.15–6.16.

## What was wrong (until 2026-10-05)

`POST /auth/otp/send` issued a code to **any** registered address, and
`POST /auth/otp/verify` exchanged that code for a full session, for **any
role** (admins included), **even with 2FA switched off**. The one-time code
was therefore a password-free sign-in, not a second factor. Nothing limited
guessing: a code survived any number of wrong attempts for 5 minutes, and
`/otp/send` had no cooldown.

**For the requirements matrix.** Describe F.2 (authentication) as
*realised, with optional OTP 2FA, off by default*, and nothing stronger.
Until 2026-10-05 the OTP feature weakened F.2, because it added a path that
skipped the password.

## The challenge model now

- **Where a code can come from.** A code exists only inside a *challenge*
  with a purpose, stored in D1 as `users.otp_purpose` (migration 0003):
  - **`login`:** created only after a **correct password** (`/auth/login` or
    `/auth/admin/login`). Any role.
  - **`register`:** created only by `/auth/register`, which creates role
    User. It is redeemable only while the role is still User.
- **Redeeming.** `/auth/otp/verify` must name the purpose. The answer is the
  same "invalid or expired" whether the purpose is wrong, the code belongs to
  another account, the challenge expired, or there is no challenge; each of
  these counts as a wrong attempt. A redeemed challenge is consumed (single
  use).
- **Re-sending.** `/auth/otp/send` only re-sends a **pending** challenge,
  with the same purpose, and can never create one. It gives one identical
  answer in every case.
- **2FA off.** With `REQUIRE_2FA` off, both OTP endpoints answer
  `403 AUTH_FORBIDDEN` and do nothing.
- **Admins.** Admin sessions always need the admin's password. A
  registration challenge can never yield an Admin session.
- **Storage.** Codes are stored only as **Argon2id hashes** (random salt,
  argon2-cffi) and checked with Argon2's own **constant-time** verify.
  Residual risk: a stolen database lets someone brute-force a 6-digit code
  offline, but every code expires after 5 minutes.
- **Delivery.** In **production** (`ENVIRONMENT` anything but
  `development`), no code is issued unless real e-mail is configured
  (`EMAIL_BACKEND=smtp` with host, user, password and sender). Otherwise
  the answer is `503 OTP_DELIVERY_UNAVAILABLE`. Registration is refused
  *before* the account is created, and an SMTP failure never falls back to
  printing the code. Console delivery is development only.

- **No stale hashes.** A challenge's hash, expiry and purpose are cleared
  when it is redeemed, when it is killed by wrong attempts, and when it
  **expires**. The app lifespan purges expired challenges at startup and
  every 60 s, so no code hash outlives its expiry by more than a minute.

## Accounts whose registration code was never redeemed

- **2FA on (`REQUIRE_2FA=True`).**
  - The account has **no session** until a code is redeemed.
  - Signing in with the password does not give a session either: it sends
    a *login* code to the same mailbox.
  - Redeeming either code proves control of the mailbox, so it also sets
    `is_email_verified`.
  - In effect, every session already implies a verified address, so login
    is **not** gated separately on the registration code.
- **2FA off (`REQUIRE_2FA=False`, the default in `m1_access/config.py`).**
  - Email ownership is **never** checked.
  - Accounts are created with `is_email_verified=True`, meaning
    "verification not required in this mode", not "verified".
  - Verification is **optional** and off in this configuration.
- **Residual risk (reported, not fixed).** With 2FA on, someone can
  register another person's address and never redeem the code. The real
  owner then gets "email already taken" and has no way to recover the
  address: there is no password reset, and admins cannot reassign it.
  Mitigations for later: let a new registration take over an *unverified*
  account after a grace period, or add an admin action.

## Throttling (in memory)

| Limit | Key | Rule |
|---|---|---|
| Sign-in, per address | email + client IP | 3 free failures, then 1, 2, 4 … 60 s wait |
| Sign-in, per account | email only (any IP) | 10 free failures, then the same doubling |
| OTP redemption | account | the 5th wrong code (or wrong purpose) kills the challenge |
| OTP re-send | email (account or not) | 60 s cooldown, 5 per hour |

- **Delay, never lockout.** A waiting request gets `429 AUTH_RATE_LIMITED`
  with `Retry-After`. After the wait, one more attempt is checked. A correct
  password clears both sign-in counters.
- **Client IP.** This is the address uvicorn resolved. `X-Forwarded-For` is
  honoured only from `--forwarded-allow-ips`, so a direct client cannot
  spoof it.
- **Audit log.** Throttle events reach D6 at most once a minute per key.
- **Eviction.** Each table holds at most 10,000 keys. For a new key at a
  full table:
  1. Expired entries are dropped first.
  2. Otherwise the entry with the fewest failures or sends goes, least
     recently used first.
  3. An entry that is currently **enforcing** a delay or cap is **never**
     evicted.
  4. If every entry is enforcing, the new key goes untracked, and that is
     logged.

  So flooding with fresh keys cannot reset a counter that matters. This is
  tested, and a plain-LRU version fails those tests.
- **Capacity and fallback.** Each table holds 10,000 keys; all tables
  together take a few MB. If an attempt cannot get its own counter (every
  slot is enforcing a delay), it is **not** left unthrottled:
  - it falls back to a per-IP counter (3 free failures, then doubling);
  - if that table is saturated too, it falls back to one global window of
    30 untracked failures a minute.

  The global window is a **last resort**:
  - it applies only to attempts that no other counter could hold;
  - it counts **failures only** (successful sign-ins do not consume it);
  - it cannot tell attackers from legitimate newcomers, so while it is full
    a real user whose key is untracked waits too, for at most a minute.

  OTP sends that cannot be tracked are refused, not sent.
- **State resets on restart, and on a crash loop.** All throttle state lives **in this process's
  memory**: a restart forgets every counter. With several workers, each
  counts separately. The app runs one worker on purpose (the GPU). This
  slows online guessing; it is not a distributed rate limiter.
