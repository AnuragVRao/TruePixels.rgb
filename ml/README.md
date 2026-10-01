# Machine Learning

**No model training happens in this project.** Detection uses third-party
pretrained checkpoints exactly as published; see `CLAUDE.md` §0 for the full
rule and §2 for the checkpoints in use.

Runtime inference code lives in `backend/app/m2_analysis/detectors.py`
(semantic branch) and `backend/app/m2_analysis/frequency_detector.py`
(frequency branch), not here.

## Folders

- `training/`: **retired.** Kept only to record why it is empty.
- `datasets/`: fetch scripts and metadata for the evaluation sets. No images
  are committed — `fetch_synthbuster.py` and `fetch_raise.py` pull them on
  request, `make_variants.py` derives the control and degradation arms.
- `evaluation/`: **in scope** — measuring the pretrained detectors. Reading
  weights and reporting numbers is not training. `evaluate.py` runs a labelled
  set through the production path; `select_threshold.py` picks the decision
  threshold on a validation split; **`RESULTS.md` holds every measurement**.
- `notebooks/`: exploratory analysis of detector behaviour.
