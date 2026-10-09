# Session log archive

Detailed entries moved out of `CLAUDE.md` on 2026-09-30 to keep that file
to orientation, rules and current state. Newest first. The summary of each
is in `CLAUDE.md` §9; measurement detail is in
[../ml/evaluation/RESULTS.md](../ml/evaluation/RESULTS.md).

---

### 2026-10-09 — main rebuilt on dd2ac49; confidence scaled by 0.8
- `main` was reset to `dd2ac49` and rebuilt. The calibrated-P(AI) work
  (phases 1–4c, C2 v2, migration 0006 with p_ai / certainty) stays on
  `decision-map-1` only.
- On `main`: confidence = `0.5 + 0.5 × 0.8 × margin` from tau, so 50–90 %
  (`CONFIDENCE_SCALE`); migration `0006c` recomputes stored rows and reverts
  exactly. Docs, tests and examples updated (99.7 % → 89.8 %, 65.6 % → 62.5 %).
- Cherry-picked from `decision-map-1`: the Admin Dashboard tab hidden from
  non-admins; reset e-mail sent after the response; one error envelope;
  `PasswordInput`.

### 2026-09-30 — M1 and M3 integrated
- Teammates' M1 (auth, upload, validation, C1 preprocess, React UI) and M3
  (results, history, reports, admin, logs, dashboard) merged into one app.
  Every edit to their code, with its reason, is in
  [changes.md](changes.md). Headlines:
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
