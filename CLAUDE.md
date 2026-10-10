# CLAUDE.md — TruePixels.rgb working notes

Orientation for anyone (human or agent) working on this repository. It holds
the rules and the current state; history lives in
[docs/session-log.md](docs/session-log.md), every measurement in
[ml/evaluation/RESULTS.md](ml/evaluation/RESULTS.md). Update §5 and add a
session-log entry as work lands.

---

## 0. The one rule that overrides everything

> **This project never trains, fine-tunes, or retrains a model.**

Not deferred, not a later milestone — permanently out of scope. Detection uses
third-party pretrained checkpoints exactly as published: no training pipeline,
no `training/` tree, no dataset collection for training, no randomly
initialised heads. If a capability needs training, it does not go in.

Choosing **configuration constants** (the fusion weight `w` and threshold `τ`)
on a selection/validation split is allowed — it updates no weight — and the
result is always reported on held-out data that played no part in the choice.

---

## 1. What this project is

TruePixels.rgb detects AI-generated images. Two independently pretrained
models read the same upload — one reads **content**, one reads
**frequency-domain** evidence — and their scores are fused, on the argument
that a generator which defeats one kind of evidence has no particular reason
to have defeated the other.

Modules: **M1** accounts / upload / validation ([app/m1_access/](backend/app/m1_access/),
written by a teammate — change only when integration needs it and record it in
[docs/auth-hardening.md](docs/auth-hardening.md)); **M2** detection, fusion,
model registry ([app/m2_analysis/](backend/app/m2_analysis/)); **M3** results,
history, PDF reports, admin ([app/m3_results/](backend/app/m3_results/), owned
and edited directly here since 2026-10-08). The seams are the contracts in
[app/shared/contracts/](backend/app/shared/contracts/) (C1 in, C2 out, C3
sessions), each defined once. The four PRDs and `changes.md` were removed from
the working tree in `4bf5c15`; they remain in git history.

Request flow: `POST /api/v1/images` (M1: validate, store) →
`POST /api/v1/predictions {image_id, xai}` (M2: both branches, D4 row committed
before returning) → `GET /api/v1/results/{id}`, `/history`, `/reports/{id}`
(M3). The UI is the React app in `frontend/`.

---

## 2. The models

All identifiers, revisions, digests and flags live **only** in
[config.py](backend/app/shared/config.py). Every model runs `.eval()` under
`torch.inference_mode()`, on CUDA when available, loaded once per process and
warmed at startup.

### Content branch — a pinned set; the active D3 row picks one

`config.SEMANTIC_BACKBONES` holds every allowed content detector. A D3
semantic row is valid only if it names one of them **at exactly its revision**;
`detectors.semantic(checkpoint)` returns the detector the active row names.

| | **Community Forensics** (in use since 2026-10-09) | SigLIP 2 (pinned rollback target) |
|---|---|---|
| Checkpoint | `OwensLab/commfor-model-384` @ `6076002b`, MIT | `prithivMLmods/AIorNot-SigLIP2` @ `f4e6a281`, Apache-2.0 |
| Model | timm ViT-S/16, 384 px, one logit (CVPR 2025; ~4,800 training generators). Class vendored in [vendor/commfor/](backend/app/m2_analysis/vendor/commfor/) | SigLIP 2 fine-tune, 2 logits, HF `AutoModelForImageClassification` |
| Input | authors' test transform: shortest side 440 → **centre crop 384** | its own processor, full image → 224 |
| "AI" output | `sigmoid(logit)`, convention `SEMANTIC_COMMFOR_AI_IS_POSITIVE`, checked against the authors' published scores | index resolved from `id2label` (`{0: Real, 1: AI}`) |
| Loading | SHA-256 checked, strict (152/152) | pinned revision, local cache first |
| Uploaded heads | none | yes (perturbed-head tests only) |

**Why the switch:** on 2025 generators SigLIP 2 scored AUC 0.53 and lowered
every fusion it was part of (RESULTS.md 2026-10-09).

**Numerics trap:** on CUDA, PyTorch's default **TF32 convolutions** moved a
Community Forensics reference score from 0.7860 to 0.7655. The patch
projection is therefore computed as unfold + matmul
(`detectors._ExactPatchProjection`) — the same linear map — so CPU and GPU
agree to 1e-5. Do not replace it with the Conv2d.

### Frequency branch — SPAI (CVPR 2025, Apache-2.0)

FFT low/high split of every **native-resolution** 224×224 patch, encoded by a
frequency-pretrained ViT-B/16, aggregated by spectral context attention →
one logit; `sigmoid` = P(AI) by convention (`DETECTOR_FREQUENCY_AI_IS_POSITIVE`,
verified against the authors' CSVs and a canary). Code vendored under
[vendor/spai/](backend/app/m2_analysis/vendor/spai/); weights converted once
from the authors' `spai.pth` into `storage/models/spai.safetensors`,
digest-pinned, loaded strictly (324/324). Images under 224 px have no patch:
the branch reports itself unavailable and the verdict is content-only
(`frequency_score` null).

### The label-order hazard

Checkpoints disagree on which output means "AI" (`AIorNot-SigLIP2`: index 1;
`Organika/sdxl-detector`, `Ateeqq/ai-vs-human`: index 0). Never hard-code an
index: resolve it from `id2label` (`resolve_ai_index` refuses to guess); for
single-logit models use the documented config flag plus a check against
published reference scores.

---

## 3. Rules that are easy to break

- Never hard-code an output index or a logit's sign (§2).
- Never load weights leniently — `strict=False` leaves layers random and
  nothing downstream notices. Never load an unpinned revision or a file whose
  digest does not match.
- Both branches read `source_reference`, the native original, each with its
  own preprocessing. SPAI must never see a resized copy unless
  `DETECTOR_FREQUENCY_RESIZE_TO` says so (default `None`; downscaling is this
  system's worst failure mode). Nothing reads C1's `tensor_ref`.
- `confidence_score` is **not** `fusion_score` (§6). Never render the fused
  score as a confidence.
- Never fill a field with a stand-in value. Null is the honest answer.
- Checkpoint names, digests and flags belong in `config.py` only.
- Do not edit `vendor/spai/` or `vendor/commfor/` except to fix a vendoring
  error, and record every edit in its NOTICE.
- **D3 decides what runs, not config.** Changing the model or operating point
  means registering a row and activating it (canary → quality gate → atomic
  switch; `registry.activate`, Admin → Models). Config only seeds an empty D3.
  D3 rows keep `metrics` null — upstream figures are not ours.
- The quality gate's reference cache must match the pinned models: after
  changing any pinned detector, run `python backend/scripts/build_reference_set.py`.
- M2 is the only writer of D4 and commits before returning.
- `app/stubs/` fabricates data and is **test-only**; nothing under `app/` may
  import it. No explanation panel is drawn without real model state —
  M3 answers `XAI_UNAVAILABLE` instead.
- Never print `.env` or secret values; check only that a key is present.

---

## 4. How to run

Python **3.13** (`.venv\Scripts\python.exe`; a 3.14 venv cannot install the
pinned torch). GPU: RTX 4050 6 GB with the CUDA build of torch:

```bash
python -m pip install -r backend/requirements.txt
python -m pip install --index-url https://download.pytorch.org/whl/cu126 "torch==2.13.0+cu126" "torchvision==0.28.0+cu126"
```

```bash
start.cmd / stop.cmd                                  # everything: DB, migrations, API, HTTPS front end
python -m pytest backend/tests -q                     # all tests (-m "not slow" skips the model-backed ones)
docker compose --env-file backend/.env up -d db        # PostgreSQL on 127.0.0.1:5433 (credentials only in backend/.env)
cd backend && alembic upgrade head                    # the ONLY way the schema changes
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers   # from backend/
```

- **Once per machine:** download `spai.pth` (link in
  `config.DETECTOR_FREQUENCY_SOURCE_URL`) into `storage/models/`, then
  `python backend/scripts/convert_spai_checkpoint.py`. The content detectors
  download themselves at their pinned revisions on first use. Then build the
  gate reference: `python backend/scripts/build_reference_set.py` (needs
  `ml/datasets/sbr_val`).
- Tests build their own database (scratch SQLite, or `TEST_DATABASE_URL` whose
  name must end in `_test`) and never touch `storage/`.
- The server refuses to start on a database that is not at the latest
  migration. `main` (`… 0005 → 0006c → 0007`) and branch `decision-map-1`
  (`… 0005 → 0006`) have **different** migration chains: downgrade to `0005`
  before switching a database between them. `start.ps1` applies pending
  migrations — take a backup first.
- `GET /ready` is 503 until warm-up succeeds; `/health` shows the device, the
  baseline and every pinned content detector, and which are loaded.
- `ENVIRONMENT` defaults to production (no `/docs`).
  2FA and SMTP settings: `backend/.env.example`, [docs/auth-hardening.md](docs/auth-hardening.md).
  HTTPS: [docs/https.md](docs/https.md).
- **VRAM on Windows:** when VRAM runs out under WDDM, CUDA does not raise — it
  spills to system memory and stalls for an hour. Don't run GPU jobs (tests,
  evaluations) while the API is serving; stop it first.
  `DETECTOR_FREQUENCY_FEATURE_BATCH` is a measured 16.
- Latency (GPU, warm): 1–3 s for an ordinary photo; very large originals can
  take 30 s+ (SPAI tiles every patch).

---

## 5. Current state (2026-10-10)

**Live:** Community Forensics + SPAI, fused as
`0.55 · content + 0.45 · frequency`, verdict *AI Generated* if the fused score
is ≥ **τ = 0.4524** (D3 semantic row #7, fusion row #8). SigLIP 2 (#4) and the
previous operating point (#6) are one rollback each.

**Measured** (held out; w and τ were chosen on a separate selection pool):

| test set | accuracy | recall | FPR on real | AUC |
|---|---|---|---|---|
| AIGenImages2026 val — 19 generators from 2025, content-matched reals (559 + 559) | 0.798 [0.77, 0.82] | 0.626 | 0.030 | 0.895 |
| Synthbuster vs RAISE-1k — 2022–23 generators, camera TIFFs (99 + 99) | 0.939 [0.90, 0.96] | 0.949 | 0.071 | 0.986 |

Quote these as *separation of these generators' images from these real
photographs*, never as "the accuracy of the system".

**Limitations to state whenever results are shown**
1. Some 2025 generators still get through: FLUX.2 pro 23 % caught, FLUX.2 max
   17 %, FLUX 1.1 pro 26 %, GPT-image-1 29 %. Newer generators are untested.
2. Not independent: Synthbuster is one of SPAI's own test sets and may overlap
   Community Forensics' training generators; AIGenImages2026 is from SPAI's
   authors' group.
3. Output is uncalibrated (MM2.5 missed: ECE 0.113 on validation for the
   previous configuration; the current one is unmeasured). A confidence is a
   distance from the threshold, not a probability.
4. Resizing badly hurts the frequency branch (halving: recall 0.939 → 0.616);
   JPEG recompression barely does. Learned enhancement (phone pipelines,
   upscalers) makes real photos look synthetic.
5. Community Forensics sees only the central square of the image.
6. Images under 224 px get a content-only verdict — the two-kinds-of-evidence
   argument does not apply to them.
7. The quality gate is a coarse safety net: 100 reference images, SE ≈ 0.04 on
   accuracy. It catches gross breakage, not subtle degradation.
8. Latency budget MM2.7 (p95 ≤ 2.5 s) is met on the GPU for ordinary photos,
   missed for very large originals and on CPU.

**Known issue (2026-10-10):** the evaluation images in
`ml/datasets/synthbuster_raise/` and `ml/datasets/sbr_val/` were deleted by
mistake during a clean-up and must be re-fetched (`ml/datasets/README.md`).
Until then two slow tests in `test_model_management.py`, the regression check
and rebuilding the gate reference cannot run. The gate's existing cache, the
live system and all recorded results are unaffected.

**Built and working:** sign-in with optional e-mail 2FA, password reset and
change, login activity; upload validation; both branches; fusion and verdict;
explanation panels (content-detector attention rollout drawn inside the
crop it saw, SPAI patch spectrum); history; PDF reports; admin dashboard,
users, logs and model management (register, gate preview, activate,
rollback); PostgreSQL + Alembic; HTTPS via Caddy.

---

## 6. The confidence shown to users

```
predicted_class  = "AI Generated" if fusion_score >= tau else "Real"
confidence_score = fusion.confidence_in_prediction(fusion_score, tau, predicted_class)
```

`semantic_score`, `frequency_score` and `fusion_score` are all **P(AI)**-like
scores. `confidence_score` is the odd one out: confidence in **whichever class
was predicted**, 0.5 exactly at the threshold and rising with the distance
from it to 100 % at the far end, so a verdict never shows below 50 %. Bands:
High ≥ 85 %, Moderate 65–85 %, Low < 65 %. It is a margin, not a calibrated
probability. The exact rule is in `fusion.py`; user-facing docs describe it in
words. Stored rows were last recomputed by migration 0007 (0004 introduced
the rule; 0006c applied a scale that 0007 removed again). Rendering
`fusion_score` as a confidence is the integration bug PRD2 FR-04 warned about:
a confidently-real image would read as "8 %". Asserted in `test_fusion.py`
and over HTTP in `test_api_predict.py`.

---

## 7. Deviations from the (removed) PRDs, recorded rather than hidden

- **No trained components** (§0): PRD2 FR-01's trainable CLIP head and FR-02's
  trained spectral classifier are realised by pretrained checkpoints
  (content detector, SPAI). FR-02's hand-written spectral features survive in
  `frequency.py` for explainability only. Fusion strategy B (a logistic
  meta-classifier) is out — it would be training; strategy A, a weighted
  average, is used.
- **C2** (`app/shared/contracts/c2.py`) carries `semantic_score`,
  `frequency_score` (null when SPAI has no evidence), `fusion_score`,
  `confidence_score`; its changelog records every revision.
- Python 3.13, not PRD2's 3.11. Third-party model code is vendored (SPAI,
  Community Forensics) because neither is a packaged `AutoModel`.
- C1's `tensor_ref` and related fields are always `None`; C1 v2 should drop them.

---

## 8. Recent work (full entries: [docs/session-log.md](docs/session-log.md))

- **2026-10-10** — admin "Remove" action dropped (it was Disable under another
  name); 1-Click Verification made admin-only.
- **2026-10-10** — confidence rule restored to the 2026-10-05 form (migration
  0007); legacy M3 dashboard removed; unused local data cleaned up.
- **2026-10-09/10** — Community Forensics replaced SigLIP 2 after AIGenImages2026
  showed SigLIP 2 at chance on 2025 generators; content detectors became a
  pinned set chosen by D3; TF32 numerics defect found and fixed.
- **2026-10-09** — `main` rebuilt on `dd2ac49` (the calibrated-P(AI) work lives
  on `decision-map-1`); admin tab hidden from non-admins; readable PDF report;
  confidence rule adjusted (reverted 2026-10-10).
- **2026-10-08** — forgot/change password, login activity.
- **2026-10-05** — HTTPS (Caddy), auth hardening, OTP as a second factor.
- **2026-10-03** — React UI (user + admin), model management with quality
  gate, explainability, PostgreSQL + Alembic.
- **2026-10-01** — operating point chosen on a validation split.
- **2026-09-30** — first in-task benchmark (Synthbuster vs RAISE-1k); M1/M3
  integrated.
- **2026-09-07 → 09-12** — pretrained detectors replaced untrained heads; SPAI
  became the frequency branch.
