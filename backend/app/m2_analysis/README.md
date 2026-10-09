# M2: Image Analysis and Prediction

Runs two independently pretrained branches over an uploaded image — one
reading **content** (semantic) evidence, one reading **frequency-domain** evidence —
fuses their scores, and returns a Real / AI Generated verdict.

**This module trains nothing.** Both models are third-party checkpoints used
exactly as published, named only in `app/shared/config.py`. There is no
randomly initialised weight anywhere in the inference path. See `CLAUDE.md`
§0 and §2.

| File | Role |
|---|---|
| `detectors.py` | The content (semantic) branch: `semantic(checkpoint)` over the pinned set — Community Forensics (in use) and a SigLIP 2 fine-tune — plus `resolve_ai_index` |
| `frequency_detector.py` | The frequency branch: SPAI, a pretrained spectral detector; digest-verified, strictly loaded |
| `vendor/spai/` | SPAI's model code, vendored as published (Apache-2.0) — see its `NOTICE` |
| `vendor/commfor/` | Community Forensics' model class (MIT) — see its `NOTICE` |
| `pipeline.py` | `run_detection()` — the single entry point and Contract C2 producer |
| `fusion.py` | Score fusion, thresholding, and the confidence inversion |
| `frequency.py` | Hand-written spectral **features** for explainability — produces no score |
| `registry.py` | D3 decides what runs: the active rows, row validation, canary, activation and rollback |
| `gate.py` | The quality gate an activation must pass, on a cached validation reference |
| `model_artifacts.py`, `heads.py` | Registering uploaded heads / fusion configurations, and loading heads |
| `xai.py`, `warmup.py` | Explainability capture (no score), and loading the active models at startup |
| `models.py` | D3 `models` and D4 `predictions` tables (designed by M3, owned by M2) |
| `router_predict.py` | `POST /api/v1/predictions` — `{image_id, xai}`, authenticated, owner only |
| `router_models.py` | `/api/v1/models` — admin-only model management |
| `schemas.py` | The public half of C2, as returned over HTTP |

The SPAI weights are not downloaded automatically (they are published on
Google Drive). One-time setup is in `CLAUDE.md` §4; the converter is
`backend/scripts/convert_spai_checkpoint.py`.

## Three things that bite

**Which output means "AI" is never assumed.** Hugging Face checkpoints
disagree on label order (`AIorNot-SigLIP2` puts AI at index 1; others put it
at 0), so a Hugging Face classifier's index is resolved from its own
`id2label` and `resolve_ai_index` raises rather than guessing. Community
Forensics and SPAI have no labels at all — each is one sigmoid logit — so their
sign conventions are config flags (`SEMANTIC_COMMFOR_AI_IS_POSITIVE`,
`DETECTOR_FREQUENCY_AI_IS_POSITIVE`), justified by the authors' own label maps
and evaluation data and checked against published reference scores
(`tests/test_commfor.py`, RESULTS.md).

**Weights are loaded strictly.** SPAI's upstream loader uses `strict=False`.
Community Forensics' file must match its pinned SHA-256 before it is read.
Ours refuses any missing or unexpected key, any digest mismatch, and any head
that is not a single logit, because a partially loaded model still emits
plausible numbers.

**`confidence_score` is not `fusion_score`.** It is confidence in the
predicted class, measured from the decision threshold (0.5 at tau, rising with the distance from it
to 1.0 at the far end; never below 0.5).
At the operating point tau = 0.4524 a `fusion_score` of 0.08 means "Real" at 0.91 confidence, and 0.30
means "Real" at 0.67 - never the self-contradicting below-0.5 figures of the old `1 - fusion` rule
(replaced 2026-10-05).

M2 owns D3 Models and D4 Predictions. It consumes Contract
C1 and produces Contract C2; see `docs/contracts/` for the documented C2
history. Model registry writes stay inside M2 even when its controls are
rendered by M3.
