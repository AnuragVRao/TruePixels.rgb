# Manual test script - React front end (user flows, Phase 5a)

Run against a backend and the Vite dev server:

```bash
docker compose up -d db                      # repo root
cd backend && alembic upgrade head
python -m uvicorn app.main:app --port 8000   # leave running; OTP codes print here in dev
cd ../frontend && npm install && npm run dev # http://localhost:3000 (proxies /api to :8000)
```

Each step lists what to do and what must be true. "Console" means the
backend terminal (with no SMTP configured, OTP codes are printed there).

| # | Flow | Steps | Expected |
|---|---|---|---|
| 1 | Guard | Open `/history` while signed out | Redirected to `/login?next=/history` |
| 2 | Register | `/register`: name, email, weak password, then a valid one (10+ chars, letter, digit) | Rule list turns green; the button is enabled only when all pass |
| 3 | OTP (2FA on) | Submit registration | Lands on `/verify`; the page explains the console fallback; the code appears in the console |
| 4 | OTP wrong code | Enter `000000` | Error notice "Email or password is incorrect" (`AUTH_INVALID_CREDENTIALS`) with code shown; no crash |
| 5 | OTP right code | Enter the console code | Signed in, back on `/` (or the `next` page) |
| 6 | Upload validation | Choose a `.gif`, a >10 MB file, a 32x32 PNG | Each is refused before upload with a specific message |
| 7 | Analyse (xai on) | Choose a normal JPG/PNG, keep "Include explainability" ticked, Analyse | "Uploading…", then "Analysing… Ns" with a live timer; then the results page |
| 8 | Results | On the results page | Verdict, confidence %, band; three branch scores; original image; "SigLIP 2 attention rollout" and "SPAI patch spectrum" panels with the backend's captions as text; model rows listed |
| 9 | PDF | Click "PDF report" | A PDF downloads (fetched with the Authorization header; no token in the URL) |
| 10 | Small image | Analyse a 160x160 PNG | Results show "not measured" for the frequency score, the semantic-only warning, and the partial-explainability note |
| 11 | xai off | Untick explainability, Analyse | Results show no panels and "No explainability panels were requested" |
| 12 | History | `/history` with more than 20 results (the automated run seeds 25 extra) | Newest first, thumbnails load, 10 per page, Previous/Next work and Next is disabled on the last page; clicking a row opens its result |
| 13 | Not yours | Open `/results/<another user's id>` | "That result was not found." (`INF_PREDICTION_NOT_FOUND`) |
| 14 | Expired session | Delete `tp_token` in sessionStorage (DevTools) and click History | Redirected to `/login?expired=1…` with "Your session ended" |
| 15 | Sign out | Sign out | Back to `/login`; `/history` redirects to sign-in again |
| 16 | Missing original | A record whose upload file is gone (e.g. migrated dev data) | "The original image is no longer stored" notice, no broken image |
| 17 | Narrow screen | Resize to ~375 px wide | Navigation collapses to icons; no horizontal scroll; panels stack |
| 18 | Safe redirect | Open `/login?next=https://evil.example`, also `//evil.example` and `/\evil.example`; sign in | Always lands on `/` of this site, never the external target |

## Automated run - what was and was not exercised in a browser

`frontend/e2e/run_manual_flows.py` drives these steps in **headless Chromium
only** (Playwright 1.55; no Firefox/Safari/Edge run), against the live dev
servers and a scratch database. "375 px" is **viewport emulation** in that
Chromium, not a real phone.

Last run: 2026-10-03, all automated checks passing.

| Doc step | Automated? | Notes |
|---|---|---|
| 1-6 | yes | |
| 7 + 8 | yes, as one check | analyse then inspect results in the same flow |
| 9 | yes | asserts no request URL contains `token=` |
| 10, 11 | yes | |
| 12 | yes | 28 results: pages of 10/10/8, Next disabled on the last page |
| 13 | yes | second user in a separate browser context |
| 14 | yes | token replaced by an invalid one (not a naturally expired 8 h token) |
| 15 | yes | includes returning to the `next` page after OTP |
| 16 | yes | deletes the scratch originals, then checks the notice and thumbnails |
| 17 | partly | 375 px emulation, **login page only** - results/history at 375 px were not checked |
| 18 | yes | the three external forms above |
| not in this table | no | admin flows (Phase 5b), real e-mail delivery, real phones, browsers other than Chromium |

## Admin flows (Phase 5b)

Sign in with "Sign in as administrator" ticked. Every number on these
screens comes from the API; none is hard-coded.

| # | Flow | Steps | Expected |
|---|---|---|---|
| A1 | Non-admin | Sign in as a normal user, open `/admin/users` | No "Admin" link; "Administrators only."; the API answers 403 `AUTH_FORBIDDEN` to `/admin/*` and `/models*` with that token |
| A2 | Overview | `/admin` | Tiles show `/admin/summary` and `/admin/analytics`: errors in the last 24 h, active models, warm-only p50/p95 latency with the count of excluded cold starts; empty states when there is no data |
| A3 | Logs | `/admin/logs`; Next/Previous; Severity = error | 25 per page; filters narrow the list; log text that contains HTML is shown literally and never runs |
| A4 | Users | `/admin/users`; Disable / Enable / Remove another account | A confirmation explains that nothing is deleted (images, results and files are kept); your own row has no actions; the API refuses self-changes and leaving no active admin (409 `ADM_ACTION_NOT_PERMITTED`) |
| A5 | Models | Register a fusion JSON with tau 0.05; Check quality gate; Activate; Override the gate…; Roll back | Gate metrics framed as "a coarse safety net, not a verification"; plain activation refused, nothing changes; override needs a reason of 10+ characters plus a tick box, and is recorded as forced; rollback is offered only where an earlier activation exists; a passing candidate shows "Running canary and quality gate… Ns", then activates |
| A6 | Narrow screen | 375 px | No page-level horizontal scroll on the four admin screens (wide tables scroll inside their own box) |
| A7 | Expired admin session | Corrupt `tp_token`, open Logs | `/login?expired=1&next=/admin/logs` |
| A8 | Metadata only | Throughout | Admin screens never request a user's image, thumbnail or panel |

### What ran in a browser (2026-10-03)

The following ran in **headless Chromium only**, against a scratch Postgres
database (`truepixels_regression`), with all 8 checks passing:

- `frontend/e2e/seed_admin_scratch.py`, then
  `frontend/e2e/run_admin_flows.py`, automate A1 to A8 as written above.
  - A2 also compares each tile with the JSON the API returns.
  - A5 restores the original fusion configuration by rollback before it
    ends.
  - A4 re-enables every account it changed.
- `frontend/e2e/check_legacy_dashboard.py` checks the legacy dashboard
  (`/`, `/api-tester`), with all 9 checks passing:
  - a seeded `<img onerror>`/`<script>` log row is shown as text and does
    not execute;
  - there are no CLIP labels and no hard-coded health tile;
  - the error tile equals `/admin/summary`;
  - "Run All" reports `8 passed, 4 failed`. The 4 are example ids that do
    not belong to this admin, so they are reported, not hidden.

**Not exercised in a browser:**
- uploading semantic or SPAI head files through the form (the backend
  tests cover those uploads);
- refusal of the last active administrator (it cannot be reached over HTTP;
  it is covered by `test_admin_policy.py`);
- a naturally expired 8-hour token;
- browsers other than Chromium;
- real phones.
