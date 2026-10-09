# Datasets

**No dataset is collected for training.** TruePixels.rgb never trains a model
(`CLAUDE.md` §0). Labelled images are used only to **measure** the pretrained
detectors and to choose two configuration constants (the fusion weight and
threshold) on a validation/selection split. Images are never committed: this
folder holds the fetch scripts and documentation, and the sets are rebuilt on
each machine.

| Set (folder, gitignored) | Role | How to get it |
|---|---|---|
| `synthbuster_raise/` | held-out test, 2022–23 generators (99 + 99) | `fetch_synthbuster.py --per-model 11`, `fetch_raise.py` |
| `sbr_val/` | validation split (scenes 99-296, 198 + 198); also the quality gate's reference sample | `fetch_synthbuster.py --per-model 22 --offset 99 --out ml/datasets/sbr_val`, then `fetch_raise.py --out ml/datasets/sbr_val` |
| `aigen2026_raw/val/` | held-out test, 2025 generators (559 + 559) | [AIGenImages2026](https://huggingface.co/datasets/pthan12/AIGenImages2026), `val` split |
| `aigen2026_select/` | part of the 2026-10-09 selection pool (500 real + 499 AI, seeded draw from the `train` split) | the same archive |
| `synthbuster_raise__*` | degradation / control arms of the 2026-09-30 study | `make_variants.py` |

**On this machine (2026-10-10):** `synthbuster_raise/` and `sbr_val/` are
empty and must be re-fetched — their contents were deleted by mistake during a
clean-up. Until then the regression check, the explainability-cost scripts,
rebuilding the gate reference, and two slow tests in `test_model_management.py`
cannot run. The gate's existing reference cache and every recorded result are
unaffected; the cache's manifest records the SHA-256 of each reference image,
so a re-fetch can be verified byte for byte.

If an evaluation set is added, two constraints from the original design still
apply and still matter:

- It must exclude `competitions/aiornot`, which is the primary detector's own
  training data.
- It should include at least one generator family that neither checkpoint is
  likely to have seen. That figure — behaviour on unfamiliar generators — is
  the one that actually predicts deployment behaviour, and it is the reason
  PRD2 puts MM2.2 ahead of MM2.1.

## Evaluation sets on this machine

### `AttGAN/AttGAN/` (repository root, gitignored) — added 2026-09-12, no longer on this machine

2,000 `0_real` + 2,000 `1_fake` PNGs, 256×256, `<root>/0_real` / `<root>/1_fake`
layout. Face images: the fakes are AttGAN attribute edits of CelebA-HQ faces,
the "reals" are the unedited CelebA-HQ faces. This is the AttGAN split of the
GAN-detection benchmark family (ForenSynths / GANGen-Detection style).

**What it measures.** "Edited CelebA-HQ face vs unedited CelebA-HQ face" — a
face-forensics question. It does **not** measure "AI-generated image vs camera
photograph", for a reason that matters to a spectral detector: CelebA-HQ
itself was produced by running CelebA through a trained super-resolution
network and a filtering pipeline (Karras et al. 2018, appendix C). Every
"real" image here already contains neural-network-generated high-frequency
content. SPAI scores ~1.0 on nearly all of them; the same detector scores
0.000 on genuine photographs downscaled to the same 256 px (probe recorded in
`../evaluation/RESULTS.md`), so this is a property of the images, not of the resolution.

Use it as a **negative control** and as a stress test of the semantic branch
on faces. Do not quote its accuracy as the system's accuracy for the task the
system exists for. Run with `python ml/evaluation/evaluate.py AttGAN/AttGAN`.

### `ml/datasets/synthbuster_raise/` (gitignored) — added 2026-09-30

The in-task set: **whole generated images vs camera originals**, which is what
AttGAN could not provide. 99 per class by default, paired scene for scene.

| class | source | licence |
|---|---|---|
| `1_fake` | [Synthbuster](https://zenodo.org/records/10066460) (Bammey 2023) — 11 images from each of 9 generators: DALL·E 2, DALL·E 3, Firefly, Glide, Midjourney v5, SD 1.3 / 1.4 / 2 / XL | **CC-BY-NC-SA-4.0 — non-commercial** |
| `0_real` | [RAISE-1k](https://loki.disi.unitn.it/RAISE/download.html) (Dang-Nguyen 2015) — uncompressed TIFFs from Nikon D90 / D7000 / D40 | research use; cite the paper |

Build it with:

```bash
python ml/datasets/fetch_synthbuster.py --per-model 11   # ~130 MB
python ml/datasets/fetch_raise.py                        # ~1.5 GB
python ml/datasets/make_variants.py --degrade            # control + degradation arms
```

**Why these two.** Synthbuster's prompts describe RAISE photographs, so its
filenames *are* RAISE ids and the two sets pair one-to-one. All nine
generators were given the same 1,000 scenes, so `fetch_synthbuster.py` hands
each generator a **disjoint** slice of the id list: the 99 fakes therefore span
99 distinct scenes rather than 11 scenes nine times over, and the 99 reals are
exactly those scenes. Each scene appears once as a photograph and once as a
generated image.

**Two things to know before quoting any number from it.**

1. **Synthbuster is one of SPAI's own published test sets.** A good SPAI score
   here confirms our integration reproduces the authors' result; it is *not*
   independent evidence that SPAI generalises. Community Forensics was trained
   on ~4,800 generators that may include these; SigLIP 2 had not seen the set.
2. **The classes differ in resolution, and the fake class is not uniform.**
   Reals are 4288×2848 / 4928×3264 TIFFs. The generated class, measured rather
   than assumed, spans **256×256 (Glide) to 2688×1536 (Firefly)**, with ten
   aspect ratios inside SD 2 and SD XL alone, and DALL·E 3 images carrying an
   alpha channel. Glide's 256² images fall into SPAI's five-crop fallback
   instead of its sliding-window regime, so they are processed differently
   from every other generator. `make_variants.py` builds control arms to say
   how much of the headline number survives when the size difference is
   removed — `__crop1024` is the valid control (it equalises resolution *and*
   patch count) and it costs only 0.031 AUC. `__resize1024` transforms only
   the reals and is therefore **not** a control; read it as a probe of what
   drives false positives. Results and the pre-registered reading: `../evaluation/RESULTS.md`.
3. **`make_variants.py --degrade` floors every output at 224 px**, because
   SPAI raises on anything smaller and halving Glide's 256² images crashed the
   first attempt. The 11 floored images are reported when the arm is built.

**Practical note.** The download host in `RAISE_1k.csv`
(`193.205.194.113`) is effectively dead — an 8 MB range request timed out
twice at over 180 s on 2026-09-30. `fetch_raise.py` ignores the CSV's URLs and
uses `loki.disi.unitn.it`, which serves the same files at ~1 MB/s.
`dataset/1.py` (the user's original extractor) is correct and is kept as the
reference implementation; `fetch_synthbuster.py` reproduces its selection rule
without needing the 12.4 GB archive on disk.
