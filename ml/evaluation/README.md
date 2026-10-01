# Evaluation

**Still in scope.** Measuring a pretrained detector is evaluation, not
training: it reads weights and reports numbers, it never updates them. That
distinction is what separates this directory from `../training/`, which is
retired.

`evaluate.py` runs any `<root>/0_real` + `<root>/1_fake` set through the
production path and reports per-branch and fused metrics (see its docstring).
It has been run once, on AttGAN — an out-of-scope face-edit set on which both
branches are at chance; see `CLAUDE.md` §6 and `../datasets/README.md` for why
that number is not the system's accuracy. Consequently **no accuracy figure
for TruePixels.rgb on its own task exists yet**. The only numbers currently quotable are the upstream
checkpoints' own self-reported metrics, which must always be attributed to
their authors and to their splits.

## What a first evaluation should report

Per PRD2 §13.5 and NF.3, against a public labelled test set:

- Accuracy, precision, recall, F1 and ROC-AUC, overall and per generator family.
- **False-positive rate on real photographs** — the most important number
  here. PRD2 FR-03 argues that calling a genuine photograph AI-generated is
  the more damaging error, MM2.6 wants FPR ≤ 0.10, and an ad-hoc 14-image
  smoke test already produced two false positives on real photos. This needs a
  real measurement.
- Expected calibration error, plus a reliability diagram. The fused score is
  currently uncalibrated and no temperature has been fitted.
- Per-branch ablation: SigLIP 2 alone, SPAI alone, fused. Whether fusion
  actually helps is an open question — on the 2026-09-07 smoke test with the
  previous second branch it helped twice and hurt once; the SPAI smoke test of
  2026-09-12 is recorded in `CLAUDE.md` §6.
- Because the frequency branch was chosen over a cheaper alternative (NPR)
  on the strength of the authors' numbers, not ours, the ablation should be
  run before that choice is treated as settled.
- Robustness sweep: JPEG quality 95/85/75/60, 50% downscaling, mild noise.

## Rules

- Use a test set neither model was trained on. `competitions/aiornot` is the
  semantic branch's training data; COCO, LSUN and the Latent Diffusion set
  are SPAI's. None of them can be used to evaluate the branch trained on it.
- Touch the test set once. There are no hyperparameters to tune here, because
  tuning them on results is how a test set silently becomes a validation set.
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
