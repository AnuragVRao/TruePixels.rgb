# Session log archive

Detailed entries, newest first. `CLAUDE.md` keeps only orientation, rules and
current state; measurement detail is in
[../ml/evaluation/RESULTS.md](../ml/evaluation/RESULTS.md). Entries that name
`changes.md` or the PRD files refer to documents removed from the working tree
in commit `4bf5c15`; they remain in git history (`git show 4bf5c15^:changes.md`).

---

### 2026-10-10 — evaluation images lost in the clean-up
- After the clean-up, `ml/datasets/synthbuster_raise/` (2.3 GB) and
  `ml/datasets/sbr_val/` (4.6 GB) were found empty. Neither was named in any
  delete. The most likely cause: the removed `c2v2-0007` worktree folder held
  directory junctions to these folders (made by an earlier session so tests
  could run there), and Git Bash's `rm -rf` followed them. Not confirmable
  after the fact.
- Unaffected: storage (uploads, panels, weights, gate cache), the database,
  the AIGenImages2026 images, every recorded result.
- To do: re-fetch both sets (`ml/datasets/README.md`) and verify the reference
  images against the SHA-256s in the gate cache's manifest. Lesson: inspect a
  folder for junctions (`dir /AL`) before deleting it on Windows.

### 2026-10-10 — confidence rule restored
- The scale applied to the displayed confidence on 2026-10-09 was removed:
  confidence is again 0.5 at the threshold rising to 1.0 at the far end
  (the 2026-10-05 rule). Migration `0007` recomputed stored rows; its
  downgrade restores `0006c` exactly. Worked examples in the docs updated
  (#18: 63.1 %, Low).

### 2026-10-10 — clean-up
- Removed M3's legacy static dashboard (`frontend/m3_dashboard`, its dev-only
  routes `/`, `/api-tester`, `/developer`, `/playground`, and its e2e check);
  the React app is the only interface. `infra/check_https.py` now asserts those
  paths are 404 in both profiles.
- Local files deleted (gitignored, nothing read them): the 11 GB
  AIGenImages2026 archive (the val and selection subsets stay extracted),
  `storage/tensors/` (dead CLIP tensors), the SigLIP-only gate reference cache,
  `storage/models/spai.pth` (already converted; re-download from the link in
  config to re-convert), and the 2026-09-30 degradation variants (regenerable
  with `ml/datasets/make_variants.py`).
- Git: branch `c2v2-0007` (a migration conflicting with `main`), its worktree,
  and a superseded stash removed. `decision-map-1` kept.

### 2026-10-09 / 10 — Community Forensics replaces SigLIP 2 as the content detector
- **Measured first:** AIGenImages2026 (19 generators from 2025, content-matched
  reals) put SigLIP 2 at AUC 0.53 and the live fusion at 0.714. Bake-off on a
  selection pool (AIGenImages2026 train + sbr_val), reported on two held-out
  sets: Community Forensics + SPAI (w 0.55, τ 0.4524) 0.798 / AUC 0.895 and
  0.939 / AUC 0.986. RESULTS.md 2026-10-09.
- **Pinned set** `config.SEMANTIC_BACKBONES` (SigLIP 2 + Community Forensics);
  the active D3 semantic row picks one (`detectors.semantic`). Registry,
  canary, warm-up, `/health`, gate and reference builder generalised; uploaded
  heads stay SigLIP-only. Gate reference rebuilt with both detectors.
- **Found and fixed:** cuDNN TF32 convolutions shifted Community Forensics
  (0.7860 → 0.7655 on a reference image). Patch projection as unfold + matmul;
  bake-off re-scored and re-selected (same w, τ).
- Explanation: CLS rollout (`commfor-attention-rollout`, own caption), drawn
  inside the outlined centre crop the model sees (`attention_region`).
- Live D3: semantic #7 + fusion #8 activated through the gate (both passed).
- Tests: `test_commfor.py` (19); model-management tests re-based on the new
  operating point; SigLIP-only paths run on a SigLIP-seeded test D3.

### 2026-10-09 — confidence rule updated; non-admins lose the admin tab
- `fusion.confidence_in_prediction` updated; migration **0006c** recomputes
  stored rows (reversible).
- **Branch history:** `main` was rebuilt on `dd2ac49`. The P(AI) /
  calibration work (C2 v2, phases 1-4c, migration 0006 p_ai) lives only on
  `decision-map-1`; its `0006` and this `0006c` are different migrations, so
  a database must be downgraded to 0005 on one branch before following the
  other.
- Admin Dashboard tab hidden from non-admins; reset e-mail sent after the
  response; one error envelope (cherry-picked from `decision-map-1`).
- **Fusion weights made equal (owner's decision): w = 0.5, τ = 0.6665.** τ
  re-selected for w = 0.5 by `select_threshold.py` on the validation CSV
  (0.666505). Registered as D3 fusion row #6 and activated through
  `registry.activate` (canary ok, gate passed: 0.78 / FPR 0.12 / AUC 0.898
  vs current 0.77 / 0.14 / 0.904; 11 of 100 labels changed); #3 (w 0.25) is
  one rollback away. Held out: accuracy 0.783, recall 0.657, FPR 0.091
  (MM2.6 now met), AUC 0.928 - fewer false alarms, fewer AI images caught.
- PDF report rewritten for non-technical readers (result first, plain
  captions, "Keep in mind", technical details last; 2 pages).

### 2026-10-09 — main rebuilt on dd2ac49; confidence rule updated
- `main` was reset to `dd2ac49` and rebuilt. The calibrated-P(AI) work
  (phases 1–4c, C2 v2, migration 0006 with p_ai / certainty) stays on
  `decision-map-1` only.
- On `main`: the confidence rule was updated; migration `0006c` recomputes
  stored rows and reverts exactly. Docs, tests and examples updated.
- Cherry-picked from `decision-map-1`: the Admin Dashboard tab hidden from
  non-admins; reset e-mail sent after the response; one error envelope;
  `PasswordInput`.

### 2026-10-08 — forgot password, change password, login activity
- Migration 0005:
  - `users.token_version` (the `ver` claim) and `users.password_changed_at`;
  - `password_resets`, one hashed code per user;
  - `login_events`.
- Endpoints:
  - `POST /auth/password/forgot`, `/auth/password/reset` and `/auth/password/change`;
  - `GET /users/me/login-activity` and `GET /admin/login-activity`.
- Reset codes are kept out of `users.otp_*`. Widening that CHECK on SQLite would rebuild `users`
  and lose the `lower(email)` index, and a separate table also stops a reset from replacing a
  pending sign-in code.
- A wrong current password is 400, not 401: the React client signs out on any 401.
- `changes.md` was removed by the user in `4bf5c15`. These M1/M3 edits are recorded in
  docs/auth-hardening.md instead.
- React:
  - "Forgot password?" on both portals, then `/forgot-password`;
  - `/account` (reached from the e-mail chip): change password plus own login activity;
  - admin "Login Activity" tab.
- Tests: `test_password_reset.py` and `test_login_activity.py` (25). `test_migrations.py`'s 0004
  test now re-upgrades to head.

### 2026-10-05 — Phase 6 (HTTPS) and the pre-6 auth hardening
- Pre-6:
  - OTP is a second factor: challenges are bound to a password or to
    registration; codes are purged on expiry;
  - sign-in is throttled per address and per account, with flood-proof
    eviction and a fallback for keys that cannot be tracked;
  - the user rotated the database password and the JWT key;
  - the database container now gets only the `POSTGRES_*` values;
  - M1's old components were deleted (tag `pre-m1-cleanup`).
- Phase 6: Caddy runs in Docker in front of uvicorn on the host
  (127.0.0.1).
  - `host.docker.internal` reached uvicorn on loopback, but uvicorn sees
    the proxy as `127.0.0.1`. Forwarded headers are therefore trusted only
    with a shared secret (`PROXY_SHARED_SECRET`), not by IP.
  - The CSP has no `unsafe-inline` or `unsafe-eval` for scripts.
  - Fonts are self-hosted, and Vite's `data:` inlining is off: the first
    HTTPS run caught `data:` fonts blocked by `font-src`.
  - `ENVIRONMENT` defaults to production, which turns off `/docs` and the
    legacy dashboard.
  - CORS is empty in production unless configured.
- Evidence:
  - `infra/check_https.py`: dev 46/46, prod 47/47, TLS verified against
    Caddy's CA;
  - Playwright through HTTPS (certificate errors ignored), 0 CSP
    violations: user flows 17/17, admin flows A1–A8, prod smoke 3/3.
- **Next:** Phase 7 (performance and concurrency).

### 2026-10-03 — Phase 5b (admin UI) and pre-5b security fixes
- Pre-5b:
  - console OTP codes no longer reach D6;
  - `dev_otp` removed;
  - hard size ceilings on every file endpoint;
  - the gate's reference cache is content-keyed, and a stale cache is
    refused;
  - the post-login redirect is same-origin only.
- React admin screens: overview, logs, users and models.
  - Every figure comes from the API.
  - Latency is warm-only p50/p95.
  - Metadata only; admins never see user images.
- One account policy for M1 and M3: no self-change, never zero active
  admins, `USER_NOT_FOUND`. "Remove" is a soft status change; nothing is
  deleted.
- `POST /models/{id}/gate-preview`: gate metrics per candidate before any
  decision. The UI frames them as a coarse safety net. Override needs a
  reason and an explicit acknowledgement.
- Legacy dashboard demoted:
  - the XSS sink, CLIP labels and fake health tile are fixed;
  - `api_tester` "Run All" no longer always passes.
- Browser (headless Chromium): admin flows A1–A8 and the legacy-dashboard
  checks all pass. The 5a user flows were re-run after the routing change.
- **Phase 6 note:** test the CSP against the real build (recharts inline
  SVG styles, `blob:` images, lazy admin chunks). The legacy dashboard
  needs CDN sources or should not be served in production.
- **Next:** delete the superseded M1 components (separate commit, after
  the M1 owner is told), then Phase 6.

### 2026-10-03 — Phase 5a (React user flows)
- React app: routes for sign-in / register / OTP, upload + analyse, results
  (panels with backend captions, model rows, PDF via blob), history. Token in
  sessionStorage; all files via Authorization header + blob URLs. `?token=`
  removed from `/reports`. ESLint with `react/no-danger`.
- Browser run (headless Chromium, Playwright; the Chrome extension was not
  connected): 16 of the 17 manual-test steps automated and passing; found and
  fixed a sign-out-on-reload bug and a server-side file-handle leak on Windows
  (trigger unconfirmed; fixed by reading stored files in memory).
- **Next:** Phase 5b (admin UI).

### 2026-10-03 — Phase 4 (model management, F.19)
- D3 became the authority: `registry.active(db)` reads the active rows; the
  stale-provenance defect was reproduced in a failing test first (commit
  `4f00e19`), then fixed. SigLIP pinned to revision `f4e6a281…`, loaded from
  the local cache (works with `HF_HUB_OFFLINE=1`).
- Quality gate on a cached 100-image `sbr_val` reference. Thresholds fixed
  before any candidate was scored. τ 0.60 passes and flips labels
  (asserted by test); τ 0.05 is refused (FPR). Finding: on this reference, τ 0.65 scores
  accuracy 0.83 vs the baseline τ 0.7558's 0.77 at the same FPR 0.14 —
  **not acted on** — within the noise of 100 images, and the gate's data is
  not tuning data (limitation 12).
- Rollback made the gate advisory (it is a return to a previously active
  model); decided by default, reversible.
- **Next:** Phase 5 (React front end).

### 2026-10-03 — Phase 2 (PostgreSQL + Alembic) and Phase 3 (explainability)
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
  (`changes.md` (removed in `4bf5c15`; in git history) §3.0b).
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
  schema and PDF made null-tolerant (`changes.md` (removed in `4bf5c15`; in git history) §3.0).
- Verified the scoring path was unaffected by the M1/M3 merge landing
  mid-run: crop1024 re-scored 198/198 bit-identical.
- **Next:** choose τ on a *fresh* validation split (a second disjoint slice
  of the same sets) to close MM2.6 and MM2.5 the way PRD2 FR-03 specifies —
  that is an operating-point choice, not training, and it reopens Step 4's
  "superseded" ruling now that labelled data exists. Then a post-2023
  generator set (MM2.2). Scaling this set to 1000/class would narrow the
  intervals and change no conclusion.

### 2026-09-30 — M1 and M3 integrated
- Teammates' M1 (auth, upload, validation, C1 preprocess, React UI) and M3
  (results, history, reports, admin, logs, dashboard) merged into one app.
  Every edit to their code, with its reason, is in
  `changes.md` (removed in `4bf5c15`; in git history). Headlines:
  - one definition of each contract (C1–C3), one `db`/`errors`/`logging`;
    M3's models import D1/D2 from M1 and D3/D4 from M2 instead of
    redefining them (a startup crash otherwise);
  - M3's mock `/mock/predict` and synthetic heatmap/spectrum fallbacks
    removed from the live app; its stubs are test-only;
  - M3's report download had **no authentication** (a query-string
    `authorization`, and a fallback to user 1) — now M1's token check;
  - a real Gmail app password hard-coded in M1's `email_service.py` removed.
    **It must be revoked** — it was in the zip and may be in M1's repo.
- M2: `dev_intake.py` deleted; `/predictions` is PRD2 §10.1's JSON form,
  authenticated, owner-only; the pipeline writes D3 rows (from config,
  metrics null) and the D4 row, and commits before returning.
- One storage tree (`storage/`, served at `/static`) for all three modules.
- 152 tests green: M1 36, M3 27, M2 76 fast + 13 model-backed.
- **Next:** Step 6 (ActivationBundle, so M3 has real panels to draw);
  make D3 authoritative (rest of Step 5); C1 v2 without the tensor.

### 2026-09-12 (later still) — first labelled evaluation; venv fixed
- Added `ml/evaluation/evaluate.py` (Step 7 tooling): production path per
  image, per-branch + fused metrics at τ, AUC, FPR on real, and the
  information-only best-threshold accuracy.
- Ran it on a user-supplied AttGAN set (4,000 CelebA-HQ faces): **at chance
  for both branches**, SPAI FPR 0.95. Diagnosed as (a) an out-of-scope task
  (localised edits) and (b) a "real" class that is itself network-processed;
  the five-crop small-image regime was probed and cleared. Recorded in §6
  with a new limitation (learned enhancement looks synthetic).
- A user image from a modern generator (stylised "AI dog") was missed by
  SPAI (3×10⁻²⁴) and vetoed SigLIP's 0.92 through the unweighted average;
  compression and size were ruled out. Recorded in §6.
- The repo `.venv` was a Python 3.14 environment with nothing installed
  ("No module named uvicorn"); recreated from 3.13.6 with the cu126 torch.
  87 tests green from inside it.
- **Next:** an evaluation set that matches the task (camera originals vs
  whole generated images, e.g. Synthbuster + RAISE); then the deployment
  step or Step 5.

### 2026-09-12 (later) — both branches on the RTX 4050
- Installed torch `2.13.0+cu126` (same pinned version, CUDA build; the `+cu126`
  tag must be explicit). No code change needed for device selection.
- Sized SPAI's patch batch by measurement on 6 GB: 16 (3.4 GB peak). Found
  and documented the WDDM spill hazard — an over-large batch stalls silently
  instead of raising OOM. `score()` now releases the CUDA cache per request.
- GPU canary: identical verdicts (13/14), scores within 0.0006 of the CPU
  run; SPAI p50 4.1 s / max 33.6 s vs 102 s / 979 s on CPU. Tables in §4.
- Added a cpu/cuda-parametrised test for the vendored FFT filter; `/health`
  reports `feature_batch`. 87 tests green.
- **Deferred, on purpose:** serving the laptop as the deployed backend
  (tunnel, CORS, no-auth caveat, single worker). Nothing in this step
  precludes it; `main.py` remains the single place to add CORS.
- **Next:** deployment plan, or Step 5 (D3/D4), or Step 7 (benchmark).

### 2026-09-12 — SPAI becomes the frequency branch; SwinV2 removed
- Verified that FR-02's "classifier over spectral features" cannot exist
  without training, then surveyed published frequency-domain detectors with
  released weights. NPR (CVPR 2024) rejected as a pixel-space proxy with no
  licence; a FaceForensics FFT repo rejected for publishing no weights.
  Chose **SPAI** (CVPR 2025, Apache-2.0 code + weights).
- Vendored the inference subset of `spai/models` with LICENSE + NOTICE;
  replaced timm/torchvision/einops with local shims; no arithmetic changed.
  The released `spai.pth` is a 935 MB pickled training checkpoint that
  `weights_only=True` refuses (embedded yacs config) → one-time offline
  conversion to safetensors under a restricted unpickler; runtime loads only
  that, verifies a digest of the weights, and loads **strictly** — 324/324.
- Removed the SwinV2 branch and `secondary_score`; C2 back to PRD2 §7.3.
  Fusion is FR-03 strategy A verbatim.
- Sign convention verified from the authors' evaluation CSVs and by the
  smoke canary (§6): 13/14, SPAI mean 0.978 on generated vs 0.146 on real.
- **Latency on CPU is far outside MM2.7** at native resolution (p50 102 s)
  and every `resize_to` cap costs verdicts (§4). Default left at `None`.
  Resolved the same day by moving inference to the GPU (entry above).
- 86 tests green at that point (75 fast, 11 model-backed).
- **Next:** resolve the latency decision; then Step 5 (D3/D4) or Step 7
  (benchmark with the SigLIP 2 / SPAI / fused ablation).

### 2026-09-07 (later) — pretrained detectors replace the untrained heads
- Verified against the HF API that vanilla SigLIP 2 is **not** a detector, but
  that genuine SigLIP 2 detection fine-tunes exist. Chose
  `prithivMLmods/AIorNot-SigLIP2` over the more popular
  `Ateeqq/ai-vs-human-image-detector`, which carries no `base_model` metadata
  and whose card reports overfitting.
- Added `detectors.py` with `resolve_ai_index`; deleted `semantic.py`; removed
  the frequency classifier head. **No randomly initialised weights remain.**
- Found and guarded the label-order hazard: the two detectors have opposite AI
  indices.
- C2: `frequency_score` → always null, `secondary_score` added.
- 69 tests green. Smoke-tested on 14 Commons images (see §6) — 12/14, with two
  false positives on real photographs.
- **Next:** Step 5 (D3/D4 persistence), or Step 7 (benchmark on a public
  labelled set) if a real FPR number is wanted before demoing further.

### 2026-09-07 (earlier) — first end-to-end path
- Built M2 from an empty repo: contracts, config, registry, branches, fusion,
  pipeline, HTTP layer. 52 tests green.
- Heads were randomly initialised; scores were meaningless by construction.
  Superseded the same day by the change above.
