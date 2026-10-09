# Evaluation

**Still in scope.** Measuring a pretrained detector is evaluation, not
training: it reads weights and reports numbers, it never updates them. That
distinction is what separates this directory from `../training/`, which is
retired.

`evaluate.py` runs any `<root>/0_real` + `<root>/1_fake` set through the
production path and reports per-branch and fused metrics with 95 % intervals
(see its docstring). `select_threshold.py` picks τ on a validation split.
**Every result is in [RESULTS.md](RESULTS.md)**; the headline held-out figures
are also in `CLAUDE.md` §5. Evaluations so far:

- 2026-09-12: AttGAN, an out-of-scope face-edit set (a negative control).
- 2026-09-30: Synthbuster vs RAISE-1k (2022–23 generators), with ablation,
  a resolution control and a degradation sweep.
- 2026-10-01: operating point chosen on a disjoint validation split.
- 2026-10-09: AIGenImages2026 (19 generators from 2025), and a bake-off that
  replaced the content detector, reported on two held-out sets.

## What every evaluation reports

- Accuracy, precision, recall, F1 and ROC-AUC, overall and per generator,
  each with its interval.
- **False-positive rate on real photographs** — the most important number.
  Calling a genuine photograph AI-generated is the more damaging error, and
  MM2.6 wants FPR ≤ 0.10.
- Per-branch ablation: content detector alone, SPAI alone, fused.
- The claim the numbers support, stated narrowly: separation of *these*
  generators' images from *these* real photographs, never "the accuracy of the
  system".

## Rules

- Use a test set neither model was trained on, and say when that cannot be
  guaranteed (Synthbuster is one of SPAI's own test sets).
- Configuration constants (`w`, τ) may be chosen only on a selection or
  validation split, never on a test set; report on held-out data that played
  no part in the choice.
- Touch a test set once per decision. Choosing anything from its results is
  how a test set silently becomes a validation set.
- Report what was measured, including results that are worse than hoped.

## Regression check (NF.5): `regression_check.py`

Not an accuracy measurement — a tripwire. It sends a fixed list of images
(`regression_images.json`, committed: 21 files from the local Synthbuster /
RAISE sets plus 3 seeded synthetic images, one below SPAI's 224 px minimum)
through the real HTTP path — M1 upload, `POST /api/v1/predictions` — against a
scratch database, and stores every score as `float.hex`, so the comparison is
bit-exact rather than rounded.

```bash
python ml/evaluation/regression_check.py --record --out pre-phaseN   # before a change
python ml/evaluation/regression_check.py --compare                   # after it
```

Run `--record` before any change that could touch the scoring path and
`--compare` after; a mismatch prints every differing field. Baselines are
written to `ml/outputs/regression/` (gitignored) together with the device
they were recorded on — GPU and CPU differ in the last bits, so only
same-device comparisons are expected to be identical.

## Explainability checks

- `xai_faithfulness.py`: a deletion sanity test of the semantic attention
  map. Masking the top-attended region is compared with random and
  bottom-attended regions of equal size, on the validation split.
- `xai_cost.py`: latency and peak VRAM with xai off vs on, through the HTTP
  path, including 16 MP images.

Results and caveats are in `RESULTS.md` under "Explainability: faithfulness
and cost".
