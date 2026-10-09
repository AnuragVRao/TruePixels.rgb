# TruePixels.rgb

Detects AI-generated images by running **two independently pretrained models**
over the same picture and fusing their verdicts:

- a **semantic** branch — [`prithivMLmods/AIorNot-SigLIP2`](https://huggingface.co/prithivMLmods/AIorNot-SigLIP2),
  a SigLIP 2 fine-tune, which asks *what is this a picture of, and does it look
  like the AI images it was trained on*;
- a **frequency-domain** branch — [SPAI](https://github.com/mever-team/spai)
  (CVPR 2025), which ignores content and asks *does this pixel grid carry the
  spectral signature of a synthesis pipeline*.

A generator that defeats one kind of evidence has no particular reason to
have defeated the other. The measurements below show where that holds and
where it does not.

> **This project never trains, fine-tunes or retrains a model.** Every score
> comes from a third-party checkpoint used exactly as published. Where the
> PRDs call for a trained component, the architecture uses pretrained weights
> instead; the supersessions are recorded in `CLAUDE.md` §8.

**Contents:** [Requirements](#requirements) · [Setup](#setup) ·
[Database](#database-postgresql--migrations) · [Run](#run) · [HTTPS](#https) ·
[Tests](#tests) · [Demo](#demo) · [What it measures](#what-it-measures-honestly) ·
[Project structure](#project-structure) · [Documentation](#documentation) ·
[Licences](#licences)

---

## Requirements

| | |
|---|---|
| Python | **3.13**. The pinned torch wheel does not exist for 3.14. |
| Node.js | 20 or newer, for the React front end |
| Docker Desktop | PostgreSQL 16 and the Caddy HTTPS proxy run in containers |
| GPU (optional) | An NVIDIA card with CUDA 12.6 drivers. About 25× faster than the CPU; developed on an RTX 4050 (6 GB). |
| Disk | About 2 GB for model weights (SPAI 560 MB, SigLIP 2 about 370 MB) |

The commands below are written for **Windows PowerShell**, the development
platform. On Linux or macOS, use `source .venv/bin/activate` and `cp`.

## Setup

**1. Python environment**, from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
# GPU: pip's default index only has the CPU build, so name the +cu126 build explicitly.
pip install --index-url https://download.pytorch.org/whl/cu126 "torch==2.13.0+cu126" "torchvision==0.28.0+cu126"
python -c "import torch; print(torch.cuda.is_available())"   # True with a working GPU
```

**2. Front end:**

```powershell
cd frontend; npm install; cd ..
```

**3. SPAI weights (one-time).** They are published on Google Drive, which
cannot be fetched reproducibly by URL, so nothing downloads them for you.

1. Download `spai.pth` (935 MB) from the link in
   `config.DETECTOR_FREQUENCY_SOURCE_URL` (`backend/app/shared/config.py`)
   into `storage/models/`.
2. Convert it:

   ```powershell
   cd backend; python scripts/convert_spai_checkpoint.py; cd ..
   ```

The converter:
- verifies the upstream SHA-256;
- extracts only the tensors, under a restricted unpickler;
- writes `storage/models/spai.safetensors` and prints its digest.

The server then loads that file **strictly** (all 324 weights) and checks it
against the pinned digest. SigLIP 2 downloads itself from Hugging Face the
first time the server starts.

**4. Configuration.**

```powershell
Copy-Item backend\.env.example backend\.env
```

Then edit `backend/.env`. It is gitignored: **never commit it**.

| Key | What to set |
|---|---|
| `ENVIRONMENT` | `development` for local work. **Unset means production**: no `/docs`, no legacy dashboard, and no OTP codes printed to the console. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Database credentials. Generate the password with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `DATABASE_URL` | `postgresql+psycopg://<user>:<password>@127.0.0.1:5433/<db>`, using the same three values |
| `JWT_SECRET_KEY` | Session signing key: `python -c "import secrets; print(secrets.token_hex(48))"` |
| `PROXY_SHARED_SECRET` | Shared with Caddy, which the API trusts for client addresses: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `REQUIRE_2FA` | `True` to require an e-mailed one-time code at sign-in. Optional, **off by default**. |
| `EMAIL_BACKEND`, `SMTP_*` | `smtp` with a Gmail **app password** (16 letters) for real e-mail. `console` prints codes in the API window, in development only. |
| `TRUEPIXELS_CORS_ORIGINS` | Leave unset; the app is same-origin. Set it only for a genuine cross-origin client, HTTPS origins only. |

Rotating secrets later: [docs/rotate-secrets.md](docs/rotate-secrets.md).

## Database: PostgreSQL + migrations

```powershell
docker compose --env-file backend/.env up -d db      # PostgreSQL 16 on 127.0.0.1:5433, data in a named volume
cd backend
alembic upgrade head                                  # the ONLY way the schema is created or changed
python seed_admin.py                                  # once: creates admin@truepixels.rgb
cd ..
```

- **`--env-file backend/.env` is required** on every `docker compose` command.
  Compose refuses to run without it, rather than start a database with a
  guessable password.
- **Admin password:** `seed_admin.py` uses `SEED_ADMIN_PASSWORD` if it is
  set; otherwise it generates one and prints it once.
- **Out-of-date schema:** the server refuses to start on a database that is
  not at the latest migration, and names the command to run.
- **Stopping:** `docker compose --env-file backend/.env down`. **Never add
  `-v`**, which deletes the data volume.
- **SQLite instead of Docker:** set `DATABASE_URL=sqlite:///./truepixels.db`
  and run `alembic upgrade head` as above.
- **Branches:** `main` runs the migration chain `0001 … 0005 → 0006c`. The
  `decision-map-1` branch holds the calibrated-P(AI) work and has a
  *different* `0006`. A database migrated on one branch must be taken back to
  `0005` on that branch (`alembic downgrade 0005`) before the other branch
  will start on it.

## Run

### One command: `start.cmd` / `stop.cmd`

Once setup is done, double-click **`start.cmd`** in the repository root, or
run `.\start.ps1`. It:

1. starts Docker Desktop if needed, then the database;
2. applies pending migrations;
3. opens the API in its own **"TruePixels API"** window and waits for the
   models (keep that window open);
4. builds the front end if needed;
5. starts Caddy and opens **https://localhost**.

**`stop.cmd`** (or `.\stop.ps1`) stops the API, Caddy and the database.
**Data is kept.**

| Option | Effect |
|---|---|
| `start.cmd -ConsoleCodes` | Print sign-in codes in the API window instead of e-mailing them (needs `ENVIRONMENT=development`) |
| `start.cmd -Build` | Force a front-end rebuild (it already rebuilds automatically when `frontend/` sources are newer than the last build) |
| `start.cmd -NoBrowser` | Do not open the browser |
| `stop.cmd -KeepDatabase` | Leave PostgreSQL running |

The manual steps, if you prefer:

### Manually

**API**, from `backend/`. It runs on the host, not in Docker, because it
needs the GPU.

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

- **Start-up:** both models load and warm up first (about 10–20 s). `GET /ready`
  answers 503 until they are ready, then 200.
- **One worker on purpose:** each extra worker would load its own copy of
  the models (about 3.4 GB of VRAM).
- **`--no-proxy-headers` is deliberate:** client addresses are trusted only
  from Caddy, by shared secret ([docs/https.md](docs/https.md)).

**Front end for development** (hot reload; `/api` is proxied to :8000):

```powershell
cd frontend; npm run dev        # http://localhost:3000
```

The interface works like this:
- **Signed out:** a landing page with **Create Account**, **Sign In** and
  **Admin Login** (the Administrator Portal).
- **Signed in:** four tabs:
  1. Forensic Detection;
  2. User Scan History;
  3. Admin Dashboard & Analytics - **administrators only**; a normal user
     does not see this tab, so their tabs run 1, 2, 3 (Forensic Detection,
     User Scan History, 1-Click Verification);
  4. 1-Click Verification.

With `ENVIRONMENT=development`, M3's legacy static dashboard is also served
at <http://127.0.0.1:8000/>, and the API reference at `/docs`.

## HTTPS

Caddy runs in Docker in front of the API and serves the production build of
the front end.

```powershell
cd frontend; npm run build; cd ..                     # once per front-end change
docker compose --env-file backend/.env --profile https-dev up -d caddy-dev
# open https://localhost  (HTTP redirects to HTTPS)
docker compose --env-file backend/.env --profile https-dev stop caddy-dev
```

| Profile | Certificate | Listens on | HSTS |
|---|---|---|---|
| `https-dev` | Caddy's local CA | 127.0.0.1:80/443 | no |
| `https-prod` | `TP_TLS=internal`, or an e-mail address for a real Let's Encrypt certificate (`TP_SITE_ADDRESS` = your domain) | all interfaces | yes |

- **Run one profile at a time.** If ports 80/443 are taken, set
  `TP_HTTP_PORT` and `TP_HTTPS_PORT`.
- **Browser warning:** stop it by trusting the local CA **on this machine
  only**:

  ```powershell
  certutil -user -addstore Root infra\caddy\data\dev\caddy\pki\authorities\local\root.crt
  ```

  The CA's private key lives in `infra/caddy/data/`, which is gitignored.
  Never commit it or share it.
- **Security headers:** Caddy sets a strict CSP (no inline or eval scripts),
  `nosniff`, `no-referrer`, `DENY` and `Permissions-Policy`, and caps
  request bodies.

Removing trust, the ACME path and the reasoning behind each choice are in
[docs/https.md](docs/https.md).

## Tests

**Backend**, from the repository root:

```powershell
python -m pytest backend/tests -q                  # everything (SQLite scratch DB); ~7 min with the GPU
python -m pytest backend/tests -q -m "not slow"    # skip the model-backed tests
python -m pytest backend/tests/m1 -q               # M1's own suite
python -m pytest backend/tests/m3 -q               # M3's own suite
```

The same suite runs on PostgreSQL. The database name must end in `_test`,
because the suite empties every table. Built from `.env`, the password is
never typed:

```powershell
$u = (Select-String -Path backend\.env -Pattern '^DATABASE_URL=(.*)/[^/]*$').Matches[0].Groups[1].Value
$env:TEST_DATABASE_URL = "$u/truepixels_test"; python -m pytest backend/tests -q; Remove-Item Env:TEST_DATABASE_URL
```

- **Isolation:** tests never touch the real database or `storage/`. Scratch
  databases (`*_test`, `*_regression`) are created when missing; any other
  name is refused.
- **Last run (2026-10-05):** SQLite 416 passed and 7 skipped (the skips are
  PostgreSQL-only tests); PostgreSQL 423 passed.

**Front end:**

```powershell
cd frontend; npm run typecheck; npm run lint; npm run build
```

**Browser (Playwright, headless Chromium).** The suites drive the real app.
**Run them only against a scratch API and database**, because they create
accounts:

```powershell
pip install playwright==1.55.0; python -m playwright install chromium
```

The scripts are in `frontend/e2e/`:
- `run_manual_flows.py`: the user flows;
- `run_admin_flows.py`: the admin flows;
- `run_prod_smoke.py`: a production-profile smoke test.

Set `TP_BASE` to choose the target (`http://localhost:3000` or
`https://localhost`). Any CSP or mixed-content message in the browser fails
the run. Steps and arguments: [docs/manual-test-react.md](docs/manual-test-react.md).

**HTTPS acceptance checks**, with TLS verified against Caddy's CA. They
cover the redirect, headers, CORS, client-address spoofing and body limits:

```powershell
python infra/check_https.py --profile dev --api http://127.0.0.1:8000
```

**Score regression (NF.5):** every score is compared bit for bit, through the
real HTTP path:

```powershell
python ml/evaluation/regression_check.py --compare
```

## Demo

The whole system on one machine. Set up as above, then:

1. **Codes.** In `backend/.env`, set `REQUIRE_2FA=True`. Then choose one:
   - real e-mail: `EMAIL_BACKEND=smtp` with a Gmail app password;
   - no mail server: `ENVIRONMENT=development` and `EMAIL_BACKEND=console`.
     Codes then appear in the API window as
     `2FA OTP simulated in console for you@example.com: code=123456`.
2. **Start.** Run the API (keep its window visible), build the front end, and
   start `caddy-dev` (see [Run](#run) and [HTTPS](#https)). Open
   **https://localhost**.
3. **Create Account,** then enter the code. You land on **1. Forensic
   Detection**.
4. **Analyse an image** (drag and drop or choose a file; JPG/PNG, at most
   10 MB). Show:
   - the verdict, the confidence and its band;
   - the three scores: semantic, frequency and fused;
   - the two explanation panels: the SigLIP 2 attention rollout and the SPAI
     patch spectrum;
   - **PDF report**.

   Confidence is always in the predicted class and never below 50 %.
5. **Good images to try**, from the evaluation set: a DALL·E 2 image, a real
   camera photo, and a real photo the system gets **wrong** (to show its
   limits).
6. **2. User Scan History:** past results, then **Test Security Barrier**,
   which proves another user's result cannot be opened.
7. **1-Click Verification → Run Verification** (tab 3 for a normal user): live checks against every
   seam.
8. **Sign Out** (it asks first). Then **Admin Login** → **3. Admin Dashboard
   & Analytics**:
   - an overview of figures that all come from the API;
   - logs;
   - users (disable or enable, with a confirmation);
   - models: register a fusion configuration, check its quality gate, see a
     bad one refused, and roll back.
9. **Stop:** `docker compose --env-file backend/.env --profile https-dev stop caddy-dev`,
   then press Ctrl+C in the API window.

**Defaults and limits:**
- 2FA is optional and off by default. Without it, the `/auth/otp/*`
  endpoints answer 403.
- Production never prints a code, and refuses to issue one without real
  e-mail.
- Details: [docs/auth-hardening.md](docs/auth-hardening.md).

## What it measures, honestly

Benchmarked on **Synthbuster** (9 generators) against **RAISE-1k** camera
originals: 99 images per class, scene-paired, with 95 % intervals. The fusion
weight and threshold (w = 0.25, τ = 0.7558) were chosen on a **separate
validation split** that shares no scene with this one, so these are held-out
figures:

| branch | accuracy | recall | false positives on real | AUC |
|---|---|---|---|---|
| SigLIP 2 | 0.672 [0.60, 0.73] | 0.475 | 0.131 | 0.728 [0.66, 0.80] |
| SPAI | 0.884 [0.83, 0.92] | 0.909 | 0.141 | **0.967 [0.95, 0.98]** |
| **fused (what the system returns)** | 0.864 [0.81, 0.90] | 0.838 | **0.111 [0.06, 0.19]** | 0.941 [0.91, 0.97] |

**The claim this supports, and no more:** *detection of whole-image synthesis
from 2022–23 generators versus pristine Nikon RAW-derived TIFFs, 99 images per
class.* It is not "the accuracy of the system".

- **Resizing breaks this system; recompression barely touches it.** JPEG q75
  costs 0.019 AUC. Halving both classes takes SPAI's recall from 0.939 to
  0.616. Never downscale before analysis.
- **Fusion buys robustness, not peak accuracy.** On pristine images it is
  worse than SPAI alone; under degradation it is better.
- **The false-positive target is still missed, narrowly:** 0.111 against a
  requirement of ≤ 0.10.
- **Scores are uncalibrated.** A confidence of 85 % is not an 85 % chance of
  being right; it is a distance from the threshold.
- **Behaviour on post-2023 generators is unknown.** Real photos that went
  through a learned enhancer (phone pipelines, upscalers) look synthetic to
  the frequency branch.

Every control, degradation arm and per-generator figure:
**[ml/evaluation/RESULTS.md](ml/evaluation/RESULTS.md)**.

## Project structure

```text
backend/
  app/m1_access/     M1 - accounts, sign-in + OTP, throttling, upload validation, storage
  app/m2_analysis/   M2 - the two detectors, fusion, explainability, model registry
    vendor/spai/     SPAI's model code as published (Apache-2.0) + LICENSE + NOTICE
  app/m3_results/    M3 - results, history, PDF reports, administration, audit log
  app/shared/        config, database, proxy trust, the C1-C5 module contracts
  migrations/        Alembic - the schema
  scripts/           SPAI conversion, gate reference set, SQLite->PG copy, rotation check
  tests/             M1 + M2 + M3 suites
frontend/
  src/               the React app (pages/, pages/admin/, components/, api/)
  e2e/               Playwright suites
  m3_dashboard/      M3's legacy static dashboard (development only)
infra/               Caddyfiles (dev/prod) and the HTTPS acceptance checks
ml/evaluation/       benchmark, threshold selection, regression check, RESULTS.md
ml/datasets/         fetch scripts for the evaluation sets (no images committed)
storage/             runtime files: uploads, panels, model weights (gitignored)
docs/                contracts, HTTPS, auth hardening, secret rotation, manual tests
PRD*.md, SRS.pdf     requirements
```

## Documentation

| File | What it is for |
|---|---|
| **[CLAUDE.md](CLAUDE.md)** | Working notes: the models, the rules that are easy to break, what is real and what is not. Read this before changing anything. |
| [changes.md](changes.md) | Every edit made to M1's and M3's code during integration, and why |
| [ml/evaluation/RESULTS.md](ml/evaluation/RESULTS.md) | Every measurement, with its intervals and limits |
| [docs/contracts/](docs/contracts/) | The C1–C5 module seams and the documented deviations from PRD4 |
| [docs/https.md](docs/https.md) | The HTTPS setup, proxy trust, CSP, local CA, ACME |
| [docs/auth-hardening.md](docs/auth-hardening.md) | Sign-in, OTP challenges, throttling |
| [docs/rotate-secrets.md](docs/rotate-secrets.md) | Rotating the database password and the JWT key without printing them |
| [docs/manual-test-react.md](docs/manual-test-react.md) | Manual and automated browser test steps |

## Licences

The application code is this project's. Two third-party components carry
their own terms:

- **SPAI** (`backend/app/m2_analysis/vendor/spai/`): Apache-2.0, code and
  weights. Its `NOTICE` lists the local modifications, none of which change
  the arithmetic.
- **Synthbuster**, used only as evaluation data and never committed:
  **CC-BY-NC-SA-4.0, non-commercial**. RAISE-1k is research-use only.
  Neither is redistributed here.
