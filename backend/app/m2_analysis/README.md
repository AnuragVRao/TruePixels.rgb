# M2: Image Analysis and Prediction

Runs two independently pretrained branches over an uploaded image — one
reading **semantic** evidence, one reading **frequency-domain** evidence —
fuses their scores, and returns a Real / AI Generated verdict.

**This module trains nothing.** Both models are third-party checkpoints used
exactly as published, named only in `app/shared/config.py`. There is no
randomly initialised weight anywhere in the inference path. See `CLAUDE.md`
§0 and §2.

| File | Role |
|---|---|
| `detectors.py` | The semantic branch: a pretrained SigLIP 2 fine-tune, plus `resolve_ai_index` |
| `frequency_detector.py` | The frequency branch: SPAI, a pretrained spectral detector; digest-verified, strictly loaded |
| `vendor/spai/` | SPAI's model code, vendored as published (Apache-2.0) — see its `NOTICE` |
| `pipeline.py` | `run_detection()` — the single entry point and Contract C2 producer |
| `fusion.py` | Score fusion, thresholding, and the confidence inversion |
| `frequency.py` | Hand-written spectral **features** for explainability — produces no score |
| `registry.py` | Active configuration from config; records the D3 rows each prediction ran with |
| `models.py` | D3 `models` and D4 `predictions` tables (designed by M3, owned by M2) |
| `router_predict.py` | `POST /api/v1/predictions` — `{image_id, xai}`, authenticated, owner only |
| `schemas.py` | The public half of C2, as returned over HTTP |

The SPAI weights are not downloaded automatically (they are published on
Google Drive). One-time setup is in `CLAUDE.md` §4; the converter is
`backend/scripts/convert_spai_checkpoint.py`.

## Three things that bite

**Which output means "AI" is never assumed.** Hugging Face checkpoints
disagree on label order (`AIorNot-SigLIP2` puts AI at index 1; others put it
at 0), so the semantic branch resolves the index from the checkpoint's own
`id2label` and `resolve_ai_index` raises rather than guessing. SPAI has no
labels at all — it is one sigmoid logit — so its sign convention is a config
flag (`DETECTOR_FREQUENCY_AI_IS_POSITIVE`), justified by the authors' own
evaluation CSVs (generated = 1) and checked against real images in the
`CLAUDE.md` smoke test.

**Weights are loaded strictly.** SPAI's upstream loader uses `strict=False`.
Ours refuses any missing or unexpected key, any digest mismatch, and any head
that is not a single logit, because a partially loaded model still emits
plausible numbers.

**`confidence_score` is not `fusion_score`.** It is confidence in the
predicted class, measured from the decision threshold (0.5 at tau, 1.0 at the far end; never below 0.5).
At the operating point tau = 0.7558 a `fusion_score` of 0.08 means "Real" at 0.95 confidence, and 0.52
means "Real" at 0.65 - not the 0.48 the old `1 - fusion` rule gave (changes.md 6.21).

M2 owns D3 Models and D4 Predictions (neither built yet). It consumes Contract
C1 and produces Contract C2; see `docs/contracts/` for the documented C2
history. Model registry writes stay inside M2 even when its controls are
rendered by M3.
