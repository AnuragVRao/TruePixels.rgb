# TruePixels.rgb

Detects AI-generated images by running **two independently pretrained models**
over the same picture and fusing their verdicts:

- a **semantic** branch — [`prithivMLmods/AIorNot-SigLIP2`](https://huggingface.co/prithivMLmods/AIorNot-SigLIP2),
  a SigLIP 2 fine-tune, which asks *what is this a picture of, and does it look
  like the AI images it was trained on*;
- a **frequency-domain** branch — [SPAI](https://github.com/mever-team/spai)
  (CVPR 2025), which ignores content and asks *does this pixel grid carry the
  spectral signature of a synthesis pipeline*.

The argument for running both is that a generator which defeats one kind of
evidence has no particular reason to have defeated the other. Measurements
below show where that holds and where it does not.

> ### This project never trains, fine-tunes or retrains a model
>
> Not deferred — permanently out of scope. Every score comes from a
> third-party checkpoint used exactly as published, and there is no randomly
> initialised weight anywhere in the inference path. Where the PRDs call for a
> trained component, the architecture was changed to use pretrained weights
> instead, and the supersession is recorded in `CLAUDE.md` §8.

## Quick start

Requires **Python 3.13** (the pinned torch wheel does not exist for 3.14).

```bash
python -m venv .venv && .venv\Scripts\Activate.ps1      # Windows
pip install -r backend/requirements.txt

# GPU (optional but ~25x faster): pip's default index serves the CPU-only
# build, so the +cu126 tag must be explicit or pip thinks the pin is satisfied.
pip install --index-url https://download.pytorch.org/whl/cu126 \
    "torch==2.13.0+cu126" "torchvision==0.28.0+cu126"
```

**One-time: the SPAI weights.** They are published on Google Drive, which
cannot be fetched reproducibly by URL, so nothing downloads them for you.
Download `spai.pth` (935 MB) from the link in
`config.DETECTOR_FREQUENCY_SOURCE_URL` into `storage/models/`, then:

```bash
cd backend && python scripts/convert_spai_checkpoint.py
```

That verifies the upstream SHA-256, extracts the model tensors under a
restricted unpickler, and writes a tensors-only `spai.safetensors` (560 MB).
The server loads only that file, checks it against a pinned digest of the
weights, and loads it **strictly** — a partial load is refused, never
tolerated.

```bash
cd backend
cp .env.example .env            # set JWT_SECRET_KEY before deploying
python seed_admin.py            # creates the first admin account
python -m uvicorn app.main:app --reload
```

The primary interface is the React app in `frontend/` (`npm install && npm run dev`,
then <http://localhost:3000>): analysis, results, history, PDF reports, and
the admin screens (overview, logs, users, models).
<http://127.0.0.1:8000/> still serves M3's original static dashboard. It is
**legacy**, kept for reference and quick checks only: it has no user or
model management, and new features land only in the React app. `/docs`
lists the API.
`GET /health` reports the device, both checkpoints and whether each is loaded.

```bash
python -m pytest backend/tests -q                 # 158 tests: M1 + M2 + M3
python -m pytest backend/tests -q -m "not slow"   # skip the model-backed ones
```

## Demo over HTTPS, without an e-mail server

This walkthrough shows the whole system, the optional OTP sign-in included,
on one machine. Codes are printed in the API's console instead of being
e-mailed. That console delivery works **only** with
`ENVIRONMENT=development`.

1. **One-time setup:**
   - the database is up and migrated (Quick start above);
   - the SPAI weights are converted;
   - Docker Desktop is running.
2. **In `backend/.env`:**

   ```ini
   ENVIRONMENT=development      # dev-only surface: console OTP codes, /docs
   REQUIRE_2FA=True             # turn the optional OTP 2FA ON for the demo
   EMAIL_BACKEND=console
   PROXY_SHARED_SECRET=<python -c "import secrets; print(secrets.token_hex(32))">
   ```

3. **Build the front end:**

   ```powershell
   cd frontend; npm install; npm run build; cd ..
   ```

4. **Start the API** on the host. Leave this console open: the codes appear
   here.

   ```powershell
   cd backend
   python seed_admin.py          # once, if there is no admin yet
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
   ```

5. **Start the HTTPS proxy**, in a second console at the repository root:

   ```powershell
   docker compose --env-file backend/.env --profile https-dev up -d caddy-dev
   ```

6. **Open <https://localhost>.** The browser warns about the certificate
   until you trust Caddy's local CA, on this machine only (see
   [docs/https.md](docs/https.md)).
7. **Register.** The page asks for a code. Look in the API console for
   `2FA OTP simulated in console for you@example.com: code=123456` and enter
   it.
   - Sign out and back in: the password first, then a fresh code.
   - Admins use **Admin Login** (the Administrator Portal, `/admin/login`), then enter the code printed in
     the console.
8. **Analyse an image**, then open History, the PDF report and (as an admin)
   the Admin screens.
9. **Stop:**

   ```powershell
   docker compose --env-file backend/.env --profile https-dev stop caddy-dev
   ```

   Then stop uvicorn with Ctrl+C.

**Defaults and limits.**
- **2FA is optional and off by default.** With `REQUIRE_2FA` unset or False:
  - registration and sign-in need no code;
  - `/auth/otp/*` answers 403.
- **Production never issues codes without real e-mail.**
  - `ENVIRONMENT` unset counts as production.
  - With `REQUIRE_2FA=True` and no SMTP settings, sign-in and registration
    answer `503 OTP_DELIVERY_UNAVAILABLE`.
  - Codes are never printed.
- How sign-in and OTP work: [docs/auth-hardening.md](docs/auth-hardening.md).

## What it measures, honestly

Benchmarked on **Synthbuster** (9 generators) versus **RAISE-1k** camera
originals, 99 images per class, scene-paired, with 95 % intervals. The fusion
weight and threshold (w = 0.25, τ = 0.7558) were chosen on a **separate
validation split** of 198 images per class that shares no scene with this one,
so these are held-out figures:

| branch | accuracy | recall | false positives on real | AUC |
|---|---|---|---|---|
| SigLIP 2 | 0.672 [0.60, 0.73] | 0.475 | 0.131 | 0.728 [0.66, 0.80] |
| SPAI | 0.884 [0.83, 0.92] | 0.909 | 0.141 | **0.967 [0.95, 0.98]** |
| **fused (what the system returns)** | 0.864 [0.81, 0.90] | 0.838 | **0.111 [0.06, 0.19]** | 0.941 [0.91, 0.97] |

**The claim this supports, and no more:** *detection of whole-image synthesis
from 2022–23 generators versus pristine Nikon RAW-derived TIFFs, 99 images per
class.* It is not "the accuracy of the system".

What else the benchmark established, including the inconvenient parts:

- **Resizing breaks this system; recompression barely touches it.** JPEG q75
  on both classes costs 0.019 AUC; halving both takes SPAI's recall from
  0.939 to 0.616. Do not downscale before analysis.
- **Fusion buys robustness, not peak accuracy.** On pristine images fusion is
  *worse* than SPAI alone; under degradation it is better.
- **The false-positive target is still missed, narrowly** — 0.111 against a
  ≤ 0.10 requirement, after choosing the operating point specifically to meet
  it. The validation split predicted 0.096; the held-out set came in worse,
  which is what two constants chosen on 198 images per class buys you.
- **Behaviour on post-2023 generators is unknown**, and the one modern image
  tried was missed outright with full confidence.
- **Real photographs that have been through a learned enhancer** — phone
  camera pipelines, upscalers — look synthetic to the frequency branch.

Full results, every control and degradation arm, and the per-generator
breakdown: **[ml/evaluation/RESULTS.md](ml/evaluation/RESULTS.md)**.

## Project structure

```text
backend/app/
  m1_access/     M1 — accounts, sessions, upload, validation, preprocessing
  m2_analysis/   M2 — the two detectors, fusion, prediction records, registry
    vendor/spai/ SPAI's model code as published (Apache-2.0) + LICENSE + NOTICE
  m3_results/    M3 — results, history, PDF reports, administration, logging
  shared/        config, database, and the C1–C5 contracts between modules
backend/tests/   M2's suite plus M1's and M3's, unchanged
frontend/        the React app (primary UI); m3_dashboard/ is M3's legacy static dashboard
ml/evaluation/   evaluate.py, select_threshold.py, and RESULTS.md
ml/datasets/     fetch scripts for the evaluation sets (no images committed)
storage/         local artefacts: uploads, model weights (all gitignored)
docs/            contracts, decisions, session-log archive
PRD*.md          the four product requirement documents
```

## Documentation

| File | What it is for |
|---|---|
| **[CLAUDE.md](CLAUDE.md)** | Working notes: the models, the rules that are easy to break, how to run, milestones, what is real and what is not. Read this before changing anything. |
| [changes.md](changes.md) | Every edit made to M1's and M3's code during integration, and why |
| [ml/evaluation/RESULTS.md](ml/evaluation/RESULTS.md) | Every measurement, with its intervals and its limits |
| [docs/contracts/](docs/contracts/) | The C1–C5 module seams, and the documented deviations from PRD4 |

## Licences

The application code is this project's. Two third-party components carry their
own terms, and both matter:

- **SPAI** (`backend/app/m2_analysis/vendor/spai/`) — Apache-2.0, code and
  weights. See its `NOTICE` for the list of local modifications, none of which
  change the arithmetic.
- **Synthbuster**, used only as evaluation data and never committed —
  **CC-BY-NC-SA-4.0, non-commercial**. RAISE-1k is research-use. Neither is
  redistributed here; `ml/datasets/fetch_*.py` fetch them on request.
