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
| 12 | History | `/history` | Newest first, thumbnails load, pagination when >10 results; clicking a row opens its result |
| 13 | Not yours | Open `/results/<another user's id>` | "That result was not found." (`INF_PREDICTION_NOT_FOUND`) |
| 14 | Expired session | Delete `tp_token` in sessionStorage (DevTools) and click History | Redirected to `/login?expired=1…` with "Your session ended" |
| 15 | Sign out | Sign out | Back to `/login`; `/history` redirects to sign-in again |
| 16 | Missing original | A record whose upload file is gone (e.g. migrated dev data) | "The original image is no longer stored" notice, no broken image |
| 17 | Narrow screen | Resize to ~375 px wide | Navigation collapses to icons; no horizontal scroll; panels stack |
