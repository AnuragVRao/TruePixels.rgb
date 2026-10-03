# CLAUDE.md — TruePixels.rgb working notes

Progress tracker and orientation for anyone (human or agent) picking this up.
Update the milestone table and the session log as work lands.

---

## 0. The one rule that overrides everything

> **This project never trains, fine-tunes, or retrains a model.**

Not deferred, not a later milestone — permanently out of scope. Detection uses
third-party pretrained checkpoints exactly as published.

That means: no training pipeline, no `training/` tree, no dataset collection
for training, no randomly initialised classification heads, and no plan to
"train the head later". If a capability needs training to work, it does not go
in. Adapt the architecture to what pretrained weights can do instead.

---

## 1. What this project is

TruePixels.rgb detects AI-generated images. It runs two independently
pretrained models over the same image — one reading **semantic** evidence,
one reading **frequency-domain** evidence — and fuses their verdicts, on the
argument that a generator which defeats one kind of evidence has no
particular reason to have defeated the other. This is PRD2 §1.3's design,
realised with published checkpoints instead of heads we train.

Specifications live in four PRDs at the repository root. They are the source of
truth for *requirements*; where the no-training rule contradicts them, this
file records the supersession (see §6).

| Document | Covers |
|---|---|
| [PRD1_M1_Image_Access_Management.md](PRD1_M1_Image_Access_Management.md) | M1 — auth, upload, validation, preprocessing |
| [PRD2_M2_Image_Analysis_Prediction.md](PRD2_M2_Image_Analysis_Prediction.md) | **M2 — inference, fusion, registry (what we are building)** |
| [PRD3_M3_Results_Reporting_Management.md](PRD3_M3_Results_Reporting_Management.md) | M3 — explainability, history, reports, admin |
| [PRD4_Shared_Interface_Integration.md](PRD4_Shared_Interface_Integration.md) | Contracts C1–C5, the module seams |

---

## 2. The models

Both load lazily on first request, then stay cached process-wide (NF.4). Both
run `.eval()` under `torch.inference_mode()`, on CUDA when available and CPU
otherwise. Identifiers, digests and flags live **only** in
[config.py](backend/app/shared/config.py) — no checkpoint name appears
anywhere else in the codebase.

### Semantic branch — `prithivMLmods/AIorNot-SigLIP2`

| | |
|---|---|
| Base | `google/siglip2-base-patch16-224` — declared in the checkpoint's own HF metadata as `base_model:finetune:...`, so the SigLIP 2 lineage is **verifiable**, not just claimed in prose |
| Fine-tuned for | Binary AI-generated vs. real image classification |
| Training data | `competitions/aiornot` |
| Labels | `{0: "Real", 1: "AI"}` → **AI is index 1**, resolved from `id2label` |
| Preprocessing | Its own `SiglipImageProcessor`, 224×224 |
| Size / licence | 92,885,762 params · **Apache-2.0** |
| Loader | `AutoModelForImageClassification` + `AutoImageProcessor`, [detectors.py](backend/app/m2_analysis/detectors.py) |
| Upstream metrics | Accuracy 0.9149 over 18,618 samples (Real F1 0.9025 / AI F1 0.9246). **Theirs, on their split — not ours.** |

**Vanilla SigLIP 2 is not a detector.** `google/siglip2-*` are vision-language
foundation models with no notion of synthetic imagery. We use a checkpoint
someone fine-tuned *for this task*, and we do not use zero-shot prompting,
which would be a weak heuristic dressed up as detection.

### Frequency branch — SPAI (`mever-team/spai`)

| | |
|---|---|
| Paper | Karageorgiou, Papadopoulos, Kompatsiaris, Gavves — *Any-Resolution AI-Generated Image Detection by Spectral Learning*, **CVPR 2025**. [arXiv 2411.19417](https://arxiv.org/abs/2411.19417) · [repo](https://github.com/mever-team/spai) @ `8ff7b3b` |
| Method | FFT low-/high-pass split of each 224×224 patch (circular mask, r = 16) → ViT-B/16 pretrained by **Masked Frequency Modeling** encodes original, low, high → cosine "spectral reconstruction similarity" over all 12 layers + projected features → **spectral context attention** across patches → one logit |
| Training data | Real: COCO, LSUN. Generated: Latent Diffusion |
| Output | `sigmoid(logit)` = **P(AI Generated)** — a convention, see the hazard section |
| Input | Native resolution, tiled into 224×224 patches, stride 224. **Never resized** unless `DETECTOR_FREQUENCY_RESIZE_TO` is set |
| Size / licence | 139,945,243 params · **Apache-2.0, code and weights** |
| Code | Vendored under [vendor/spai/](backend/app/m2_analysis/vendor/spai/) with upstream LICENSE and a NOTICE listing every edit (timm/torchvision/einops shims, dead branches removed, **no arithmetic changed**) |
| Weights | Authors publish `spai.pth` (935 MB pickled training checkpoint, Google Drive). Converted **once, offline** by [convert_spai_checkpoint.py](backend/scripts/convert_spai_checkpoint.py) into `storage/models/spai.safetensors` (560 MB, no code). Upstream SHA-256 `24159f27…48a55` and a digest of the weights themselves are pinned in config; the loader verifies the digest and loads **strictly** (324/324 keys) |
| Upstream metrics | Validation accuracy 0.9853 (embedded in the checkpoint); paper reports +5.5 % AUC over prior SOTA across 13 generators. **Theirs, on their splits — not ours.** |

Why SPAI and not alternatives: it is frequency-domain in the literal sense
(FFT decomposition, frequency-pretrained backbone), any-resolution by design
— which is exactly what Contract C1 §4.3's "never downsample" rule needs —
and Apache-2.0 for the weights as well as the code. **NPR** (CVPR 2024,
interpolation residual in pixel space, no licence file) is the documented
fallback if SPAI's latency cannot be brought into budget. Repositories that
publish frequency-domain *code* but no *weights* are unusable here: using
them means training.

### ⚠ The "which output means AI" hazard

Hugging Face checkpoints **disagree on which index means "AI"**:

| Checkpoint | index 0 | index 1 | AI index |
|---|---|---|---|
| `AIorNot-SigLIP2` (in use) | Real | AI | **1** |
| `Organika/sdxl-detector` (used 2026-09-07 → 09-12) | artificial | human | **0** |
| `Ateeqq/ai-vs-human` (not used) | ai | hum | **0** |

Hard-coding `probs[1]` would silently invert a checkpoint of the second kind
— plausible numbers, confidently wrong. So the index is **always resolved
from the checkpoint's own `id2label`** by
[`resolve_ai_index`](backend/app/m2_analysis/detectors.py), which refuses to
guess. Asserted against all three real label maps in
[test_detectors.py](backend/tests/test_detectors.py).

**SPAI has no labels at all** — it is one BCE logit. Its sign is therefore a
documented convention, `DETECTOR_FREQUENCY_AI_IS_POSITIVE = True`, justified
two ways: the authors' own evaluation CSVs label every generated image `1`
and every real image `0` (checked in `data/*.csv` of the repo), and the
smoke-image canary in §6 (generated images must score higher than
photographs). If a future checkpoint inverts it, flip the flag; do not touch
the code.

---

## 3. Current focus: M2, integrated with M1 and M3

**M1 and M3 are written by teammates** and were integrated on 2026-09-30
([changes.md](changes.md) lists every edit made to their code, and why).
[backend/app/m1_access/](backend/app/m1_access/) and
[backend/app/m3_results/](backend/app/m3_results/) are theirs: change them
only when integration requires it, and record each change in `changes.md`.

The seams are [backend/app/shared/contracts/](backend/app/shared/contracts/):
[c1.py](backend/app/shared/contracts/c1.py) in (from M1's
`prepare_model_input`), [c2.py](backend/app/shared/contracts/c2.py) out,
[c3.py](backend/app/shared/contracts/c3.py) for sessions.
[shared/schemas.py](backend/app/shared/schemas.py) re-exports them under the
import path M1 and M3 use; there is exactly one definition of each contract.

The request flow is: `POST /api/v1/images` (M1: validate, store, D2 row) →
`POST /api/v1/predictions {image_id, xai}` (M2: owner check, C1 via M1, both
branches, D3 rows + D4 row committed) → `GET /api/v1/results/{id}`,
`/history`, `/reports/{id}` (M3, reading D4). M3's dashboard at `/` drives
this whole flow.

### Rules that are easy to break

- Never hard-code an output index. Resolve it from `id2label`; where there
  is no `id2label` (SPAI), the convention is a config flag plus a canary.
- Never load weights leniently. `strict=False` leaves layers randomly
  initialised and nothing downstream notices.
- `confidence_score` is **not** `fusion_score`. See §7.
- Never populate a field with a stand-in value to satisfy a schema. Null is
  the honest answer when there is no number.
- Both branches read `source_reference` (the native original), each applying
  its own preprocessing. SPAI must never see a resized copy unless
  `DETECTOR_FREQUENCY_RESIZE_TO` says so. Nothing reads C1's `tensor_ref`.
- Checkpoint names, digests and flags belong in `config.py` and nowhere else.
- Do not edit `vendor/spai/` except to fix a vendoring error, and record
  every edit in its NOTICE.
- M2 is the only writer of D4 and commits before returning (PRD4 §4.2.4).
  D3 rows are recorded from config with `metrics` **null** — no benchmark of
  this system exists, and upstream figures are not ours.
- `app/stubs/` fabricates data and is **test-only**. Nothing under `app/`
  may import it. The same goes for anything that would draw an
  explainability panel without real model state: M3 answers
  `XAI_UNAVAILABLE` instead.

---

## 4. How to run

Python **3.13.6**. Two working interpreters exist on the development machine,
both fully set up (all of [backend/requirements.txt](backend/requirements.txt)
plus the CUDA build of torch):

- the project venv, `.venv\Scripts\python.exe` — activate with
  `.venv\Scripts\Activate.ps1`. Created from Python 3.13; **a venv made from
  Python 3.14 will not work**, because the pinned torch wheel only exists for
  ≤ 3.13, and that was the cause of a "No module named uvicorn" on 2026-09-12;
- the system install, `C:\Users\anura\AppData\Local\Programs\Python\Python313\python.exe`.

**GPU.** The development laptop has an RTX 4050 (6 GB, driver 555.97). Inference
runs on it when the CUDA build of torch is installed — pip's default index
serves the CPU-only build, and the `+cu126` local tag must be explicit or pip
treats the CPU build as satisfying the pin:

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cu126 "torch==2.13.0+cu126" "torchvision==0.28.0+cu126"
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"   # True 12.6
```

No code depends on which build is present; `config.DEVICE` picks CUDA when
torch reports it, and `/health` shows `"device"`.

```bash
# Tests (from the repository root)
python -m pytest backend/tests -q                    # everything: M1 + M2 + M3
python -m pytest backend/tests -q -m "not slow"      # skip the model-backed API tests
python -m pytest backend/tests/m1 -q                 # M1's own suite (36)
python -m pytest backend/tests/m3 -q                 # M3's own suite (27)
# Same suite on PostgreSQL (database name MUST end in _test; it is emptied):
TEST_DATABASE_URL=postgresql+psycopg://truepixels:<pw>@127.0.0.1:5433/truepixels_test python -m pytest backend/tests -q

# Database (once): PostgreSQL in Docker, schema from the migrations
cp backend/.env.example backend/.env                 # choose POSTGRES_PASSWORD, same value in DATABASE_URL
docker compose up -d db                              # repo root; 127.0.0.1:5433, data in a named volume
cd backend && alembic upgrade head                   # the ONLY way the schema is created or changed

# Server (from backend/, so that `app` is the top-level package)
cd backend
python seed_admin.py                                 # once: creates admin@truepixels.rgb (M1's script)
python -m uvicorn app.main:app --reload
```

Tests never touch the real database or `storage/`:
[backend/tests/conftest.py](backend/tests/conftest.py) builds one test
database with `alembic upgrade head` (scratch SQLite, or `TEST_DATABASE_URL`),
points the whole app at it - requests, D6 logging and the pipeline share one
engine - and empties every table after each test. `STORAGE_DIR` points at a
scratch directory. SPAI weights are unaffected (`config.MODELS_DIR` ignores
`STORAGE_DIR`).

**Database.** PostgreSQL is the target (since 2026-10-03, Phase 2):
`compose.yaml` runs `postgres:16` on 127.0.0.1:5433 with credentials only from
`backend/.env`. SQLite still works (`DATABASE_URL=sqlite:///./truepixels.db`).
Either way the schema comes **only** from Alembic
([backend/migrations/](backend/migrations/)): the server refuses to start on
a database that is not at head and names the command to run. The old dev
SQLite data was copied into PostgreSQL with
`backend/scripts/migrate_sqlite_to_pg.py` (read-only on the source; the
`.db` file is kept). Copy [backend/.env.example](backend/.env.example) to
`backend/.env` for database, SMTP and 2FA settings. With no SMTP password,
OTP codes go to the console. `GET /ready` answers 503 until the model
warm-up has succeeded; `/health` is liveness only.

Two UIs talk to the same API: **M3's dashboard** at
http://127.0.0.1:8000/ (sign in, scan, results, history, reports, admin) and
**M1's React app** in `frontend/` (`npm install && npm run dev` →
http://localhost:3000, proxied to :8000; registration, OTP, upload, user
management).

### One-time setup for the frequency branch

The SPAI weights are on Google Drive, which cannot be fetched reproducibly by
URL, so the loader never downloads them. Once per machine:

```bash
# 1. Download spai.pth (935 MB) from the link in config.DETECTOR_FREQUENCY_SOURCE_URL
#    into storage/models/
# 2. Convert it - verifies the upstream SHA-256, extracts the model tensors under
#    a restricted unpickler, writes storage/models/spai.safetensors (560 MB)
cd backend
python scripts/convert_spai_checkpoint.py
```

The converter prints the weights digest and confirms it matches
`DETECTOR_FREQUENCY_WEIGHTS_DIGEST`. Without the converted file, predictions
fail with `INF_MODEL_UNAVAILABLE` naming these steps, and the slow API tests
skip with the same message.

Open **http://127.0.0.1:8000/**, sign in, and press *Scan New Image*. From
`/docs` instead: `POST /api/v1/auth/login` → *Authorize* with the token →
`POST /api/v1/images` → `POST /api/v1/predictions` with the returned
`image_id`. M1 caps uploads at 10 MB and 25 MP (`MAX_UPLOAD_SIZE_MB`,
`MAX_IMAGE_PIXELS`), so the 6144² and 8192×4096 smoke images below are now
rejected at upload. `GET /health` shows both models, whether each
is loaded, the AI index the semantic branch resolved, and the sign convention
the frequency branch is running under.

Both models load at **startup** (`WARMUP_ON_STARTUP`, default on; ~9 s per
branch, plus the SigLIP 2 download, ~370 MB, the very first time), so no
request pays for it and `latency_ms` measures inference only. With the
warm-up off they load on the first prediction instead, still outside the
timed region.

### Observed latency, warm (measured 2026-09-12, 14 images, 1024^2 - 8192x4096)

| | RTX 4050 6 GB, fp32, batch 16 | 14-thread CPU |
|---|---|---|
| SPAI p50 / p95 / max | **4.1 s / 31 s / 33.6 s** | 102 s / 393 s / 979 s |
| Both branches, ordinary photo (<= ~2000^2) | **0.8 - 3 s** | 6 - 200 s |
| Peak VRAM | 3.4 GB allocated (1.0 GB between requests) | - |
| MM2.7 budget (p95) | 2.5 s | 2.5 s |

Scores agree across devices to 0.0006. MM2.7 is met on the GPU for ordinary
photographs and missed for very large originals; on CPU it cannot be met with
this branch.

**Do not "fix" that with `DETECTOR_FREQUENCY_RESIZE_TO`.** Downscaling is
measured to be this system's worst failure mode
([RESULTS.md](ml/evaluation/RESULTS.md)): halving both classes takes SPAI's
recall from 0.939 to 0.616. The default stays `None`.

**VRAM on Windows.** When VRAM runs out under WDDM, CUDA does not raise - it
spills into shared system memory and throughput collapses to ~0. A batch-size
sweep at 32+ stalled for over an hour this way. `DETECTOR_FREQUENCY_FEATURE_BATCH`
is therefore a **measured** 16 (3.4 GB peak; 24 gave 5% for +600 MB), and
`SpectralDetector.score` returns the allocator cache after every request.

---

## 5. Milestone tracker

| Step | PRD milestone | Deliverable | Status |
|---|---|---|---|
| 1 | pre-M2.0 | End-to-end path, HTTP upload → verdict | ✅ done (2026-09-07) |
| 2 | ~~M2.1~~ | ~~Train the CLIP head~~ → **superseded**: integrate a pretrained SigLIP 2 detector | ✅ done (2026-09-07) |
| 3 | ~~M2.2~~ | ~~Train the frequency classifier~~ → **superseded**: integrate a pretrained frequency-domain detector. Interim (2026-09-07): a second semantic detector, SwinV2. Final (2026-09-12): **SPAI**, SwinV2 removed | ✅ done (2026-09-12) |
| 4 | M2.3 | Select the fusion weight and τ on a validation split | ✅ **done (2026-10-01)** — reopened. It had been closed as "fitting is training", a ruling made when no labelled data existed. w and τ are configuration constants, not model weights; §0 forbids updating weights, and PRD2 FR-03 explicitly calls for both to be tuned on validation. Chosen on scenes 99–296, disjoint from the test set: **w = 0.25, τ = 0.7558**. Not done: the calibration temperature (MM2.5) |
| 5 | M2.4 | Postgres + Alembic, D3/D4 tables, registry endpoints, atomic activation | 🟡 D3/D4 tables exist (designed by M3, moved to M2) and every prediction writes D4 + commits; D3 rows are recorded **from config**. Not done: D3 as the authority (`active()` still reads config), registration canary, Alembic, Postgres |
| 6 | M2.5 | ActivationBundle capture hooks (joint delivery with M3) | ✅ **done (2026-10-03, Phase 3)** — SigLIP attention rollout (mean-pooled, faithfulness-tested) + spectrum of SPAI's own patches; panels in D5, results and PDF |
| 7 | M2.6 | Benchmark the **pretrained** branches on a public labelled set — evaluation only, no weight updates. Should include the SigLIP 2 / SPAI / fused ablation | ✅ **done (2026-09-30)** — Synthbuster vs RAISE-1k, 99/class, with the SigLIP 2 / SPAI / fused ablation, a confound control and a degradation sweep (§6). Optional next: scale to 1000/class (one flag), and a set from post-2023 generators |

Steps 2–4 previously blocked on acquiring a labelled dataset. **That
dependency is gone.** Nothing on the critical path needs data any more.

### What exists in code

```
backend/app/
  main.py                    FastAPI app: M1 + M2 + M3 routers, /static, M3 dashboard at /, /health
  shared/
    config.py                checkpoint id, SPAI file + digests + flags, τ, w, spectral params, storage
    contracts/c1.py          PreprocessedImage      (PRD4 §4.1)
    contracts/c2.py          InferenceOutput        (PRD2 §7.3, field set restored)
    contracts/c3.py          SessionContext         (PRD4 §4.3)
    contracts/errors.py      INF_* codes            (PRD2 §11)
    schemas.py               re-exports C1-C3 at the path M1/M3 import from
    db.py deps.py errors.py logging.py   merged from M1 + M3 (see changes.md)
  m1_access/                 M1 (teammate): auth, OTP, upload validation, C1 preprocess, D1/D2
  m3_results/                M3 (teammate): results, history, PDF reports, admin, D5/D6, C5 logs
  stubs/                     M3's fake M1/M2 — TEST-ONLY, imported by backend/tests/m3 alone
  m2_analysis/
    detectors.py             ★ semantic branch (SigLIP 2) + resolve_ai_index
    frequency_detector.py    ★ frequency branch (SPAI): digest check, strict load, scoring
    vendor/spai/             SPAI model code as published (Apache-2.0) + LICENSE + NOTICE
    pipeline.py              run_detection() — the C2 producer
    frequency.py             hand-written spectral FEATURES — explainability only, no score
    fusion.py                fusion + the confidence inversion
    registry.py              active config + record() of the D3 rows a prediction ran with
    models.py                D3 models / D4 predictions tables
    router_predict.py        POST /api/v1/predictions {image_id, xai} — authenticated, owner only
    schemas.py               public half of C2 only
backend/scripts/
  convert_spai_checkpoint.py one-time spai.pth → spai.safetensors (restricted unpickler)
backend/seed_admin.py        M1's script: creates the first Admin account
backend/tests/               184 tests, all green (2026-10-03, phase 1b):
  test_*.py                  M2 + cross-module: storage access, audit logging, warm-up,
                             plus the model-backed end-to-end suite (test_api_predict.py)
  m1/                        M1's suite (36), unchanged
  m3/                        M3's suite (27), test files unchanged; conftest adapted
  fixtures/spai_state_dict_manifest.json   key/shape/dtype of all 324 released tensors
frontend/                    M1's React app (Vite); m3_dashboard/ = M3's static dashboard + API tester
```

Deleted: `semantic.py` (frozen backbone + trainable head, 2026-09-07); the
SwinV2 secondary detector and `secondary_score` (2026-09-12); `dev_intake.py`
(the M1 shim, 2026-09-30, when M1 arrived). Never created: any `training/`
module.

---

## 6. What is real, and what it does not prove

| Component | Status |
|---|---|
| Semantic branch (SigLIP 2 fine-tune) | ✅ **pretrained, real** |
| Frequency branch (SPAI, spectral) | ✅ **pretrained, real** — 324/324 weights strictly loaded, digest-verified |
| AI-index resolution from `id2label` | ✅ real, tested against three checkpoints |
| SPAI sign convention | ✅ **verified** two ways — authors' CSVs (generated = 1) and the smoke canary below |
| Fusion, thresholding, inversion | ✅ real — FR-03 strategy A, `0.5·semantic + 0.5·frequency` |
| Determinism (AC-04) | ✅ **verified** — bit-identical scores across repeated runs, both branches |
| Spectral feature pipeline (`frequency.py`) | ✅ real, but **explainability only — produces no score** |
| Randomly initialised weights | ✅ **none anywhere** — a partial load is refused, not tolerated |
| **Latency budget MM2.7** | ⚠ met on the GPU for ordinary photographs (≤ ~2000² px: 1–3 s); missed for very large originals (6144²: 34 s). Not met on CPU. See §4 |
| τ and fusion weight | ✅ **selected on a validation split** (2026-10-01), disjoint from the test set, by PRD2 FR-03's own rule. w = 0.25, τ = 0.7558. No model weight was touched |
| Calibration (temperature) | ❌ no-op at T=1.0, and **MM2.5 is now measured as missed** — ECE 0.113 on validation, and the best temperature available (T = 0.97) only reaches 0.110 against a ≤ 0.05 target. Temperature scaling alone will not close it |
| D3/D4 persistence | ✅ every prediction writes D4 and commits before responding; M3 reads it back (asserted end-to-end). SQLite by default |
| Registry (FR-06/07) | ⚠ D3 rows mirror config, `metrics` null; M3's activate endpoint flips a flag but does not change what runs |
| Authentication / ownership | ✅ M1's JWT sessions on every M2/M3 endpoint; predictions owner-only, `IMG_NOT_FOUND` for not-yours (no id oracle) |
| Explainability (F.10/F.11/F.14/NF.13) | ✅ **real** — attention recomputed from passively captured inputs (matches eager attention < 1e-4; scores bit-identical, `regression_check --xai` 24/24). Deletion test on 40 validation images: masking the top-attended 20% changes the score 0.265 vs 0.195 random (+0.071, CI [0.041, 0.103], p = 5.8e-8) — better than chance, modest. Frequency panel = mean spectrum of SPAI's 224 px patches + its r = 16 split; descriptive, not evidence. Cost: +1.1–3.6 s, +7 MB VRAM. See RESULTS.md |
| **Detection of whole-image synthesis** | ✅ **measured** — Synthbuster vs RAISE-1k, 99 per class, at an operating point chosen on a disjoint validation split: fused accuracy 0.864 [0.81, 0.90], recall 0.838, AUC 0.941 [0.91, 0.97]; SPAI alone AUC 0.967. Confound-controlled. Read the narrow claim, not "accuracy" |
| **False-positive rate MM2.6 (≤ 0.10)** | ❌ **still missed, narrowly** — 0.111 [0.06, 0.19] after selecting w and τ on a validation split specifically to meet it (validation predicted 0.096). Improved from 0.162, at a cost of 10 points of recall. 11 of 99 genuine photographs called AI Generated |
| Robustness to resizing | ❌ **measured and poor** — halving both classes takes SPAI recall 0.939 → 0.616. JPEG q75 costs almost nothing. See below |
| Images smaller than 224 px | ✅ **fixed 2026-09-30** — below one 224 px patch SPAI has no evidence at all, so the branch reports itself unavailable and fusion uses the documented passthrough: a semantic-only verdict with `frequency_score` **null**. M1 admits images from 64 px (PRD C.9), so this is a normal upload, not an edge case ([changes.md](changes.md) §3.0) |

### The evidence behind that table

Full results, every arm, every per-generator figure and every superseded
measurement live in **[ml/evaluation/RESULTS.md](ml/evaluation/RESULTS.md)**.
The headline: Synthbuster vs RAISE-1k, 99 images per class, at **w = 0.25 and
tau = 0.7558 chosen on a disjoint validation split** (198/class, scenes
99-296), 95% intervals:

| branch | accuracy | recall | FPR on real | AUC |
|---|---|---|---|---|
| SigLIP 2 | 0.672 [0.60, 0.73] | 0.475 | 0.131 | 0.728 [0.66, 0.80] |
| SPAI | 0.884 [0.83, 0.92] | 0.909 | 0.141 | **0.967 [0.95, 0.98]** |
| **fused (what the system returns)** | 0.864 [0.81, 0.90] | 0.838 | **0.111 [0.06, 0.19]** | 0.941 [0.91, 0.97] |

**The claim this supports, and no more:** *detection of whole-image synthesis
from 2022-23 generators versus pristine Nikon RAW-derived TIFFs, 99 images per
class.* Never "the accuracy of the system".

Four things it established:

1. **Not a resolution artefact.** Equalising resolution and patch count
   (reals cropped to 1024^2) costs 0.031 AUC - inside the 0.05 band registered
   before scoring.
2. **Resizing breaks this system; recompression does not.** JPEG q75 on both
   classes costs 0.019 AUC. Halving both takes SPAI's recall 0.939 -> 0.616.
3. **Fusion buys robustness, not peak accuracy** - worse than SPAI alone on
   pristine images, better under halving. That is the argument for leaving
   w = 0.5 alone.
4. **MM2.6 and MM2.5 are both still missed.** The operating point was chosen
   on a validation split specifically to meet MM2.6 and still lands at FPR
   0.111 against <= 0.10 - validation said 0.096, held-out said 0.111, which
   is the sampling noise of 198 images per class. MM2.5 is further away:
   ECE 0.113, and the best temperature available (0.97) reaches only 0.110
   against <= 0.05, so temperature scaling cannot close it.
5. **Choosing the weight mattered more than choosing the threshold.** At the
   FPR MM2.6 demands, the old equal-weight average left recall at 0.596;
   w = 0.25 leaves it at 0.798 on validation, 0.838 held out. The fused AUC
   rose 0.928 -> 0.941, which is threshold-independent and so a real gain.

### Limitations to state whenever results are shown

1. One benchmark has been run, on 99 images per class, and it measures
   exactly one thing: whole-image synthesis from 2022–23 generators versus
   pristine RAW-derived TIFFs. Quote that claim, with its intervals, and never
   the word "accuracy" unqualified.
2. Both checkpoints were trained on generators available at *their* training
   time, and the benchmark set is from the same era. Behaviour on newer
   generators is still unknown, and the one modern-generator image we have
   tried was missed outright — the exact gap PRD2's MM2.2 exists to measure.
3. Output is uncalibrated. A 0.93 is not a 93% chance of being right.
4. τ and w **are** now an operating point, chosen on a validation split to
   hold the false-positive rate at MM2.6's ≤ 0.10. They were selected on 198
   images per class and carry that sampling noise; two constants fitted on one
   split is the main reason to treat the test figures as the honest ones.
5. **Resizing degrades this system badly; recompression barely touches it.**
   Measured 2026-09-30: halving both classes takes SPAI's recall from 0.939 to
   0.616, while JPEG q75 costs 0.019 AUC. Any pipeline that downscales before
   analysis throws away most of the frequency branch's value.
6. The independence argument is PRD2's original one again — semantic
   evidence vs. physical spectral evidence — but SPAI was trained on Latent
   Diffusion images and SigLIP 2 on the `aiornot` mix, so the two still
   share exposure to broadly similar generators. Independence of *kind*, not
   of training data.
7. **Learned enhancement looks synthetic.** Real photographs processed by a
   trained super-resolution / enhancement network score as AI on the
   frequency branch (CelebA-HQ "reals": 95 % called AI). Phone camera
   pipelines and upscalers are the everyday version of this.
8. SPAI's generalisation claims (13 generators, robustness to online
   perturbations) are the authors'. The one confident false positive in our
   smoke set (the sunflower photograph, 1.000) shows the branch can be wrong
   with full conviction, exactly as the previous second branch could.
9. **Synthbuster is one of SPAI's own published test sets.** Its 0.967 there
   confirms our integration reproduces the authors' result; it is not
   independent evidence that SPAI generalises. For SigLIP 2 the set is
   genuinely unseen — and SigLIP 2 scores 0.728.
10. **Images under 224 px get a semantic-only verdict.** The frequency branch
    reports itself unavailable and `frequency_score` is null — so the
    two-kinds-of-evidence argument in §1 does not apply to them at all. Say so
    wherever such a result is shown.

---

## 7. The confidence inversion

```python
predicted_class  = "AI Generated" if fusion_score >= tau else "Real"
confidence_score = fusion_score if predicted_class == "AI Generated" else 1.0 - fusion_score
```

`semantic_score`, `frequency_score` and `fusion_score` are all
**P(AI Generated)**. `confidence_score` is the odd one out — it is confidence
in whichever class was *actually predicted*.

A `fusion_score` of 0.08 means **"Real" with 0.92 confidence**.

PRD2 FR-04 calls this the most likely integration bug in the project because
it fails quietly: a confidently-real image rendered at 8% looks like a weak
model rather than a wiring error. Asserted in
[test_fusion.py](backend/tests/test_fusion.py) and again over HTTP in
[test_api_predict.py](backend/tests/test_api_predict.py). M3 must assert it
independently from its own side.

**Never render `fusion_score` as a confidence figure.**

---

## 8. Contract C2 changes, and other deviations

### C2 (PRD2 §7.3) — field set restored

| Field | History |
|---|---|
| `semantic_score` | kept throughout; P(AI) from the semantic branch (SigLIP 2 fine-tune) |
| `frequency_score` | 2026-09-07: `float \| None`, always null (no classifier). **2026-09-12: populated by SPAI** — P(AI) from frequency-domain evidence, as PRD2 meant. Still typed `float \| None` solely because the branch can be disabled, in which case fusion is a documented passthrough |
| `secondary_score` | added 2026-09-07 for the SwinV2 detector; **removed 2026-09-12**. Nothing should read it |
| `fusion_score` | unchanged; now literally FR-03 strategy A, `0.5·semantic + 0.5·frequency` |
| `confidence_score` | unchanged — confidence in the predicted class |

The public field set is now exactly PRD2 §7.3's again.

### Superseded PRD requirements

- **FR-01** (frozen CLIP backbone + a trainable head) and **FR-02** step 8
  (train a classifier over spectral features) both require training. FR-01 is
  realised by a pretrained SigLIP 2 fine-tune; FR-02 by a pretrained spectral
  detector (SPAI) that asks FR-02's physical question with its own, published
  architecture. FR-02's hand-written feature pipeline (steps 1–7) survives for
  explainability only.
- **OI-1** (fusion strategy A vs. B) is closed in favour of A. Strategy B is a
  logistic meta-classifier whose coefficients must be fitted — that is training.
- **M2-A / M2-B / M2-C** (backbone choice, dataset sourcing, per-channel
  ablation) are moot: all three presupposed training.

### Other deviations, recorded rather than hidden

1. **Python 3.13.6**, not the 3.11 in PRD2 §4.
2. ~~`POST /api/v1/predictions` takes a multipart file~~ — **reverted
   2026-09-30**: it is PRD2 §10.1's `{image_id, xai}` JSON body again, behind
   M1's auth. `run_detection(prepared)` still works as PRD4 writes it; it
   also accepts the request's `db` session.
3. ~~No auth on any endpoint~~ — **resolved 2026-09-30** by M1's C3.
4. ~~C1's CLIP tensor is built and saved but never read~~ — **resolved
   2026-10-03**: M1 no longer builds or saves it (changes.md 6.3). C1's
   `tensor_ref`/`shape`/`dtype`/`normalization` remain as optional fields,
   always `None`; **C1 v2 should drop them**.
5. **`ml/training/` is retired** — it contradicts §0. `ml/evaluation/` stays:
   benchmarking a pretrained detector is evaluation, not training, and remains
   both legitimate and wanted (Step 7).
6. **Third-party model code is vendored** (`vendor/spai/`, Apache-2.0) because
   SPAI is not packaged and is not a Hugging Face `AutoModel`. Every local edit
   is a `# TruePixels:` comment and is listed in the NOTICE; none changes the
   arithmetic. Its weights pass through a one-time offline conversion because
   the published file is a pickled training checkpoint that the safe
   unpickler refuses (it embeds a `yacs` config object).

---

## 9. Session log

### 2026-10-03 (latest) — Phase 2 (PostgreSQL + Alembic) and Phase 3 (explainability)
- Phase 2: PostgreSQL via compose (127.0.0.1 only), Alembic baseline, one
  engine for app + logger + pipeline, startup refuses an un-migrated DB,
  dev SQLite data migrated (pre-checked, read-only on the source). Scores
  bit-identical end to end through PostgreSQL.
- Phase 3: explainability built for real — see the §6 row and RESULTS.md.
  Two things found on the way: `attn_implementation="eager"` passed to
  `from_pretrained` does **not** reach this checkpoint's vision sub-config
  (it stays SDPA); and PNG `optimize=True` was ~80% of the overlay's cost.
  Explainability never fails a prediction: D5 is written after D4 commits;
  forced failures tested on SQLite and PostgreSQL.
- **Next:** Phase 4 (real model management, F.19).

### 2026-10-02 / 10-03 — completion phases 0, 1a, 1b
- The project is being finished in reviewed phases (plan approved by the user;
  one `phase-N:` commit per unit, never pushed). Phase 0 baseline commit
  `d371021`; the hard-coded admin seed password was removed **before** it
  could enter history (`git log --all -S` finds only the unrelated M1 test
  fixture string).
- **Security: `/static` served the whole storage tree unauthenticated** —
  every upload and the SPAI weights. Removed; files now go out only through
  owner-only endpoints with resolved-path containment checks and D6 audit
  rows (changes.md 6.1, 6.2). Path-traversal and junction/symlink tests.
- `emit_log` swallows write errors by design; tests had silently written no
  D6 rows. Swallowed failures are now recorded and `strict_audit_log` fails a
  test on them.
- NF.5 tripwire: `ml/evaluation/regression_check.py` (24 images, float.hex,
  real HTTP path). Bit-identical across every phase-1 change.
- Dead CLIP tensor removed (changes.md 6.3); startup warm-up; `latency_ms`
  now excludes model load and the discarded xai FFT. First request after
  boot: 889 ms (was 20,861 ms cold).
- Baseline was **not** green on arrival: one stale test assumed w = 0.5.
  Fixed. Held-out metrics re-derived from the per-image CSV: they were
  computed at w = 0.25, τ = 0.7558 — the configuration that runs.
- **Next:** Phase 2, PostgreSQL + Alembic (the `cold_start` D4 column lands in
  its baseline migration).

### 2026-10-01 — operating point selected on a validation split
- Reopened Step 4. It had been closed as "fitting is training"; that ruling was
  made when no labelled data existed and was broader than §0 requires — §0
  forbids updating model **weights**, and w and τ are config constants that
  PRD2 FR-03 explicitly says to tune on validation.
- Built a disjoint validation split (198/class, scenes 99–296; the test set is
  0–98) and found the **weight, not the threshold, was the binding
  constraint**: at the FPR MM2.6 demands, w = 0.5 left recall at 0.596 because
  averaging drags SPAI's confident detections toward the middle — 52 of the 157
  it was sure about fell below a qualifying τ. **w = 0.25, τ = 0.7558.**
- Held out: FPR 0.162 → **0.111**, recall 0.939 → 0.838, fused AUC 0.928 →
  **0.941**. **MM2.6 still missed** (0.111 vs ≤ 0.10; validation predicted
  0.096). MM2.5 is unreachable by temperature scaling — best T = 0.97 gives
  ECE 0.110 against ≤ 0.05.
- A subagent review found two real defects, both fixed: **the dashboard
  crashed on a null `frequency_score`** (my 2026-09-30 fix reached the PDF and
  the API schema but not `frontend/m3_dashboard/`, and the error was swallowed
  as "NETWORK_ERROR"), and **`evaluate.py` aborted on any sub-224 px image**
  instead of mirroring the production passthrough — so no benchmark had
  covered the semantic-only path. Also: atomic writes + CRC re-verification on
  resume in the fetcher, and stale wording in `c2.py`, `schemas.py`, `config.py`.
- **The dashboard shipped a hard-coded verdict** — "Real, 96.2%, High
  Confidence" with invented branch scores rendered before any scan, on an
  empty database. Found by the user on first use; now an empty state
  ([changes.md](changes.md) §3.0b).
- Commit hygiene: a fixed `JWT_SECRET_KEY` fallback, wildcard CORS with
  credentials, and a personal Gmail address removed from source; 5.7 GB of
  fetched data and the 32 MB module zips excluded from git.
- **Next:** MM2.6 needs a larger validation split or a better semantic branch,
  not more tuning against the test set. Then a post-2023 generator set (MM2.2),
  and the three provenance findings in §6.

### 2026-09-30 — the in-task benchmark; Step 7 closed
- Built the evaluation set the system actually needed: **Synthbuster** (9
  generators) vs **RAISE-1k** camera originals, scene-paired, 99 per class.
  `fetch_synthbuster.py` range-reads Zenodo's remote zip so 1.3 GB moves
  instead of 12.4 GB; the user's `dataset/1.py` was verified correct and is
  kept as the reference selection rule. The host in `RAISE_1k.csv` is dead;
  `loki.disi.unitn.it` works.
- **SPAI AUC 0.967 [0.95, 0.98]**, fused 0.928, SigLIP 2 0.728. Confound
  control (reals cropped to 1024²) costs 0.031 AUC — inside the band
  pre-registered before scoring, so the number is not a resolution artefact.
- **MM2.6 missed**: FPR 0.162 [0.10, 0.25] on pristine photographs.
- **Resizing, not recompression, is the failure mode**: halving both classes
  takes recall 0.939 → 0.616; JPEG q75 costs 0.019 AUC.
- **Fusion buys robustness, not peak accuracy** — worse than SPAI alone on
  pristine images, better under degradation. w left at 0.5; nothing tuned.
- Two registered predictions were **wrong** and are recorded as wrong: the
  resize arm's direction (the arm was mis-designed — it transforms one class
  only) and "SigLIP 2 weakest on the newest generators" (its worst is SD 2).
- Added Wilson/bootstrap intervals, per-generator breakdown and a `claim`
  field to `evaluate.py`; asserted per-generator image sizes in the fetcher,
  which revealed the generated class spans 256² to 2688×1536 with RGBA.
- **Found and fixed a defect**: images under 224 px crashed the frequency
  branch → HTTP 500, reachable from any upload between M1's 64 px floor and
  224 px. Now `SpectralBranchUnavailable` → `frequency_score` null →
  passthrough, the path Contract C2 always allowed. D4's column and M3's
  schema and PDF made null-tolerant ([changes.md](changes.md) §3.0).
- Verified the scoring path was unaffected by the M1/M3 merge landing
  mid-run: crop1024 re-scored 198/198 bit-identical.
- **Next:** choose τ on a *fresh* validation split (a second disjoint slice
  of the same sets) to close MM2.6 and MM2.5 the way PRD2 FR-03 specifies —
  that is an operating-point choice, not training, and it reopens Step 4's
  "superseded" ruling now that labelled data exists. Then a post-2023
  generator set (MM2.2). Scaling this set to 1000/class would narrow the
  intervals and change no conclusion.

### Earlier entries, one line each

- **2026-09-30** - M1 and M3 integrated by teammates; see
  [changes.md](changes.md) for every edit to their code and why.
- **2026-09-12** - first labelled evaluation (AttGAN: at chance, and why that
  set could not answer the question); repo venv rebuilt from Python 3.13 with
  the cu126 torch.
- **2026-09-12** - both branches moved to the RTX 4050; patch batch sized by
  measurement; WDDM spill hazard found and documented.
- **2026-09-12** - **SPAI became the frequency branch**; SwinV2 and
  `secondary_score` removed; C2 restored to PRD2 §7.3; weights vendored,
  digest-pinned and strictly loaded.
- **2026-09-07** - pretrained detectors replaced the untrained heads; the
  label-order hazard found and guarded; no randomly initialised weights left.
- **2026-09-07** - first end-to-end path built from an empty repo.

Full entries: [docs/session-log.md](docs/session-log.md). Measurement
detail: [ml/evaluation/RESULTS.md](ml/evaluation/RESULTS.md).
