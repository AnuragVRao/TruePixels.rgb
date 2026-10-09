# How a score is computed

What happens between a user choosing an image and the result page showing
"AI Generated, 63.1 %". Every number below is what the code does today; the
constants live in [backend/app/shared/config.py](../backend/app/shared/config.py).

```
upload ──► validate & store ──► content detector (Community Forensics) ──┐
                           └──► frequency detector (SPAI) ───────────────┤
                                                                         ▼
                                        combined score = 0.55·content + 0.45·frequency
                                                                         ▼
                                        verdict: AI Generated if combined ≥ 0.4524
                                                                         ▼
                                        confidence: distance from 0.4524, shown as a percentage
```

---

## 1. Upload and validation

`POST /api/v1/images` ([m1_access](../backend/app/m1_access/)).

The image is accepted only if:

- it really is a **JPG or PNG**: the first bytes of the file are checked, not
  the file name;
- it is **at most 10 MB** and **at most 25 megapixels**, which guards against
  decompression bombs;
- **both sides are at least 64 px**;
- it decodes cleanly, so truncated or corrupted files are refused.

The original file is stored exactly as uploaded. Each detector reads this
original file and applies its own preprocessing: the content detector resizes
and crops it as its authors do, while the frequency detector never resizes it.

## 2. Two detectors, two kinds of evidence

`POST /api/v1/predictions` ([m2_analysis/pipeline.py](../backend/app/m2_analysis/pipeline.py)).
Both models are published, pretrained checkpoints, used exactly as released;
this project never trains or fine-tunes a model.

**Why two:** a generator that fools one kind of evidence has no particular
reason to also fool the other.

### Content detector: Community Forensics (`OwensLab/commfor-model-384`, CVPR 2025)

Looks at **what the picture shows**: textures, lighting, the "too clean" look
of generated images. It was trained by its authors on images from about 4,800
different generators, specifically so that it would hold up on generators it
has never seen.

1. The image is converted to RGB, its shortest side is resized to 440 px and
   the central **384 × 384** square is cut out (the authors' own test
   procedure). This detector therefore sees the centre of the image, not the
   edges.
2. A vision transformer (ViT-S/16) produces **one number** (a logit).
3. **Content score = sigmoid(logit)**: between 0 and 1, higher means more
   likely AI. That higher means "AI" is the authors' published convention, and
   our tests check it by reproducing the authors' own example scores.

The weights are loaded only if their SHA-256 matches the pinned value, and
every tensor must match the model exactly.

Until 2026-10-09 this branch was SigLIP 2 (`prithivMLmods/AIorNot-SigLIP2`).
On images from 2025 generators it could barely tell AI from real (AUC 0.53),
so it was replaced after a comparison; it is still installed and can be
switched back by an administrator.

### Frequency detector: SPAI (CVPR 2025)

Looks at **the pixel grid itself**, ignoring the content. Generators leave
statistical traces in the fine, high-frequency detail that cameras do not.

1. The image is **tiled into 224 × 224 patches at its native resolution**,
   never resized. Downscaling would erase exactly the detail this detector
   reads.
2. Each patch is split by a Fourier transform into a low-frequency part and a
   high-frequency part (circular mask, radius 16).
3. A vision transformer encodes the original, the low part and the high part.
   This transformer was pretrained to reconstruct missing frequency bands of
   *real* photographs.
4. The model measures how similar those three encodings are, the "spectral
   reconstruction similarity". A model that only knows real-photo statistics
   reconstructs a generated image differently.
5. An attention layer weighs all the patches together and produces **one
   number** (a logit).
6. **Frequency score = sigmoid(logit)**: a value between 0 and 1, where higher
   means more likely AI.

The bigger the image, the more patches there are and the longer this takes:
about 1–3 s on the GPU for an ordinary photo.

**Images smaller than 224 px** on either side have no complete patch, so SPAI
has no evidence at all. The frequency score is then shown as *not measured*,
and the verdict rests on the content detector alone; the result page says so.

## 3. The combined score

```
combined = 0.55 × content + 0.45 × frequency
```

([m2_analysis/fusion.py](../backend/app/m2_analysis/fusion.py), `combine`)

- **How the weight and threshold were chosen:** on a selection set of 698
  real and 697 generated images (from 2025 and 2022–23 generators), kept
  separate from the test sets. For every weight, the lowest threshold that
  keeps false alarms on real photos at or below 10 % was found, and the weight
  that then catches the most AI images was kept.
- **No model was changed:** the weight is a setting; the models are unchanged.
- **One detector only:** without a frequency score, the combined score is
  simply the content score.

All three of these numbers (content, frequency, combined) mean the same thing:
**the probability, as the model sees it, that the image is AI-generated**.

## 4. The verdict

```
AI Generated   if combined ≥ τ      (τ = 0.4524)
Real           otherwise
```

τ was chosen on the same selection set to keep false alarms on genuine
photographs low: the requirement is at most 1 in 10. It sits below 0.5
because, at this weighting, a combined score of 0.45 is already rare for real
photographs.

## 5. Confidence

The percentage on the result page is **confidence in the verdict that was
given**. It is not the combined score: it measures how far the combined score
sits from the threshold τ, on the side of the verdict that was given.

- **50 %** means the combined score sat exactly on the threshold, a coin
  toss.
- The further the combined score is from τ (towards 1.0 for *AI Generated*,
  towards 0.0 for *Real*), the higher the confidence, up to **100 %** at the
  far end.
- A verdict therefore never shows less than 50 %. The figure is a distance
  from the threshold, not a measured probability.

The label next to it is a simple band of that number:

| Confidence | Label |
|---|---|
| ≥ 85 % | High |
| 65 % – 85 % | Moderate |
| < 65 % | Low |

## 6. A worked example

The hammer image (result #18), where the two detectors disagree:

| Step | Value |
|---|---|
| Content score (Community Forensics) | 0.265: looks real to it |
| Frequency score (SPAI) | 1.000 (rounded; the raw value is just under 1) |
| Combined | 0.55 × 0.265 + 0.45 × 1.000 = **0.596** |
| Verdict | 0.596 ≥ 0.4524 → **AI Generated** |
| Confidence | 0.596 is above 0.4524, but not far above → **63.1 %, Low** |

The low confidence is the honest reading of a split decision: one kind of
evidence says AI, the other does not.

And a photograph whose combined score is 0.30:

| Step | Value |
|---|---|
| Verdict | 0.30 < 0.4524 → **Real** |
| Confidence | 0.30 is below 0.4524 by about a third of the way to 0 → **66.8 %, Moderate** |

## 7. What the numbers do *not* mean

- **Confidence is not "the chance the verdict is right".** It is a distance
  from the threshold. The detectors' outputs are not calibrated (for the
  previous configuration they were measured off by 11 percentage points on
  average, against a target of 5; the current one has not been calibrated
  either). Read a high figure as "far past the threshold", not as an exact
  probability.
- **A detector can be wrong with full conviction.** A genuine sunflower
  photograph once scored 1.000 on the frequency detector.
- **Enhanced photos tend to look synthetic** to the frequency detector. This
  includes phone "AI enhancement", upscalers and beauty filters.
- **Resizing hurts the frequency detector badly; JPEG compression barely
  does.** Halving an image's size dropped SPAI's detection rate from 94 % to
  62 %. Upload originals, not shrunken copies.
- **Measured on two held-out tests, never used to choose any setting:**
  - **2025 generators** (AIGenImages2026: 559 generated images from 19
    generators, each paired with a real photo of similar content): accuracy
    0.798 [0.77, 0.82]; 63 % of the generated images caught; 3 % of the
    genuine photographs wrongly called AI.
  - **2022–23 generators** (Synthbuster: 99 generated images against 99
    camera originals): accuracy 0.939 [0.90, 0.96]; 95 % caught; 7 % of the
    genuine photographs wrongly called AI.

  Some 2025 generators still get through most of the time (FLUX.2 pro and max,
  GPT-image-1). Generators released after these tests are untested.

A result is a model's estimate, not proof.

## 8. Explainability panels (optional)

If *Include explainability panels* is ticked, two pictures are drawn **after**
the score is final. They never change it.

- **Content detector attention rollout:** where the content model's attention
  went, drawn inside the outlined centre square it actually analysed. It is an
  approximation of where the model looked, not a measurement of what caused
  the verdict.
- **SPAI patch spectrum:** the average frequency content of the patches SPAI
  analysed, with its low/high split marked. It is descriptive only.

---

Further detail:
- [ml/evaluation/RESULTS.md](../ml/evaluation/RESULTS.md): every measurement
  behind the figures above;
- [CLAUDE.md](../CLAUDE.md) §2 and §6: the models, and the confidence rule.
