# changes.md — integrating M1 and M3

On 2026-09-30, the M1 (`M1 TruePixel.zip`, *Truepixels.rgb-main*) and M3
(`M3 TruePixel.zip`, *AI Generated Image Detection System*) projects were
merged into this repository alongside M2. The rule was to **keep their code
as it was and change it only where integration required it**. This file lists
every change to their code and the reason for it.

Each changed line in their files also carries an `INTEGRATION:` comment, so
`grep -rn INTEGRATION backend frontend` finds all of them.

---

## At a glance

| | Files copied | Files unchanged | Files changed |
|---|---|---|---|
| **M1** backend (`app/m1_access/`) | 12 | 10 | 2: `config.py`, `email_service.py` |
| **M1** tests | 6 | **6** | 0 |
| **M1** React frontend | all | **all** | 0 |
| **M1** other | `seed_admin.py`, `.env.example` | `seed_admin.py` | `.env.example` (one line) |
| **M3** backend (`app/m3_results/`) | 12 | 6 | 6: `models.py`, `router_reports.py`, `router_results.py`, `router_history.py`, `explain.py`, `overlay.py` (+ 1 new: `urls.py`) |
| **M3** stubs (`app/stubs/`) | 3 | 2 | 1 (docstring only) |
| **M3** tests | 7 | **6** test files | `conftest.py` |
| **M3** frontend | 2 | 0 | `index.html`, `api_tester.html` |
| Both: `app/shared/*`, `app/main.py` | — | — | **merged** — each team shipped its own copy (see §1) |

Test results after integration: **M1 36/36, M3 27/27, M2 76/76 fast + 13/13
model-backed** — 152 in total, all green. M1's test files and M3's test files
run unchanged. The 13 model-backed tests now drive the whole chain: upload
through M1, predict through M2, and read the result back through M3.

---

## Where things went

| From | To | Why |
|---|---|---|
| M1 `app/m1_access/` | `backend/app/m1_access/` | Same package name as the placeholder that was already there. |
| M3 `app/m3_results/` | `backend/app/m3_results/` | PRD4 §7 names the package `m3_results`; this repo's placeholder was called `m3_reporting`. The placeholder README moved into it, so none of M3's imports had to change. |
| M3 `app/stubs/` | `backend/app/stubs/` | Kept where M3's tests import it from. **Test-only now** (see §3.1). |
| M1 `tests/` | `backend/tests/m1/` | Each team's conftest defines its own `client`/`db_session`, so each suite gets its own directory. |
| M3 `tests/` | `backend/tests/m3/` | Same; an `__init__.py` was added so the two `conftest.py` files don't clash. |
| M1 `frontend/` (React/Vite) | `frontend/` | Merged into the existing placeholder tree; nothing overwritten. |
| M3 `frontend/index.html`, `api_tester.html` | `frontend/m3_dashboard/` | `frontend/` is now M1's React app. `main.py` serves these files at `/` and `/api-tester` as before. |
| M1 `seed_admin.py` | `backend/seed_admin.py` | Same position relative to `app/` as in M1's repo, so it still runs unchanged from `backend/`. |
| M1 `.env.example` | `backend/.env.example` | `load_dotenv()` searches upward from `app/m1_access/`, so `backend/.env` is found. |
| M1 `requirements.txt` | merged into `backend/requirements.txt` | Pinned to the versions the suite was run with. `alembic`, `pydantic-settings` and `pytest-asyncio` were listed but never imported; `passlib` is only a fallback for when `argon2-cffi` is missing. These four were left out. |
| M3 needed `reportlab`, `matplotlib` | added to `backend/requirements.txt` | M3 shipped no requirements file. |

**Not copied.** From M3: `truepixels.db`, `test_out.pdf`, `uploads/` (mock
images, random tensors, rendered heatmaps), `__pycache__/`, `.pytest_cache/`,
and the three seeding scripts `generate_mock_dataset.py`, `seed_data.py` and
`seed_internet_benchmarks.py`. The scripts fill the database with fabricated
predictions, and the old `/mock/predict` endpoint needed
`generate_mock_dataset.py` (see §3.1). From M1: `storage/.gitkeep`, since the
repo already has `storage/`.

---

## 1. Files both teams shipped — merged

M1 and M3 each shipped their own `app/main.py` and their own
`app/shared/{db,deps,errors,logging,schemas}.py`, and M2 had its own
`app/shared/contracts/`. Only one copy of each can exist, so these were
merged. The rule for each merge: **keep what both sides relied on, so neither
side's code has to change.**

### 1.1 `app/shared/db.py`
The two copies were nearly identical. **M1's** is used, since it owns D1/D2
and ships `init_db()`. It has two additions:
- M3's `SQL_ECHO` switch now works alongside M1's `DEBUG` switch.
- `init_db()` imports all three model modules before `create_all()`, so D1–D6
  are all created no matter which router was imported first.

### 1.2 `app/shared/deps.py` (Contract C3)
**M1's file, unchanged.** M3's version was a mock: an in-memory
`ACTIVE_SESSIONS` table of fixed tokens such as `test-user-token-1`. Anyone who
knew those strings could act as any user in the running app. That table now
lives only in `backend/tests/m3/conftest.py` (§3.4).

### 1.3 `app/shared/errors.py`
The union of the two:
- `ERROR_REGISTRY` and the `AppException` signature come from **M3**. They are
  a superset of M1's: `message` and `status_code` default from the registry
  when omitted, and every M1 call site passes both explicitly, so M1's
  behaviour is unchanged.
- The named subclasses (`AuthTokenInvalidException`, `ImgNotFoundException`,
  …) and both handlers come from **M1**. M1's catch-all handler replaces the
  equivalent one in M3's `main.py`; it also returns the request id, where
  M3's returned `null`.

### 1.4 `app/shared/logging.py` (Contract C5)
`emit()` now does what **both** versions did:
- **M3's behaviour:** persist the event to the D6 `logs` table through M3's
  `logging_service.emit_log`. M3 owns C5 and D6, and the admin log viewer
  reads that table.
- **M1's behaviour:** echo a redacted line to stdout. This is kept because
  M1's console e-mail backend depends on it: with `EMAIL_BACKEND=console`,
  this output is the only place the OTP code appears.

`severity` keeps M1's default of `"info"`. M3 made it required, but every M3
call passes it.

### 1.5 `app/shared/schemas.py` (Contracts C1, C2, C3)
M1, M3 and M2 each had their own definitions of `PreprocessedImage`,
`InferenceOutput`, `ActivationBundle` and `SessionContext`. Three copies of
one contract is how the seams drift apart. Now:
- C1 and C2 are defined once, in `app/shared/contracts/c1.py` and `c2.py`
  (M2's existing files).
- C3 `SessionContext` is defined once, in the new `contracts/c3.py`. It is the
  union of M1's and M3's versions: M3's defaults for `account_status` and
  `issued_at` (M3's tests build sessions without them), plus M1's
  `from_attributes` config.
- `app/shared/schemas.py` keeps its name and re-exports all of them plus
  M3's `ErrorEnvelope`, so every `from app.shared.schemas import …` in M1 and
  M3 still works.

Other differences, none of which affects any existing call:
- M1's `PreprocessedImage` and M3's `ActivationBundle` had defaults for some
  fields. The contract versions require them, and both teams already pass
  them.
- In `InferenceOutput`, `frequency_score` is `float | None`, because M2's
  frequency branch can be disabled. The other fields match M1/M3 exactly.

### 1.6 `app/main.py`
Everything both files registered is registered here:
- **From M1:** the `lifespan` that calls `init_db()`, CORS, the request-id and
  timing middleware, both exception handlers, the `/auth`, `/images` and
  `/users` routers.
- **From M3:** the `/results`, `/history`, `/reports` and `/admin` routers,
  the dashboard at `/`, the API tester at `/api-tester` (also `/developer`
  and `/playground`), and `/api/v1/health`.
- **From M2:** `/api/v1/predictions` and the detailed `/health`. M1's
  `/health` was a three-field subset of this one; its fields
  (`status`, `service`, `version`) are included.

Differences from M3's `main.py`:
- M3 mounted `./uploads` (relative to the working directory) at
  `/static/uploads`. Now the shared `storage/` tree is mounted at `/static`
  (see §4).
- M3 found its HTML with `os.getcwd()/frontend/…`. It now uses
  `REPO_ROOT/frontend/m3_dashboard/…`, so the page is served whatever
  directory uvicorn starts from.
- M3's startup created `./uploads/images`, `./uploads/tensors`,
  `./uploads/xai` and `./frontend` in the working directory. That step is
  gone; the shared storage layout is created instead.

---

## 2. Changes to M1's code

### 2.1 `app/m1_access/email_service.py` — hard-coded Gmail password removed (**security**)
```diff
- smtp_password = os.getenv("SMTP_PASSWORD", "<a real app password>")...
+ smtp_password = os.getenv("SMTP_PASSWORD", "")...
```
The default value was a real Google app password for a developer's personal
Gmail account. Committing it would publish a working credential. The literal
is redacted here too - a changelog that quotes the secret it removed has not
removed it. With no password set, the code falls through to M1's existing
console path, which logs the OTP. To send real mail, put `SMTP_PASSWORD` in
`backend/.env`.

> ⚠ **Action for M1's owner:** that password was in the zip and is probably
> in M1's own git history. **Revoke it** in the Google account (Security →
> App passwords) and create a new one. Removing it from this repository does
> not make the old one safe.

### 2.1b `app/m1_access/config.py` + `email_service.py` — signing key and personal address (**security**, 2026-09-30)

Found while making the tree commit-ready.

```diff
- JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev_secret_key_truepixels_rgb_8473…")
+ JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(64)  # + a loud warning
```
A signing key written into the source is not a secret: anyone who can read the
repository can mint a valid session token for any user, on any deployment that
did not override it — and this one is headed for a public tunnel. Unset now
means *unguessable* rather than *published*. The cost is that sessions end at
every restart while the variable is unset, which is the right way round, and
the warning says so. **Set `JWT_SECRET_KEY` in `backend/.env` before deploying**,
and note that more than one uvicorn worker *requires* it — otherwise each
worker signs with a different key and rejects the others' tokens.
`backend/.env.example` carried the same fixed key and now carries instructions
for generating one.

`SMTP_USER` and `SMTP_FROM` (in both `config.py` and `email_service.py`)
defaulted to a developer's personal Gmail address. Now empty; set them in
`.env`. With no `SMTP_PASSWORD` the console fallback is unchanged, so local
development is unaffected.

### 2.1c `app/main.py` — wildcard CORS with credentials (**security**, 2026-09-30)

```diff
- allow_origins=["*"], allow_credentials=True, allow_methods=["*"]
+ allow_origins=config.CORS_ALLOWED_ORIGINS, allow_credentials=True,
+ allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
```
`"*"` together with `allow_credentials=True` is the dangerous pairing: rather
than sending `Access-Control-Allow-Origin: *` (which browsers refuse to use
with credentials), Starlette **echoes the caller's Origin**, so any website a
signed-in user happened to visit could call this API with their session
cookie or token. Both module mains shipped it.

The allowlist lives in `app/shared/config.py` as `CORS_ALLOWED_ORIGINS` and
defaults to the local dev origins (M1's React server on :3000 or :5173, and
the API's own host). M3's dashboard is served from the API itself, so it is
same-origin and needs no CORS at all. Add a deployment origin with
`TRUEPIXELS_CORS_ORIGINS=https://…` rather than widening the default.

### 2.2 `app/m1_access/config.py` — one shared storage directory
```diff
- STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage")))
+ STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR.parent / "storage")))
```
`BASE_DIR` is `backend/`, so M1 used to store uploads in `backend/storage/`,
while M2 reads from repo-root `storage/`. The two would never have found each
other's files. M2's config now also honours M1's `STORAGE_DIR` variable, so
setting it moves all three modules together.

### 2.3 `.env.example`
`STORAGE_DIR=./storage` was commented out. Copied to `.env`, that line would
have overridden the shared default with a path relative to wherever uvicorn
was started.

### Not changed in M1, deliberately
All routers, validation, preprocessing, security, models and schemas are
**unchanged**. All 36 of M1's tests pass as written.

---

## 3. Changes to M3's code

### 3.0 `frequency_score` may be null (2026-09-30)

M2's frequency branch (SPAI) tiles its input into 224x224 patches and cannot
score an image smaller than that in either dimension - the vendored tensor
code raises. M1 accepts images down to 64px (PRD C.9), so a 100x100 upload
reached M2 and came back as **HTTP 500**. Confirmed by probe: 223x223 fails,
224x224 works.

Contract C2 has always typed the field `float | None`, so the fix is the one
the contract already allows: M2 returns **null** and fusion degrades to its
documented passthrough (a verdict from the semantic branch alone), exactly as
when the branch is switched off in config. Two of M3's files assumed the
field was always a number:

- **`schemas.py`: `frequency_score: float` -> `float | None`.** It now matches
  C2, which M3's own schema is a projection of.
- **`reporting.py`: the PDF cell** formatted `f"{...:.4f}"` unconditionally,
  which raises on null. It now prints `unavailable`.

Also changed on M2's side of the seam: `models.py` makes the D4 column
`nullable=True` (a stand-in number there would outlive the request and end up
in reports), and `pipeline.py` no longer refuses a null - the guard that did
so was added on the assumption that M3 could not render one.

**No migration needed** as long as the SQLite file is recreated: the column
was `NOT NULL` in any database created before this change.

### 3.0b The dashboard shipped a hard-coded verdict (2026-10-01)

§3.1 below removed M3's mock prediction *endpoint*. The static page kept its
own copy of the same idea: `frontend/m3_dashboard/index.html` rendered the
result card unconditionally, pre-filled with **"Real", "High Confidence",
"96.2%"**, branch scores `0.0320 / 0.0480 / 0.0380`, model
`TruePixels-Ensemble-ViT-FFT v1.0.0` and a `2026-09-06` timestamp. Signing in
and touching nothing therefore displayed a confident verdict for an image that
had never been analysed — with an empty `predictions` table behind it. Found
by the user on first use.

- The card is now `hidden` until a prediction has actually been rendered, and
  an **empty state** ("No image analysed yet") sits in its place.
- Every pre-filled value is now an em dash, so nothing fabricated can appear
  even for the instant before real data lands.
- The two explainability panels had `<img src="">`, which browsers draw as
  broken-image icons. They now carry an explicit "Not available" note —
  M2 exports no activations yet, so `/explainability` answers
  `XAI_UNAVAILABLE`, and `showPanel()` reveals an image only if the API
  returned a URL.

This is the same rule as CLAUDE.md §3's "never populate a field with a
stand-in value to satisfy a schema", applied to the UI: a demo audience
reading a fabricated 96.2% has been misled more effectively than by any
wrong number the model could produce.

### 3.1 Mock predictions and synthetic explainability removed from the live app
M3 was built before M2 existed, and like M2's old `dev_intake.py` it
contained stand-ins for the missing module. Now that the real module exists,
they come out of the running app, just as `dev_intake.py` came out of M2
when M1 arrived.

- **`router_results.py`: `POST /api/v1/mock/predict` removed.** It stored
  random scores in the real `predictions` table, where they would have mixed
  with genuine predictions in history, analytics and PDF reports. It also
  imported `generate_mock_dataset` from outside the `app` package, which is
  not importable here. Predictions now come from `POST /api/v1/images` →
  `POST /api/v1/predictions`. `CreateMockPredictionRequest` is left in
  `schemas.py`, now unused.
- **`explain.py`: the synthetic-heatmap fallback removed.** With no attention
  or gradient data, `build_relevance_map()` used to return a Gaussian blob
  labelled `synthetic-fallback`. That renders as a convincing heatmap that
  explains nothing. PRD4 §4.2.2 says M3 must "surface XAI_UNAVAILABLE rather
  than … fabricating a blank heat map", so it now raises `XAI_UNAVAILABLE`.
- **`overlay.py`: the synthetic-spectrum fallback removed,** for the same
  reason (`XAI_UNAVAILABLE` instead).
- **`app/stubs/__init__.py`: docstring only.** It now states that the package
  is test-only. The stubs themselves are unchanged. Nothing under `app/`
  imports them; only M3's tests do.

**What M3 shows today:** M2 does not yet produce an `ActivationBundle` (M2
milestone Step 6). So a result page shows the verdict and all scores but no
panels, and `GET /api/v1/explainability/{id}` answers `501 XAI_UNAVAILABLE`.
That is the honest answer until Step 6 lands.

### 3.2 `router_reports.py` — report download had no authentication (**security**)
The original handler's parameters were `token`, `session` and
`authorization`, all without `Header()`/`Depends()`, so FastAPI read all
three from the **query string**. The `Authorization` header was never looked
at. Tokens were looked up in the mock `ACTIVE_SESSIONS` table, and **when no
session was found the handler fell back to test user 1**. Result: anyone,
with no credentials at all, could download user 1's reports. M3's own
isolation test (case 3) passed only because its attacker happened to be
user 1.

Now a `report_session` dependency takes the token from the `Authorization`
header or from `?token=`, which the dashboard's download button needs because
a plain browser download can't set headers. It checks the token with **M1's**
`verify_session_token`, including the live account-status check, and
answers `401 AUTH_TOKEN_INVALID` when there is no token. The ownership and
admin logic below it is unchanged.

### 3.3 `models.py` — D1–D4 no longer redefined
M3's `models.py` declared its own `User` (D1), `Image` (D2), `ModelRegistry`
(D3) and `Prediction` (D4). With M1 also declaring `users` and `images` on the
same `Base`, the app **crashes on import** with `Table 'users' is already
defined for this MetaData instance`. Now:
- `User` and `Image` are imported from `app.m1_access.models` (M1 owns D1/D2).
- `ModelRegistry` and `Prediction` moved to `app/m2_analysis/models.py`
  (PRD4 §4.2.4: M2 owns D3/D4 and is the only writer of D4), with **M3's
  columns unchanged** apart from the two notes below. They are re-imported
  here, so every `from app.m3_results.models import …` still works.
- `Explainability` (D5) and `LogEntry` (D6) are M3's, unchanged, except that
  `LogEntry.user` no longer declares `back_populates="logs"`: M1's `User` has
  no `logs` attribute, and nothing reads it. `Prediction.image` lost its
  `back_populates` for the same reason.

Two column notes in the moved D3/D4 classes:
- `models.artifact_sha256` is now **nullable**. The SigLIP 2 checkpoint is
  loaded from Hugging Face by name, and no hash of it is pinned. An invented
  hash would be worse than `NULL`.
- `predictions.frequency_score` **stays NOT NULL**, as M3 wrote it, because
  M3's views and PDF report format it unconditionally. If M2's frequency
  branch is ever disabled, the prediction fails with a clear message instead
  of storing a stand-in number.

### 3.4 URLs for stored files — new `urls.py`, used by `router_results.py` and `router_history.py`
M3 built image URLs as `f"/static/{file_reference}"`. That only works for
paths relative to the working directory, but M1 stores **absolute** paths
(`C:\…\storage\uploads\ab\cd\<sha>.jpg`), which produced broken links like
`/static/C:\…`. The new `storage_url()` turns a path inside the shared
storage tree into its `/static/…` URL. For anything else it falls back to
M3's original format. Three lines changed: `original_image_url`,
`thumbnail_url` and `visualization_url` (×2).

### 3.5 `overlay.py` — where explainability images are written
The default `storage_dir` changed from `"./uploads/xai"` (relative to the
working directory) to `storage/explainability/`. That folder is inside the
tree served at `/static` and already gitignored.

### 3.6 Frontend — `index.html` (dashboard)
Only the three parts that depended on mocks changed:
1. **Sign-in.** The three persona buttons, which picked a fixed fake token,
   became an email/password form. It calls M1's `/auth/login` or
   `/auth/admin/login`, and handles M1's optional OTP step via
   `/auth/otp/verify`. "Switch User" became "Sign Out" and calls
   `/auth/logout`. The session survives a page reload (`sessionStorage`).
2. **Scanning.** "Simulate New Scan", which called the removed mock endpoint,
   became "Scan New Image": pick a file → `POST /api/v1/images` →
   `POST /api/v1/predictions` → show the result.
3. **Removed:** the "Quick Test Cases" buttons, which linked to prediction ids
   33, 34 and 13 in M3's seeded mock database, with the percentages hard-coded
   into their labels. Also, diagnostics check 5 now uses the signed-in session
   instead of a hard-coded admin token, and expects `403` for non-admins.

Results, history, reports, admin analytics, charts and styling are
unchanged.

### 3.7 Frontend — `api_tester.html`
- The token dropdown's three fake tokens were replaced by "Signed-in session
  (from dashboard)", which reads the dashboard's login. Same origin, so they
  share it. The "invalid token" and "no header" options remain.
- "Run all" used a hard-coded fake token and now uses the selected one.
- The "Simulate Pipeline Scan" entry now points at `POST /api/v1/predictions`.

Its sample URLs still contain M3's example ids (e.g. `/reports/33`); edit
them to one of your own predictions.

### 3.8 `tests/m3/conftest.py`
M3's **test files are unchanged**. The conftest now:
- holds M3's original mock `ACTIVE_SESSIONS` table and mock `current_session`
  logic (moved here from `app/shared/deps.py`, logic unchanged), and applies
  them through `app.dependency_overrides` for M1's `current_session` and the
  new `report_session`. The test files' `"Bearer test-user-token-1"` headers
  therefore still work;
- runs the suite from a scratch directory, so the relative `./uploads/…` paths
  M3's tests write to don't land in the repository.

### Not changed in M3, deliberately
`analytics.py`, `logging_service.py`, `reporting.py`, `router_admin.py`,
`schemas.py`, `m1_stub.py`, `m2_stub.py` and all six test files are
**unchanged**. All 27 of M3's tests pass.

---

## 4. Changes on M2's side (our code), for completeness

- **`dev_intake.py` deleted.** It was the temporary M1 stand-in, documented
  from the start to be deleted when M1 shipped.
- **`POST /api/v1/predictions`** is now PRD2 §10.1's form: a JSON body
  `{image_id, xai}`, `Depends(current_session)`, owner-only, with the image
  resolved through M1's `prepare_model_input` (Contract C1). A missing image
  and someone else's image both return `404 IMG_NOT_FOUND`, so ids can't be
  probed. Errors use the shared `{"error": {code, message, request_id}}`
  envelope instead of FastAPI's `{"detail": …}`.
- **D3/D4 persistence.** `run_detection()` writes the D4 row and commits
  before returning (PRD4 §4.2.4), so `prediction_id` and `model_id` are real
  integers again. `registry.record()` writes one D3 row for each artefact
  that actually ran: SigLIP 2, SPAI and the fusion configuration. The rows
  come from config, and `metrics` is always `NULL` (this system has no
  benchmark). M3's admin "activate" endpoint flips `is_active`, but M2 still
  runs whatever config says; making D3 authoritative is the rest of Step 5.
- **Storage.** `config.STORAGE_ROOT` honours `STORAGE_DIR`, and
  `EXPLAINABILITY_DIR` was added. Model weights stay in repo `storage/models/`
  regardless.
- **Tests.** The model-backed API tests now go through M1 upload and M1 auth,
  and read the result back through M3. The two input-validation tests moved
  to M1's domain (its suite covers them) and were replaced by persistence,
  `XAI_UNAVAILABLE`, auth and isolation checks. The root
  `tests/conftest.py` points `DATABASE_URL` and `STORAGE_DIR` at a scratch
  directory, so no test touches real data.

---

## 5. Known issues left as they are (not integration blockers)

Found while integrating and left alone, because fixing them would change
module behaviour rather than make the modules fit together. They are listed
so their owners can decide.

| Module | Issue |
|---|---|
| M1 | With `EMAIL_BACKEND=console` (or no SMTP password), the **OTP is written to the log**, and since C5 persists logs, it ends up in the D6 table, visible to admins in the log viewer. Fine for development; turn it off in production. |
| M1 | `DUMMY_HASH` is computed at import time (an Argon2 hash), which adds a little to startup time. |
| M1 | ~~`seed_admin.py` prints a fixed admin password.~~ **Fixed 2026-10-02**: the password now comes from `SEED_ADMIN_PASSWORD`, or is generated randomly and printed once; no credential is in source. If you seeded an admin with the old script, change that account's password. |
| M1 + M3 | Two user-admin APIs exist: M1's `/api/v1/users` (used by M1's React app) and M3's `/api/v1/admin/users` (used by M3's dashboard). Both work, with slightly different rules: M1 blocks **any** self-change, M3 only self-disable and self-remove. Worth consolidating. |
| M3 | `/api/v1/reports/{id}?token=…` puts the session token in the URL, where it can end up in browser history and server logs. Kept because the dashboard's download button depends on it. |
| All | ~~`/static` serves the whole storage tree without authentication.~~ **Fixed 2026-10-02**, see §6.1. |
| M1 → M2 | M1 caps uploads at 10 MB and 25 MP. Two of M2's smoke-test images (6144², 8192×4096) are over the pixel cap and are now rejected at upload. |
| M1 → M2 | M1 builds and saves the CLIP tensor both at upload and again at prediction, and no detector reads it (CLAUDE.md §8, item 4). Contract C1 v2 should drop it. |

---

## 6. Changes during the completion phases (2026-10-02 onwards)

Edits to M1's and M3's code made while finishing the project, one entry per
change, with the reason. The phase plan lives outside the repo; each entry
names its phase.

### 6.1 Stored files no longer public — `/static` mount removed (**security**, phase 1a)

**Problem.** `main.py` mounted the whole storage tree at `/static` with no
authentication. Anyone with a URL could fetch any user's uploaded original,
any explainability panel and - because `storage/models/` sits inside the same
tree by default - `spai.pth` and `spai.safetensors`. The SHA-256 file names
made URLs hard to guess, which is obscurity, not access control, and the URLs
themselves were handed out in `/results` and `/history` responses.

**Change.**
- `app/main.py`: the `StaticFiles` mount is gone. Nothing under
  `storage/` is web-served directly.
- **M1** `router_images.py`: new `GET /api/v1/images/{image_id}/file`,
  **owner only** - deliberately stricter than M1's metadata endpoint, which
  also admits Admins, because this returns the photograph itself (least
  privilege, SRS F.4 / NF.7). Admin access, if ever needed, should arrive
  with a D6 audit entry. Same `IMG_NOT_FOUND` for "not yours" and "does not
  exist". (First committed as owner-or-Admin; tightened 2026-10-03.)
- **M3** `router_results.py`: new
  `GET /api/v1/explainability/{prediction_id}/{branch}`. Owner only, with
  the same SQL ownership join and the same `INF_PREDICTION_NOT_FOUND` as
  `/results` and `/explainability`.
- **M3** `urls.py`: `storage_url()` (which turned a path into a `/static`
  URL, §3.4) is replaced by `image_file_url(image_id)` and
  `explainability_file_url(prediction_id, branch)`. URLs now carry ids, never
  filesystem paths. `router_results.py` and `router_history.py` use them
  (`original_image_url`, `visualization_url`, `thumbnail_url`). The response
  field names and types are unchanged.
- New `app/shared/files.py` (`stored_file_response`): both endpoints serve
  through it. It also refuses any reference that does not resolve inside the
  directory it should come from, or is not a PNG/JPEG, with the caller's
  not-found error - defence in depth, since references are server-written.
  Responses carry `Cache-Control: private, no-store`.
- **M3** dashboard `index.html`: `<img src>` cannot send the Bearer header,
  so result panels and history thumbnails are fetched with it and shown via
  blob URLs (`setAuthImage`).

**Tests.** `backend/tests/test_storage_access.py`: owner gets the file,
another user, an Admin and a missing id get identical 404s, no session
gets 401, references outside the storage tree are refused,
`/results` and `/history` link to the new endpoints, and `/static/...`
(including the weights) answers 404.


### 6.2 Audit entries for file access; swallowed log writes are now visible to tests (phase 1a follow-up)

**Problem.** The two file endpoints from §6.1 wrote nothing to D6, so neither
served files nor refused attempts were auditable (SRS F.4, F.15). Separately,
`emit_log` (M3, `logging_service.py`) swallows every write error by design -
correct for production, but it meant a broken log write could pass every
test: the model-backed suite had been writing **no** D6 rows at all, because
its logger pointed at a database with no `logs` table, and nothing noticed.

**Change.**
- **M1** `router_images.py` and **M3** `router_results.py`: a served file is
  logged as `prediction-request` / `info`; a refused request (not yours,
  missing, or an unsafe stored path) as `error` / `warning`. The log line
  names only the requested id, never the reason, mirroring the single 404.
- **M3** `logging_service.py`: `emit_log` still never raises and still writes
  to stderr, but each swallowed failure is also appended to a bounded
  in-process list, `WRITE_FAILURES`. Production behaviour is unchanged.
- Tests: the `strict_audit_log` fixture (`backend/tests/conftest.py`) fails
  a test if any write was swallowed during it. It is opt-in until Phase 2
  fixes the test database wiring. `test_audit_logging.py` asserts the D6 rows
  for register, login, upload and both file endpoints (served and refused),
  and that a raising write is caught; `test_api_predict.py` asserts the rows
  for a real prediction.

A history page with N rows now writes N `Image file served` entries, one per
thumbnail. That is the honest cost of logging file access; if it proves too
noisy, thumbnails could be exempted from logging - a decision for the M3 owner.

### 6.3 The unused CLIP tensor is no longer built or saved (phase 1b)

**Problem.** M1's `prepare_model_input` (Contract C1) decoded the image,
resized and centre-cropped it to 224x224, CLIP-normalised it and saved it as
`storage/tensors/<image_id>.npy` - at upload (`router_images.py`, result
discarded) and again at every prediction (`router_predict.py`). Nothing ever
read it: no `np.load` exists anywhere, and both M2 branches preprocess the
original themselves (SigLIP 2 with its own processor, whose mean/std is 0.5,
not CLIP's; SPAI at native resolution). Recorded as known issue in §5.

**Change.**
- **M1** `router_images.py`: the upload no longer calls `prepare_model_input`.
  Its audit line now reads `Image validated and stored` (it said
  "preprocessed", which was no longer true).
- **M1** `preprocess.py`: `prepare_model_input` still assembles C1 at
  prediction time - existence check, ids, `source_reference` - but builds and
  saves no tensor. `preprocess_pil_to_clip_tensor` is kept unchanged because
  M1's own test suite covers it; the application no longer calls it.
- **M1** `storage.py` / `config.py` and `app/shared/config.py`:
  `get_tensor_path` and `TENSORS_DIR` removed; no `tensors/` directory is
  created. An existing `storage/tensors/` folder is now dead data - safe to
  delete by hand; nothing deletes it automatically.
- **Contract C1** (`contracts/c1.py`): `tensor_ref`, `shape`, `dtype`,
  `normalization` are now optional and always `None`. Kept rather than
  deleted so M3's stub (which still fills them) and any other caller still
  validate; C1 v2 should drop them.

**Evidence.** Predictions are bit-identical to the pre-phase-1 baseline
(`regression_check.py`, 24 images). `test_api_predict.py` asserts no `.npy`
is written at upload or prediction.

### 6.4 Thumbnails get their own endpoint; file-serve audit policy (proposal for the M3 owner)

**Change.**
- **M1** `router_images.py`: new `GET /api/v1/images/{image_id}/thumbnail`,
  owner only with the same `IMG_NOT_FOUND` as `/file`. It returns a JPEG of
  at most 256 px on the longer side, made on the fly from the stored original
  and never written to disk (`app/shared/files.py`, which also gained
  `resolve_stored_file`, the shared containment check).
- **M3** `urls.py` / `router_history.py`: `thumbnail_url` in `/history` now
  points at the thumbnail endpoint instead of the full original.

**Audit policy (implemented; proposed to the M3 owner, who owns D6):**

| Serve | Success logged? | Refusal logged? |
|---|---|---|
| Full original, `/images/{id}/file` | yes, `prediction-request`/info | yes, `error`/warning |
| Explainability panel, `/explainability/{id}/{branch}` | yes | yes |
| PDF report, `/reports/{id}` (M3, unchanged) | yes | yes |
| Thumbnail, `/images/{id}/thumbnail` | **no** - routine, one per history row | yes |

Thumbnails are a separate endpoint rather than a flag on `/file` so that a
client cannot opt a full-resolution download out of the audit trail.

**Not changed, flagged:** `logging_service.purge_expired_logs` (M3's
retention: info rows after 90 days, warning/error after 365) is still never
called, so D6 grows without bound. Scheduling it turns on automatic
deletion of audit data, which is a policy decision; it is flagged for Phase 8
as an operational task (a CLI entry point run by cron), with retention to be
confirmed by the M3 owner.

### 6.5 PostgreSQL + Alembic: edits to M1 and M3 (phase 2)

The app now targets PostgreSQL (SQLite still works) and the schema is owned
by Alembic (`backend/migrations/`, revision `0001`). Edits that cross into
M1's and M3's code:

**M1**
- `models.py`:
  - `users.registered_at`, `users.otp_expires_at` and
    `images.upload_timestamp` are now `DateTime(timezone=True)`, like every
    other timestamp.
  - Email uniqueness moved from the raw column to a unique index on
    `lower(email)` (`uq_users_email_lower`), so `A@x.com` and `a@x.com` can no
    longer both register.
  - The duplicate single-column index on `content_sha256` is dropped
    (`idx_images_sha` already covered it).
- `router_auth.py`: every lookup by email (register, login, admin login, OTP
  send and verify) filters on `func.lower(User.email)`, which is both
  case-insensitive and the predicate the new index serves (checked with
  `EXPLAIN` on PostgreSQL). The app already lowercased emails before
  storing them, so behaviour is unchanged for existing data.
- `seed_admin.py`: the same `lower(email)` lookup; refuses to run on a
  database that has not been migrated.
- `tests/m1/conftest.py`: no private in-memory SQLite per test. The root
  conftest builds one test database with the migrations (SQLite, or
  PostgreSQL via `TEST_DATABASE_URL`), points the whole app at it, and
  empties every table after each test. Fixtures and test files are
  unchanged.

**M3**
- `analytics.py`: `is_active.is_(True)` instead of `== True`; the active
  models are ordered by type. The `func.date()` grouping is unchanged:
  PostgreSQL sessions are pinned to UTC (`app/shared/db.py`), so day
  boundaries are UTC on both backends.
- `router_admin.py`, `router_history.py`: deterministic ordering, with id as
  tie-breaker after timestamps, so paging cannot repeat or skip rows when two
  share a timestamp. `is_(True)` in activation.
- `router_results.py`, `router_reports.py`: explainability rows are ordered
  by branch (SQLite happened to return them in insertion order).
- `tests/m3/conftest.py`: the same move to the shared, migrated test
  database. M3's `test_emit_log_is_non_throwing_under_failure` writes an
  invalid log row on purpose, so the now-global strict audit check exempts
  that one test by name.
- `tests/m3/test_contracts.py` (**first edit to an M3 test file**):
  `test_contract_c5_logging_emission` inserted a log row for `user_id=1`
  without creating that user. SQLite never enforced the D6 -> D1 foreign key;
  PostgreSQL does, and SQLite now does too (`PRAGMA foreign_keys=ON`). The
  test now creates the user first; its assertions are unchanged.

**Shared / M2** (ours, for completeness)
- `app/shared/db.py`:
  - one engine factory and `configure_database()`, so requests, the D6
    logger and the pipeline can never use different databases;
  - explicit `.env` loading;
  - connection pool settings;
  - SQLite foreign keys on;
  - startup refuses a database that is not at Alembic head, instead of
    calling `create_all()`.
- D4 gains `cold_start`. D3 gains the partial unique index
  `uq_models_one_active_per_type`.

### 6.6 Records whose stored files are gone degrade gracefully (pre-phase 3)

**Problem.** The SQLite -> PostgreSQL migration carried two D2 rows whose
upload files no longer exist (they were already absent from
`storage/uploads/`). For such a record:
- the owner's `/images/{id}/file` and `/thumbnail` answered `IMG_NOT_FOUND`,
  telling them their own image does not exist;
- the PDF silently left the original out;
- the overlay generator would have painted a heat map on a grey placeholder
  canvas.

**Change.**
- New error codes in `app/shared/errors.py`:
  `IMG_FILE_MISSING` (410) and `XAI_FILE_MISSING` (410).
- `app/shared/files.py`: `resolve_stored_file` distinguishes "safely inside
  the storage tree but gone" (the caller's `missing` error) from "unsafe or
  wrong type" (still the caller's not-found error). Containment is checked
  before existence, so a missing path outside the tree is still not-found.
- **M1** `router_images.py`: the owner gets `410 IMG_FILE_MISSING` from
  `/file` and `/thumbnail`, and a D6 warning is written. Everyone else still
  gets the same `404 IMG_NOT_FOUND`, because ownership is checked first, so
  no existence is leaked.
- **M3** `router_results.py`:
  - the same for panels (`410 XAI_FILE_MISSING`);
  - `/results` gains `original_available: bool` (**additive change to M3's
    `PredictionResultView`**, default `true`), so a UI can say the file is
    gone instead of showing a broken image.
- **M3** `reporting.py`: the PDF states that the original is no longer
  stored and that the outcome shown is the recorded result. Before, it left
  the original out without saying so.
- **M3** `overlay.py`: no substitute grey canvas. A missing original raises
  `XAI_UNAVAILABLE`; the prediction is unaffected.

**Tests.** `test_missing_files.py`, on a fixture shaped like the migrated
rows: result view, both image endpoints and the panel endpoint (owner 410,
stranger 404), the PDF text (via pypdf), and the overlay refusal.

### 6.7 Explainability is real (phase 3) - and a notice to M3 about the ActivationBundle

**Notice to M3: Contract C2 `ActivationBundle` changed.** PRD2 §7.3 and
PRD4 §4.5 mark it unstable, so the field set can change with notice and
without a version bump. This is that notice.

- `backbone` now admits `"siglip_b16"`. The semantic model is SigLIP
  (ViT-B/16, 224 px, a 14x14 patch grid), not CLIP.
- **`pooling` (new):**
  - `"mean"` for SigLIP. Its classifier mean-pools all 196 patch tokens and
    there is **no CLS token**, so rollout must aggregate over every query
    token.
  - `"cls"` (the default) keeps M3's original CLS-row behaviour.
  - `explain.compute_attention_rollout` takes the matching `pooling`
    argument.
- **`spectrum` changed meaning.** It is now the mean `log(1+|FFT|)` of the
  224x224 RGB patches that SPAI actually analyses (stride 224, five-crop when
  there are fewer than 4 patches, values in [0, 1]). The values come from
  the vendored SPAI config, not hard-coded. It used to be a 512x512
  luminance centre crop that SPAI never sees.
- **`spectrum_meta` (new):** patch size and stride, patch count, five-crop
  flag, analysed size, and SPAI's mask radius (16).
- **`timings_ms` (new):** capture costs, for measurement.

**M3 code changed:**
- `explain.py`:
  - rollout honours `pooling`;
  - a token count that does not fit the grid now raises `XAI_UNAVAILABLE`.
    It used to be truncated or zero-padded, which draws a wrong map;
  - new `CAPTIONS` / `caption_for()` say what each panel shows and what it
    does not (NF.13).
- `overlay.py`:
  - panels are generated independently;
  - `persist_explainability()` returns `generated` / `partial` /
    `unavailable` with reason codes instead of raising (SRS C.3), and
    `generate_and_persist_explainability()` is kept for the stub;
  - the spectrum panel draws SPAI's real r = 16 split (no decorative rings);
  - PNGs carry no metadata and are bounded: the overlay is at most 1600 px
    on its longer side (aspect kept), the spectrum at most 768 px;
  - D5 references are stored relative to the explainability folder.
- `reporting.py`: the PDF shows the original, the semantic overlay and the
  spectrum in every case, each with its caption. It used to drop the
  spectrum whenever the original existed.
- `schemas.py`: `ExplainabilityItem.caption` (additive).

**M2:**
- `detectors.py`: passive forward pre-hooks capture each attention layer's
  input during the normal scoring pass. `attention_maps()` recomputes the
  weights exactly as transformers' eager attention does.
- `xai.py`: the SPAI-patch spectrum.
- `pipeline.py`: assembles the bundle after the timed region; `latency_ms`
  stays inference-only.
- `router_predict.py`: draws and stores the panels after D4 is committed, in
  their own transaction, so a failure rolls back only D5. Reports
  `xai_status` / `xai_reasons` (additive response fields) and an
  `X-XAI-Time-Ms` header, and writes a D6 warning when not `generated`.

**Faithfulness and cost (measured, not assumed).**
- **Faithfulness (rollout is an attention-based proxy):** on 40 validation
  images, semantic branch only, one value per image, masking the
  top-attended 20% changes SigLIP 2's score more than equal random masks:
  - mean gap +0.071 [0.041, 0.103], median +0.019;
  - paired t one-sided p = 4.0e-5; Wilcoxon 5.8e-8; 35/40 images.

  So the caption may say where the model looked, not where an image was
  manipulated. The frequency panel is descriptive and has not been
  validated.
- **Cost:** explainability adds 1.2–3.7 s per request and about 7 MB of
  VRAM. Details in `ml/evaluation/RESULTS.md`.


### 6.8 Model management is real: D3 decides what runs (phase 4, F.19)

**Problem.** M3's `POST /admin/models/{id}/activate` flipped `is_active`,
but nothing read it. `registry.active()` returned config, and every
prediction's `registry.record()` re-activated the config rows, undoing the
admin's choice. Provenance was stale: the semantic row was always `main`
with a null hash, and rows were keyed on (name, version) and never updated.
`tests/test_provenance.py` reproduced both cases, failing, in a commit
before the fix. There was no way to upload anything.

**Change.**
- **M2** `registry.py`, rewritten:
  - `active(db)` reads the ACTIVE D3 row of each type; the pipeline runs
    exactly those and writes their ids into D4;
  - `ensure_registry()` registers the published baseline (pinned SigLIP
    revision and weights SHA-256, SPAI weights digest, fusion w/tau/T) when
    a type has no valid active row; legacy rows stay, unchanged;
  - `activate()` runs the canary, then the quality gate, then the switch in
    one transaction with the type's rows locked;
  - `rollback()` is one call;
  - `baseline()` gives offline scripts the config defaults without a
    database.
- **M2** `gate.py`, `scripts/build_reference_set.py`: the quality gate on a
  cached validation-split sample (`sbr_val`, never the test set).
  Thresholds were fixed before any candidate was scored:
  - accuracy may drop by at most 0.05;
  - FPR may be at most 0.20;
  - AUC may drop by at most 0.02.
- **M2** `model_artifacts.py`, `router_models.py` (C4, `/api/v1/models`,
  admin only):
  - registration of a fusion JSON or a head as `.safetensors`, never pickle;
  - shapes must exactly match the live head, values must be finite, and
    there are size limits;
  - files are stored under their SHA-256; the hash is recorded in D3 and in
    the D6 audit log;
  - a `training_reference` is required.
- **M2** `heads.py`: uploaded heads are cached by row id and are immutable.
  The file hash is re-verified on load.
- **M2** `detectors.py`, `frequency_detector.py`:
  - SigLIP is loaded at the pinned revision, from the local cache first, so
    startup works offline;
  - an uploaded head is applied through a one-call forward hook on the
    published classifier;
  - SPAI's sign convention comes from the active row.
- **Schema** (migration 0002):
  - `models.training_reference`, `models.registered_by`;
  - `predictions.semantic_model_id` and `frequency_model_id` as real
    foreign keys (ON DELETE RESTRICT), backfilled from the JSON;
  - a `model_activations` table (audit trail, rollback);
  - D3 rows immutable by trigger, except `is_active`.
- **M3** `router_admin.py`: `POST /admin/models/{id}/activate` now delegates
  to M2's registry, as PRD3 FR-09 asks; M3 no longer writes D3. A refusing
  gate cannot be forced from the M3 endpoint.

**Scope, stated plainly.** Head uploads were validated ONLY with perturbed
copies of the published heads. This project trains nothing (CLAUDE.md §0),
and a new head would have to come from a third party. Fusion-configuration
swapping is the feature demonstrated end to end.

**Phase 4 review follow-ups (2026-10-03).**
- **Gate anchored to the baseline:** the gate now also refuses a candidate
  more than 0.08 accuracy or 0.04 AUC below the ORIGINAL published baseline,
  so small per-step drops cannot ratchet. The thresholds were fixed before
  scoring. A test walks τ 0.85 → 0.88 → 0.94: each step is allowed by the
  per-step check, and the anchor alone refuses the last.
- **Rollback is restricted to previously active rows.** The canary stays
  blocking and the gate is advisory. The audit entry reads
  `ROLLBACK (gate advisory)` with the metrics. A never-activated row is
  refused on the rollback path (`MDL_ROLLBACK_NOT_PREVIOUS`).
- **Immutability is enforced on BOTH SQLite and PostgreSQL** by a trigger
  (UPDATE of anything but `is_active` refused), plus ON DELETE RESTRICT for
  referenced rows. Tests assert the trigger exists and refuses an UPDATE, and
  that downgrading 0002 drops the trigger, the PostgreSQL function and the
  table cleanly.
- **The scratch-database reset refuses non-scratch names itself**
  (`db.refuse_unless_scratch`: `*_test`/`*_regression` on PostgreSQL, never
  the dev SQLite file), checked before connecting; tested against the dev
  names.
- **Startup warns when config.py differs from the active D3 rows.** Config
  is only a seed now. A test also shows an in-flight prediction keeps the
  model set it resolved at its start when an activation lands mid-request.
- **Activation time** (`ml/evaluation/activation_cost.py`, warm, real API):
  - fusion config ~40 ms (96 ms the first time);
  - SigLIP head 175 ms;
  - SPAI head (55 MB): 378 ms to register, 456 ms to activate;
  - rollback 41 ms.

  With models not yet loaded, the canary adds the ~9 s model load per
  branch. The admin UI should show a long-running state for that case.


### 6.9 React user flows; token removed from report URLs; stored files read from memory (phase 5a)

**Backend (M3 / shared):**
- `router_reports.py`: `GET /reports/{id}` accepts the Authorization header
  only. The `?token=` query parameter (known issue in §5) is removed, because
  a session token in a URL ends up in browser history and in proxy and server
  logs. The legacy dashboard now downloads with `fetch` + header + blob URL.
  Test: a query token gets 401; the header works.
- `router_results.py` / `schemas.py`: `/results` gains `models`, the
  semantic, frequency and fusion D3 rows that produced the prediction (D4's
  foreign keys; additive). The React results page lists them.
- `app/shared/files.py`, `router_images.py`, `router_results.py`: stored
  files are read in full inside a `with` block and sent from memory instead
  of as a streaming `FileResponse`; `overlay.py` writes PNGs through an
  explicitly closed handle. **Why:** after a browser run on Windows the
  server still held three storage files open (two semantic panels and one
  upload), which blocked deleting them. A sequential HTTP reproduction
  (downloads, thumbnails, panels, PDFs, a stream aborted after 1 KB, 60
  near-instant aborts) did NOT reproduce the leak, so the exact trigger is
  unconfirmed. With these changes the full browser scenario leaves the
  server holding no storage files (checked with psutil). Files are bounded
  (uploads <= 10 MB), so reading them into memory is safe.

**Frontend (`frontend/src`, M1's React app):**
- `react-router-dom` routes: `/login`, `/register`, `/verify` (OTP, with the
  console-mode hint), `/` (upload + analyse), `/results/:id`, `/history`.
- Session token in **sessionStorage** (was localStorage): same XSS exposure,
  shorter lifetime - it dies with the tab.
- One API client:
  - error codes mapped to plain messages;
  - a 401 clears the session and returns to `/login?next=`.
- All images and the PDF are fetched with the Authorization header and shown
  through blob URLs, which are revoked on unmount.
- Bug found by the browser run and fixed: a profile request aborted by a page
  reload was treated as "session invalid" and deleted the token. Only a 401
  clears the session now, and the session check no longer re-runs on every
  navigation.
- `InvigilatorPanel.tsx` deleted (approved): it fabricated "passed" results
  without calling the API.
- M1's original components (`Navbar`, `AuthModal`, `AdminLoginModal`,
  `OTPModal`, `ImageUpload`) are no longer rendered and are kept for the
  owner to decide on; compatibility aliases keep them compiling.
- ESLint added, with `react/no-danger` as an error; no
  `dangerouslySetInnerHTML` anywhere.
- `docs/manual-test-react.md`: the manual test script.

### 6.10 Security follow-ups before phase 5b

- **M1 `email_service.py`: console-mode OTP codes no longer reach D6.**
  - The code is printed only to the developer console (stdout logger, never
    persisted). D6 records "2FA OTP issued (console delivery, code not
    logged)".
  - Before this, every console-mode code was readable by admins in the log
    viewer.
  - Existing rows: **0** in the development database. **18** in the scratch
    `truepixels_regression` database, all from automated browser runs.
    None were edited or deleted (the owner decides).
  - Test: `test_console_otp_code_never_reaches_d6`. It fails if the code is
    put back into the audited line.
- **M1 `schemas.py`: the dead `dev_otp` field is removed** from the
  register, login and OTP-verify responses. It was never populated.
- **File endpoints have hard size ceilings now that files are read into
  memory:**
  - originals and thumbnails: 64 MB;
  - explainability PNGs: 16 MB;
  - over the limit: a structured `413 FILE_TOO_LARGE`;
  - PIL's 25 MP decompression guard still applies to decoding;
  - the PDF embeds a 1600 px in-memory copy instead of the full original.
- **The gate's reference cache is content-keyed.** The key is a SHA-256
  over:
  - the SigLIP checkpoint, revision and processor configuration;
  - the SPAI weights digest and patching parameters;
  - the reference image list with each file's SHA-256.

  The gate refuses a cache whose key no longer matches, or that has no key.
  The cache was rebuilt with the key.
- **The React post-login redirect accepts same-origin relative paths only**
  (`safeNext`): absolute, protocol-relative and backslash forms all go to
  `/`. Exercised in the browser with three external targets.
- **JWT lifetime is 8 hours.** Tokens that appeared in `?token=` URLs before
  that was removed have expired; rotating `JWT_SECRET_KEY` once at the end
  of the project is noted for Phase 8.

### 6.11 Phase 5b: admin screens, account policy, legacy dashboard

- **New M1 module, `account_policy.py`.** It is shared by M1's
  `PATCH /users/{id}/status` and M3's `PATCH /admin/users/{id}/status`, so
  the two cannot drift. It refuses:
  - an administrator changing their own status (M3 previously allowed a
    self-"enable");
  - any change that would leave no active administrator. The active admins
    are locked FOR UPDATE on Postgres.

  It also records in its docstring what "remove" does. It is a soft status
  change, identical in effect to "disable":
  - sign-in and open sessions are refused;
  - D2, D4, D5 and D6 rows and stored files are kept, so no files are
    orphaned;
  - "enable" restores everything.
- **M3 `router_admin.py`:**
  - a missing user is now `404 USER_NOT_FOUND`; it was
    `AUTH_INVALID_CREDENTIALS`;
  - refused status changes are audited.
- **M3 `analytics.py` and `schemas.py`: `/admin/analytics` gains `days`,
  `latency` and `latency_over_time`.**
  - The figures are warm-only inference latency: p50 and p95 by linear
    interpolation, overall and per UTC day.
  - Cold-start rows, and rows written before `cold_start` was recorded, are
    counted but excluded from the percentiles.
  - The percentiles are null when there are no warm rows.
  - The new fields are additive, so existing clients are unaffected.
- **M2: `POST /api/v1/models/{id}/gate-preview`** returns the canary and
  gate verdict that activation would reach, without switching or writing
  anything. The admin screen shows each candidate's metrics before anyone
  decides. A test confirms the preview agrees with activation and changes
  nothing.
- **React admin screens** (`src/pages/admin/`): overview (recharts), logs,
  users and models.
  - They show metadata only and never fetch a user's images.
  - They are lazy-loaded, so recharts never reaches non-admin users.
- **M3's legacy dashboard is demoted** (README notes in both places):
  - the XSS sink (log `event_detail` in `innerHTML`) is fixed, and the
    other server-text sinks too;
  - the CLIP labels are renamed;
  - the hard-coded health tile is replaced by the API's error count and
    active-model count;
  - `api_tester.html` "Run All" no longer passes every status, and three
    false descriptions are corrected.

### 6.12 Phase 5b review follow-ups

- **Status changes take effect on the very next request.** This was already
  true: `security.verify_session_token` re-reads `account_status` from D1 on
  every request. It is now tested with tokens from the real login endpoint,
  through both status endpoints, for disable and for remove
  (`test_account_status_enforcement.py`). With the check disabled, all four
  token tests fail.
- **Re-registration after "remove"** is documented in
  `account_policy.py`.
  - The kept D1 row holds the email (unique `lower(email)`).
  - A new registration gets the same `409 AUTH_EMAIL_TAKEN`, with the same
    message, whatever the existing account's status. This is tested.
  - Re-enabling the account is the way back.
- **`POST /models/{id}/gate-preview` is now strictly read-only.** Before
  this fix it:
  - could bootstrap or repair D3 through `registry.active()`;
  - stored the candidate's uploaded head in the process-wide head cache.

  It now reads the active rows without repairing them (and returns 409
  `MDL_NO_ACTIVE_CONFIGURATION` instead), and builds uncached heads
  (`heads.no_store()`). A test snapshots every table (row count and a
  digest of every row), the head cache and the reference file around two
  previews. The test fails if the head-cache fix is removed.
- **M3 `reporting.py`:** the PDF captions its image "Downscaled copy of the
  original (W x H px) ... the analysis ran on the full-resolution original"
  when the original is over 1600 px, and "Copy of the original image" when
  it is not. Tested for both cases.
- **`api_tester.html`:**
  - no hard-coded ids: results, explainability and PDF use the signed-in
    user's newest prediction;
  - without one, those requests are SKIPPED, not failed;
  - the prediction POST is never run by "Run All" (it creates data);
  - the isolation probe uses an id that does not exist, with an honest
    description;
  - expected statuses follow the persona (401 for an invalid or missing
    token, 403 for admin endpoints when not an admin).

  Browser run: `10 passed, 0 failed, 1 skipped`. With an invalid token:
  0 failed, all 401.
- **`docs/rotate-secrets.md`:** steps to rotate the Postgres password and
  the JWT key without printing either value.

### 6.13 Sign-in and OTP throttling, before Phase 6

- **Finding (M1, not changed here):** a session can be obtained with an email
  address and an OTP alone. `/auth/otp/send` issues a code to any address,
  and `/auth/otp/verify` exchanges it for a full session token, for any
  role, even with `REQUIRE_2FA` off. The OTP is therefore a password-free
  sign-in, not a second factor. The limits below bound guessing; closing the
  path itself is proposed separately.
- **New M1 module `throttle.py`** (in memory; resets on restart; one counter
  set per worker):
  - **Sign-in:** `/auth/login` and `/auth/admin/login` share one counter,
    keyed by (email, client IP).
    - The first 3 failures cost nothing.
    - After that, each failure doubles the wait: 1, 2, 4 s and so on, up to
      60 s. A waiting key gets `429 AUTH_RATE_LIMITED` with `Retry-After`.
    - There is no lockout, and a correct password clears the key.
    - Unknown addresses are throttled exactly like real ones.
  - **OTP codes:** the 5th wrong code invalidates the code. Any newly
    issued code resets the count.
  - **`/auth/otp/send`:** a 60 s cooldown and at most 5 sends per hour, per
    address, whether or not the account exists.
    - Every case gets **one identical answer**. The old code answered
      unknown addresses differently, which revealed which accounts exist.
    - Unknown addresses pay the same hashing cost.
  - **Client IP** = `request.client.host`, the address uvicorn resolved.
    `X-Forwarded-For` counts only from `--forwarded-allow-ips`, so a
    spoofed header from a direct client is ignored (tested).
  - **Audit log:** throttle events reach D6 at most once a minute per key.
  - **Memory:** at most 10,000 keys per table.
- **M1 `router_auth.py`:** calls the throttle; one answer for `/otp/send`.
- **Shared `errors.py`:**
  - new code `AUTH_RATE_LIMITED` (429);
  - the handler passes an exception's `headers` through (used for
    `Retry-After`).
- **Shared `db.py`:** `ensure_scratch_database_exists` CREATEs a dropped
  `*_test` / `*_regression` database, for those names only.
  `regression_check.py` was proven against a database that did not exist:
  created, migrated, 24/24 images bit-identical. `truepixels_regression`
  was then dropped, as approved.
- **`compose.yaml`:** the database container receives only `POSTGRES_USER`,
  `POSTGRES_PASSWORD` and `POSTGRES_DB`. It used to receive all of
  `backend/.env`, including `JWT_SECRET_KEY`. Compose now needs
  `--env-file backend/.env`. The running container was **not** recreated;
  that is step (c) of `docs/rotate-secrets.md`.
- **`backend/scripts/verify_rotation.py`:** checks a rotation and prints
  only True/False.
- **Tests:** `test_throttle.py`, 11 tests on an injectable clock, no sleeps.

### 6.14 M1's superseded React components deleted (M1 owner informed first)

M1 built these components before the routed React app existed. Since Phase
5a/5b the pages under `frontend/src/pages/` replace them, and none of them
was rendered. Deleted, with the user's go-ahead after the M1 owner was told:

| Deleted | Replaced by |
|---|---|
| `features/m1_access/AuthModal.tsx` | `pages/AuthPages.tsx` (`LoginPage`, `RegisterPage`) |
| `features/m1_access/OTPModal.tsx` | `pages/AuthPages.tsx` (`VerifyOtpPage`) |
| `features/m1_access/AdminLoginModal.tsx` | the "Sign in as administrator" option on `LoginPage` |
| `features/m1_access/ImageUpload.tsx` | `pages/UploadPage.tsx` (upload **and** analyse) |
| `features/m1_access/AdminUserManagement.tsx` | `pages/admin/UsersPage.tsx` (confirmations, soft-delete wording, last-admin rule) |
| `components/Navbar.tsx` | `components/Layout.tsx` |
| `components/ErrorBanner.tsx` | `components/Feedback.tsx` (`ErrorNotice`) |

The compatibility shims that existed only for these components were removed
with them:

- the deprecated `login` / `logout` / `token` aliases in `AuthContext`;
- the `ImageUploadResult` type (in `types.ts`, re-exported from
  `client.ts`);
- their ESLint style-rule exemption.

The security rules (`react/no-danger`) now apply to all of `src/` without
exception. Type check, lint and production build are clean. Nothing in
`backend/` changed. The files remain in git history (`git log --
frontend/src/features`).

### 6.15 OTP is a second factor, not an email-only sign-in (M1)

Before this change, `/auth/otp/send` issued a code to any registered
address, and `/auth/otp/verify` turned that code into a full session. This
worked for any role, admins included, and even with 2FA off. M1 files
changed:

- **New `otp_challenge.py`.** A code exists only inside a challenge with a
  purpose:
  - `login`: created only after a correct password, by `/auth/login` or
    `/auth/admin/login`;
  - `register`: created only by `/auth/register`, role User only.

  It refuses to issue codes in production without real e-mail delivery
  (`503 OTP_DELIVERY_UNAVAILABLE`). An SMTP failure clears the challenge
  instead of falling back to the console.
- **`router_auth.py`:**
  - with 2FA off, `/otp/send` and `/otp/verify` answer `403 AUTH_FORBIDDEN`;
  - `/otp/send` only re-sends a pending challenge, with the same purpose,
    and can never start one;
  - `/otp/verify` requires the purpose to match, and a `register` challenge
    is redeemable only by role User;
  - a wrong purpose or another account's code gets the same "invalid or
    expired" answer and counts as a wrong attempt;
  - challenges are single use;
  - register, login and admin login all issue codes through
    `otp_challenge`.
- **`schemas.py`:** `OTPVerifyRequest.purpose` (`login` | `register`,
  default `login`). The React verify page sends `purpose=register` after
  registration. The legacy dashboard only verifies sign-in codes, so the
  default suits it.
- **`models.py`, migration `0003`:** a `users.otp_purpose` column with a
  check constraint. On SQLite this is a plain `ALTER TABLE`: a batch
  rebuild silently drops the expression index `uq_users_email_lower`, and
  the migration tests caught that.
- **`config.py`:** `is_production()`, read at call time.
- **`email_service.py`:** outside development the console fallback is
  disabled, so a code is never printed.
- **M1's test `test_m1_auth.py::test_otp_send_and_verify_flow`** used the
  email-only path. It now signs in with the password first (2FA on), then
  runs its original send and verify steps.
- **Hashing:** codes were already stored as Argon2id hashes and compared in
  constant time (argon2-cffi verify). No change was needed.
- **Tests:** `test_otp_challenges.py` (12):
  - email-only send/verify refused for a User and an Admin, and with 2FA
    off;
  - an Admin cannot get a session from a registration challenge;
  - cross-purpose and cross-account redemption refused;
  - re-send keeps the purpose;
  - production refuses to issue codes without real e-mail and never falls
    back to the console.

  With the email-only send restored, the email-only tests fail.

### 6.16 Per-account sign-in counter; eviction that flooding cannot exploit (M1)

- **`throttle.py`:** a second sign-in counter keyed by email alone, any IP.
  It allows 10 free failures, then the same 1–60 s doubling, so rotating
  addresses does not escape it. A request waits for the longer of the
  per-address and per-account waits. Delay only, never a lockout.
- **Eviction is no longer plain LRU.** At a full table:
  1. expired entries go first;
  2. then the entry with the fewest failures or sends goes;
  3. an entry currently enforcing a delay or cap is never evicted;
  4. when all entries are enforcing, the new key goes untracked (and that
     is logged).

  Tests show flooding 4× the table size leaves an active counter intact;
  with LRU put back, those tests fail.
- **State stays in memory and resets on restart** (documented in
  `docs/auth-hardening.md`).
- **Also:**
  - `test_scratch_guard.py`: `CREATE DATABASE`, and `regression_check.py`,
    refuse any name without `_test`/`_regression`, the development
    database `truepixels` included, before any connection;
  - `verify_rotation.py` can no longer print a value even when it fails
    (sentinel test);
  - tag `pre-m1-cleanup` marks `b0a9597`, the commit before the M1
    deletion.

### 6.17 OTP and throttle follow-ups (M1)

- **Expired challenges no longer keep their hash in D1.**
  `otp_challenge.purge_expired()` clears hash, expiry and purpose in one
  `UPDATE`. `main.py` runs it at startup and every 60 s in a background task
  that is cancelled on shutdown. Redeemed challenges and those killed by
  wrong attempts were already cleared on the spot. Tested, including that the
  lifespan runs the purge.
- **Any redeemed code marks the address verified.** With 2FA on, an account
  whose registration code was never redeemed still gets no session without
  a mailbox code. The sign-in code now also sets `is_email_verified`; before
  this, the flag stayed False for such accounts. With 2FA off (the default),
  verification is optional and never checked; this is documented.
- **Throttle fallback.** A sign-in attempt that cannot get its own counter
  (every slot enforcing) falls back to a per-IP counter, then to a global
  window of 30 untracked failures a minute, instead of no throttling.
  Capacity is 10,000 keys per table. Tested.
- **Documented in `docs/auth-hardening.md`:** a crash loop resets the
  in-memory throttle state. The registration-squatting residual risk is
  reported, not fixed.

### 6.18 Phase 6: HTTPS, environment default, proxy trust

- **M1 `config.py`:** `ENVIRONMENT` and `is_production()` now default to
  **production** when the variable is unset. Only an explicit
  `ENVIRONMENT=development` enables console OTP delivery. The test conftest
  sets `development`; production tests set it themselves.
- **`main.py`:**
  - `/docs`, `/redoc` and `/openapi.json`, plus M3's legacy dashboard (`/`,
    `/api-tester`, `/developer`, `/playground`), exist only in development;
  - CORS comes from `config.cors_allowed_origins()`, which is empty in
    production unless `TRUEPIXELS_CORS_ORIGINS` is set;
  - `TrustedProxyMiddleware` is added.
- **New `shared/proxy.py`.** Forwarded headers are trusted only with the
  proxy's shared secret (constant-time compare); otherwise they are
  stripped. The reason: behind Docker Desktop, every proxied request reaches
  uvicorn from `127.0.0.1` (measured). uvicorn therefore runs with
  `--no-proxy-headers`. Unit tests are in `test_proxy_trust.py`. A first
  version kept the header keys as bytes, so trust never applied; the live
  positive control caught it and a unit test now covers it.
- **Frontend:**
  - Google Fonts were replaced by `@fontsource` packages, bundled and
    same-origin (privacy and CSP);
  - `vite.config.ts` sets `assetsInlineLimit: 0`, so no asset ships as a
    `data:` URI;
  - new `public/favicon.svg` (the old `vite.svg` link pointed at a missing
    file).
- **E2E:**
  - `csp_guard.py`: `TP_BASE`, `ignore_https_errors` over HTTPS, and a
    CSP/mixed-content watch that fails the run;
  - the two `wait_for_function` waits became locator waits: Playwright's
    string predicates use page-side `eval`, which the CSP blocks;
  - new `run_prod_smoke.py`.
- **Infra:**
  - `infra/caddy/{common.caddy, Caddyfile.dev, Caddyfile.prod}`;
  - `caddy-dev` and `caddy-prod` compose profiles;
  - `infra/check_https.py`;
  - `infra/caddy/data/` and `config/` are gitignored (local CA private key);
  - `PROXY_SHARED_SECRET` was added to `backend/.env` (generated, never
    printed) and to `.env.example`.

### 6.19 Parity check against M1.zip (2026-10-05)

`M1.zip` is the original M1 project, gitignored. It was compared file by file
with this repository:

- **10 of 12 M1 files are identical**, including `security.py` and
  `validation.py`.
- **`config.py` and `email_service.py`** differ only by the 2026-09-30
  integration fixes: a Gmail address, a Gmail app password and a JWT key were
  hard-coded as defaults in the source.
- **All 11 M1 endpoints exist here.**
- **M1's tests:** `test_m1_api`, `test_m1_preprocess` and `test_m1_validation`
  are identical. `test_m1_auth` differs only by the approved password-first
  OTP change (6.15).

**Why e-mail OTP worked in M1.zip and not here:** the zip ships working Gmail
credentials, both hard-coded and in its `.env`, while `backend/.env` held a
different account and a password Gmail rejects. The zip's `SMTP_*` values
were copied into `backend/.env`. No code changed. Delivery is now confirmed:
D6 reads "2FA OTP email delivered via Gmail TLS". That app password appears
in M1's source, so the M1 owner should revoke and replace it.

**The one missing feature was drag-and-drop on the upload page**, which M1's
`ImageUpload` had. It is now in `pages/UploadPage.tsx`, and a dropped file
goes through the same client-side checks as the file dialog.

M1's preview and reset were already here. Its "progress" bar was three fixed
steps (20/60/100 %); here the real stages are shown instead (Uploading, then
Analysing with a live timer).

### 6.20 Landing page and separate sign-in portals, as in M1 (2026-10-05)

- **New `pages/LandingPage.tsx`.** Signed-out visitors at `/` see M1's landing
  view: the "Image Authenticity & Integrity Pipeline" badge, "Verify Still
  Image Authenticity", and the locked "Authentication Required to Upload"
  panel (C.6) with Sign In and Create Account. M1's copy described a CLIP
  pipeline; the wording now describes the two detectors that actually run.
  Signed-in users still get the analyse page at `/`.
- **Separate portals.**
  - `/login` is for users only; the "Sign in as administrator" checkbox is
    removed.
  - `/admin/login` is the amber "Administrator Portal" (M1's
    `AdminLoginModal` wording: "Admin Email", "Master Password"). It calls
    `/auth/admin/login`, which refuses non-admins with `AUTH_FORBIDDEN`.
  - `/register` is Create Account.
- **Navbar when signed out:** Admin Login, Sign In and Create Account, as in
  M1's `Navbar`. Signed in, it shows the email and a role badge.
- **Navigation:**
  - signing out returns to the landing page;
  - the admin area, and an expired admin session, send you to
    `/admin/login`.
- **No backend change.**
- **Tests:**
  - e2e scripts use the portals, with a new step 19;
  - `vite.config.ts` reads `TP_API_TARGET`, so a scratch API can sit behind
    a second dev server.
- **Incident:** the first e2e attempt ran `npx vite` with an inline variable
  that did not take effect, so the run hit the live demo API. It created two
  test accounts in the development database (`react…@example.com` and
  `other…@example.com`, ids 3 and 4) with no images or other data. Nothing
  else changed: no models, no activations, no admin actions or status
  changes. Each suite run now first proves that a probe request reached the
  scratch API.

### 6.21 Confidence is measured from the decision threshold (2026-10-05)

- **Reported by the user:** a "Real" verdict showing under 50 % confidence.
  Prediction #9: SigLIP 2 gave 0.837, SPAI 0.419, fused 0.523. That is below
  tau = 0.7558, so the verdict is Real, and the confidence was
  1 - 0.523 = 47.7 %.
- **Cause:** PRD2 FR-04's `fusion` / `1 - fusion` assumes tau = 0.5. With the
  validation-chosen tau of 0.7558, every fused score in [0.5, tau) was called
  Real with a confidence below 0.5.
- **Fix (M2 `fusion.py`, `confidence_in_prediction`):**
  - AI Generated: `0.5 + 0.5 * (fusion - tau) / (1 - tau)`
  - Real: `0.5 + 0.5 * (tau - fusion) / tau`

  This is 0.5 at tau and 1.0 at the far end, monotonic, and never below 0.5.
  At tau = 0.5 it equals FR-04 exactly. Prediction #9 now reads "Real,
  65.4 %". Classes and scores are unchanged.
- **Migration 0004** recomputes `confidence_score` for every stored D4 row
  from its own fused score, class and its fusion configuration's tau. The
  downgrade restores the original values exactly; tested in both directions.
- **Tests:**
  - every threshold and score keeps confidence at or above 0.5;
  - confidence grows with distance from the threshold;
  - at tau = 0.5 the result is exactly FR-04;
  - the over-HTTP test reads the active tau.
- **Not changed:** M3's test-only stub (`app/stubs/m2_stub.py`) keeps
  `1 - fusion`. It runs at tau = 0.5, where the two rules are identical.
- **Phase 8:** record this as a deviation from PRD2 FR-04 (the formula), not
  from its intent (confidence in the predicted class).

### 6.22 Signed-in layout: the four tabs of M3's original dashboard (2026-10-05)

After sign-in, the React app now uses the original dashboard's numbered tabs
and header options:

1. **Forensic Detection** (`/`, including `/results/:id`): scan an image,
   see the verdict.
2. **User Scan History** (`/history`). It also carries the dashboard's
   "Strict Data Privacy & User Isolation (F.13 / MM3.1)" panel with its
   **Test Security Barrier** button. The button asks for an id that is not
   yours and passes only on the exact `404 INF_PREDICTION_NOT_FOUND`.
3. **Admin Dashboard & Analytics** (`/admin`, with its Overview, Logs, Users
   and Models sub-tabs). It is shown to everyone, as in the dashboard, with a
   lock icon for non-admins, who get "Administrators only". The API enforces
   the role regardless.
4. **1-Click Verification** (`/verification`, new `VerificationPage.tsx`):
   the dashboard's Live Verification Suite, run as the signed-in user.
   - Checks: health; readiness (`ready: true`); session; 401 without a
     session; your newest result (confidence ≥ 0.5); its PDF; the security
     barrier (404 with the exact code); the admin summary (200 for admins,
     403 for users).
   - Exact-status matching. A check that needs one of your predictions is
     SKIPPED without one.

**Header:** the email with a role badge, and **Sign Out** with a confirmation
dialog, as in the dashboard. `ConfirmDialog` moved to `components/` so it is
shared.

**Not carried over: the "API Console" link.** It opened the legacy
`/api-tester` page, which is development-only, is never served through
Caddy, and loads CDN scripts that the production CSP blocks. Tab 4 covers its
"Run All" purpose.

**Dev server:** `vite.config.ts` also proxies `/ready` and `/health`, the
paths Caddy proxies, so readiness answers from the API in development too.

**e2e:**
- step 20 covers the tabs, the barrier, the locked admin tab, a full
  verification run with no failures, and the sign-out confirmation (Cancel
  keeps the session);
- A1 now checks the locked admin tab;
- the sign-out steps confirm the dialog.
