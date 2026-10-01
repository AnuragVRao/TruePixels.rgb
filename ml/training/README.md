# Training — RETIRED

**This directory is intentionally empty and must stay that way.**

TruePixels.rgb never trains, fine-tunes, or retrains a model. Detection uses
third-party pretrained checkpoints exactly as published. This is not a
deferred milestone; it is a permanent scope boundary. See `CLAUDE.md` §0.

The original scaffold planned training pipelines here for the CLIP
classification head, the frequency-artifact classifier, the fusion strategy,
and calibration parameters. All four are superseded:

| Was going to be trained | Replaced by |
|---|---|
| CLIP classification head | `prithivMLmods/AIorNot-SigLIP2`, a pretrained SigLIP 2 detector |
| Frequency-artifact classifier | SPAI (`mever-team/spai`, CVPR 2025), a pretrained spectral detector. The hand-written FFT pipeline survives for explainability features only |
| Fusion strategy (logistic meta-classifier) | Strategy A, a fixed unweighted average |
| Calibration temperature | Not fitted; left as a documented no-op |

If you need better detection, **swap the checkpoint** in
`backend/app/shared/config.py`. Do not add code here.

Measuring a pretrained detector is a different thing from training one and is
still welcome — that belongs in `../evaluation/`.
