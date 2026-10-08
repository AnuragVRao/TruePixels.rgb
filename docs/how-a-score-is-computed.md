# How a score is computed

What happens between a user choosing an image and the result page showing
"AI Generated, 99.7 %". Every number below is what the code does today; the
constants live in [backend/app/shared/config.py](../backend/app/shared/config.py).

```
upload ──► validate & store ──► semantic detector (SigLIP 2) ──┐
                           └──► frequency detector (SPAI) ─────┤
                                                               ▼
                                        combined score = 0.25·semantic + 0.75·frequency
                                                               ▼
                                        verdict: AI Generated if combined ≥ 0.7558
                                                               ▼
                                        confidence: distance from 0.7558, shown as 50–100 %
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

The original file is stored exactly as uploaded. Both detectors read this
original, not a resized copy, and each applies its own preprocessing.

## 2. Two detectors, two kinds of evidence

`POST /api/v1/predictions` ([m2_analysis/pipeline.py](../backend/app/m2_analysis/pipeline.py)).
Both models are published, pretrained checkpoints, used exactly as released;
this project never trains or fine-tunes a model.

**Why two:** a generator that fools one kind of evidence has no particular
reason to also fool the other.

### Semantic detector: SigLIP 2 (`prithivMLmods/AIorNot-SigLIP2`)

Looks at **what the picture shows**: textures, lighting, the "too clean" look
of generated images.

1. The image is converted to RGB and resized to **224 × 224** by the model's own
   preprocessor.
2. The network outputs two numbers, one for *Real* and one for *AI*.
3. A softmax turns them into probabilities that add up to 1.
4. **Semantic score = the probability of "AI"**.

Which output means "AI" is read from the checkpoint's own label map
(`{0: "Real", 1: "AI"}`), never assumed. Checkpoints disagree on this, and
guessing wrong would silently invert every result.

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
and the verdict rests on the semantic detector alone; the result page says so.

## 3. The combined score

```
combined = 0.25 × semantic + 0.75 × frequency
```

([m2_analysis/fusion.py](../backend/app/m2_analysis/fusion.py), `combine`)

- **The weights:** the frequency detector gets three times the weight because
  it was clearly stronger in testing (AUC 0.967 vs 0.728).
- **How w = 0.25 was chosen:** on a validation set of 198 real and 198
  generated images, kept separate from the test set.
- **No model was changed:** the weight is a setting; the models are unchanged.
- **One detector only:** without a frequency score, the combined score is
  simply the semantic score.

All three of these numbers (semantic, frequency, combined) mean the same thing:
**the probability, as the model sees it, that the image is AI-generated**.

## 4. The verdict

```
AI Generated   if combined ≥ τ      (τ = 0.7558)
Real           otherwise
```

τ is set above 0.5 deliberately. It was chosen on the same validation set to
keep false alarms on genuine photographs low: the requirement is at most
1 in 10.

## 5. Confidence

The percentage on the result page is **confidence in the verdict that was
given**. It is not the combined score:

```
AI Generated:  confidence = 0.5 + 0.5 × (combined − τ) / (1 − τ)
Real:          confidence = 0.5 + 0.5 × (τ − combined) / τ
```

- **50 %** means the combined score sat exactly on the threshold, a coin
  toss.
- **100 %** means it was at the far end: combined = 1.0 for *AI Generated*,
  or 0.0 for *Real*.
- A verdict therefore never shows less than 50 %.

The label next to it is a simple band of that number:

| Confidence | Label |
|---|---|
| ≥ 85 % | High |
| 65 % – 85 % | Moderate |
| < 65 % | Low |

## 6. A worked example

The hammer image (result #18):

| Step | Value |
|---|---|
| Semantic score (SigLIP 2) | 0.994 |
| Frequency score (SPAI) | 1.000 (rounded; the raw value is just under 1) |
| Combined | 0.25 × 0.994 + 0.75 × 1.000 = **0.9985** |
| Verdict | 0.9985 ≥ 0.7558 → **AI Generated** |
| Confidence | 0.5 + 0.5 × (0.9985 − 0.7558) / (1 − 0.7558) = **0.997 → 99.7 %, High** |

And a photograph whose combined score is 0.52:

| Step | Value |
|---|---|
| Verdict | 0.52 < 0.7558 → **Real** |
| Confidence | 0.5 + 0.5 × (0.7558 − 0.52) / 0.7558 = **0.656 → 65.6 %, Moderate** |

## 7. What the numbers do *not* mean

- **Confidence is not "the chance the verdict is right".** It is a distance
  from the threshold. The detectors' outputs are not calibrated: on validation
  their scores were off by 11 percentage points on average, against a target
  of 5. Read 99.7 % as "far past the threshold", not as an exact probability.
- **A detector can be wrong with full conviction.** A genuine sunflower
  photograph once scored 1.000 on the frequency detector.
- **Enhanced photos tend to look synthetic** to the frequency detector. This
  includes phone "AI enhancement", upscalers and beauty filters.
- **Resizing hurts detection badly; JPEG compression barely does.** Halving an
  image's size dropped SPAI's detection rate from 94 % to 62 %.
- **Measured on one test, so far:** 99 generated images (2022–23 generators)
  against 99 camera originals. On that set:
  - overall accuracy was 0.864 [0.81, 0.90];
  - 11 % of the genuine photographs were wrongly called AI.

  Newer generators have not been tested.

A result is a model's estimate, not proof.

## 8. Explainability panels (optional)

If *Include explainability panels* is ticked, two pictures are drawn **after**
the score is final. They never change it.

- **SigLIP 2 attention rollout:** where the semantic model's attention went.
  It is an approximation of where the model looked, not a measurement of what
  caused the verdict.
- **SPAI patch spectrum:** the average frequency content of the patches SPAI
  analysed, with its low/high split marked. It is descriptive only.

---

Further detail:
- [ml/evaluation/RESULTS.md](../ml/evaluation/RESULTS.md): every measurement
  behind the figures above;
- [CLAUDE.md](../CLAUDE.md) §2 and §7: the models, and the confidence formula.
