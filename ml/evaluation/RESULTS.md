# Measurement record

Every number this project has produced, with what it does and does not
support. `CLAUDE.md` §6 carries the summary; this file carries the evidence.

Rule that governs all of it: **nothing here was ever used to fit anything.**
Thresholds, fusion weight and temperature are fixed constants in
`backend/app/shared/config.py` (CLAUDE.md §0). Where a figure suggests a
better operating point, that is recorded as a finding, not applied.

Tooling: `ml/evaluation/evaluate.py` runs any `<root>/0_real` + `<root>/1_fake`
set through the production path and reports per-branch and fused metrics with
95% intervals (Wilson for rates, bootstrap for AUC), plus per-generator
detection rates when the fake class is split into subfolders. Per-image CSVs
and summary JSON land in `ml/outputs/`.

---

### The displayed P(AI): fit and certainty band on validation, 2026-10-08

**What was fitted.** Two constants per map, a and b, in
P(AI) = sigmoid(a·logit(S) + b), with logit clipped at 1e-6. The output is shown capped
to [0.01, 0.99]. The maps were fitted on the validation split, 198 real and 198
generated images from scenes 99–296. They are disjoint from the test set. The inputs
were the per-image scores already on disk in `sbr_val_20261001T071305Z.csv`; S was
recomputed at w = 0.25 from the stored branch scores. No model weight was touched.

- Script: `ml/calibration/fit_calibration.py`.
- Output: `ml/outputs/calibration_fit_20261008T093111Z.json` and
  `reliability_val_20261008T093111Z.png`.
- AFTER figures come from 5-fold stratified cross-validated predictions (seed 20260907),
  so each image is scored by a map that did not see it. Intervals are 95 % stratified
  bootstraps; proportions use Wilson intervals.

| map | a | b | near-MLE a, b | separation warning |
|---|---|---|---|---|
| fused (S at w = 0.25) | 0.9294 | −0.2230 | 0.9373, −0.2264 | none |
| semantic-only (proxy) | 0.2292 | 0.0320 | 0.2296, 0.0321 | none |

**Fused score: the map is close to the identity and buys nothing measurable.**

| | raw S | P(AI), CV | CV − raw |
|---|---|---|---|
| Brier | 0.1003 [0.080, 0.121] | 0.1022 [0.082, 0.122] | +0.0019 [−0.0003, +0.0042] |
| log loss | 0.352 [0.284, 0.423] | 0.350 [0.291, 0.414] | −0.002 [−0.013, +0.009] |
| ECE, equal-count, 10 bins | 0.056 [0.039, 0.092] | 0.052 [0.041, 0.093] | |
| mean P − AI fraction | +0.026 [0.003, 0.049] | +0.000 [−0.023, +0.023] | |

- The only clear effect is calibration-in-the-large: raw S over-predicts AI by
  2.6 points on average, and the map removes that.
- The reliability curve is under-confident just above τ (bin mean S 0.76 → 82.5 % AI)
  and over-confident near the top (bin mean S 0.97 → 87 % AI). A single monotone
  sigmoid cannot correct both ends.
- **Honest wording:** the combined score at w = 0.25 is *approximately* calibrated on
  validation. P(AI) is a near-identity mapping of it, plus a cap.
- The 0.113 "ECE" quoted earlier in this file and in the docs is a different number:
  top-label ECE, equal-width bins, at w = 0.5. It does not describe what runs now.
- ECE at n = 396 has a noise floor of a few points. Brier and log loss are the primary
  measures.

**Semantic-only: the map matters.**

- CV Brier drops from 0.282 to 0.229 (difference −0.053 [−0.074, −0.032]).
- CV log loss drops from 0.934 to 0.650 (difference −0.285 [−0.384, −0.194]).
- ECE drops from 0.224 to 0.055.
- The map is very flat. P = 0.1 needs a semantic score of 6e-5, and P = 0.9 needs
  0.9999. No validation semantic score came that close (range 0.0032–0.9997), so
  coverage is 0/396 and in practice every semantic-only result is inconclusive.
- Every validation image is ≥ 256 px, so this is a **proxy** fitted on the semantic
  scores of full-size images. It is untested on the sub-224 px uploads it actually
  serves.
- Clip sensitivity: 0 of 396 semantic scores sit at the clip bound at eps = 1e-6,
  1e-9 or 1e-12, and a_sem and b_sem are identical at all three. The clip does not
  drive the fit.

**Sanity checks.**

- Both maps are monotonic increasing (a > 0).
- The fused map gives **P(AI | S = τ = 0.7558) = 0.696 [0.640, 0.766]**, so not below
  0.5. τ sits above even odds because it was pushed up to hold FPR ≤ 10 %.
- On the fused map, P = 0.1, 0.5 and 0.9 are reached at S = 0.107, 0.560 and 0.931.
- Consequence: Real verdicts with S in [0.560, 0.7558) display P(AI) > 0.5. That is
  36 of the 219 Real verdicts on validation. The UI words these as "leans AI, below
  the detection threshold".

**Certainty band, pre-registered at 0.90 before the fit was first run.** An image is
"confident" iff P(AI) ≥ 0.90 or ≤ 0.10. Figures below come from the CV predictions:

| | value |
|---|---|
| coverage (confident) | 0.452 [0.404, 0.501], 179 / 396 |
| τ-verdict accuracy, confident | **0.950 [0.907, 0.973]** |
| τ-verdict accuracy, inconclusive | 0.770 [0.709, 0.821] |

In-sample figures are 0.462 coverage and 0.951 accuracy. **The revised AC2 is met on
validation.** It requires τ-verdict accuracy within 'confident' ≥ 85 %, and both the
point estimate (0.950) and the Wilson lower bound (0.907) clear it. This is
in-distribution.

**Split by side** (CV), because the pooled figure hides an asymmetry:

| | n | τ-verdict right | accuracy | ≥ 0.85? |
|---|---|---|---|---|
| confident-AI (P ≥ 0.90) | 83 | 75 | 0.904 [0.821, 0.950] | point yes, **Wilson lower bound no** |
| confident-Real (P ≤ 0.10) | 96 | 95 | 0.990 [0.943, 0.998] | yes, both |

The 8 errors among confident-AI are genuine photographs that the system called AI
Generated with P(AI) ≥ 0.90. That is the confident end of the MM2.6 false-positive
problem. Pooled AC2 holds; on the AI side alone it is not established.

**"Leans AI, below threshold".** Of the 36 Real verdicts with in-sample P(AI) > 0.5,
22 are in fact AI (0.61 [0.45, 0.75]; with CV P(AI), 23 of 36). Their S range is
0.562–0.756. The "leans AI" wording is earned: these are mostly misses that τ lets
through to hold the FPR down.

**Semantic-only certainty is forced to "inconclusive".** The map's band edges are a
semantic score ≤ ~6e-5 or ≥ ~0.9999. Both lie outside the validated range 0.0032–0.9997,
so no accuracy figure exists for a "confident" semantic-only result. On validation the
map put 0 of 396 outside the band, and the τ-verdict on the semantic score alone was
right on 0.593.

**What the pilot can and cannot show.** The test set (scenes 0–98) and validation
(scenes 99–296) share no scene. Otherwise they come from the same population:

- the same nine generators, in equal numbers;
- the same RAISE camera originals, with the same sizes and therefore the same Nikon
  bodies;
- the same formats: PNG fakes, including RGBA from Glide, and TIFF reals.

The pilot is therefore a **held-out, same-distribution test, not a distribution-shift
test**. Its cropped-reals arm, where the reals are centre-cropped to 1024², is the only
arm that differs from validation.

---

### The displayed P(AI) on the held-out test set: frozen-map pilot, 2026-10-08 (run once)

**How it was run.**

- Pre-registered and committed before the run: `76a1448`, `ml/calibration/evaluate_calibration.py`.
- The map and band are the phase-1 constants, unchanged: a = 0.9294, b = −0.2230, band 0.90.
- Nothing was refitted, the band was not edited, and there was no second run.
- Offline: branch scores come from the stored test CSVs, S is recomputed at w = 0.25, and
  P(AI) comes from the backend `calibration.calibrated()`.
- Output: `ml/outputs/calibration_pilot_20261008T094223Z.json` and
  `reliability_pilot_20261008T094223Z.png`.
- This is a held-out, **same-distribution** test (see above), not a distribution-shift
  test. The semantic-only map is untestable here: every image is ≥ 256 px.

| | native (headline) | cropped reals (secondary) | validation, CV (for reference) |
|---|---|---|---|
| Brier | **0.088 [0.065, 0.114]** | 0.110 [0.083, 0.138] | 0.102 [0.082, 0.122] |
| log loss | **0.299 [0.231, 0.376]** | 0.356 [0.277, 0.441] | 0.350 [0.291, 0.414] |
| CITL (mean P − AI fraction) | **+0.005 [−0.027, +0.037]** | +0.028 [−0.007, +0.063] | +0.000 [−0.023, +0.023] |
| diagnostic slope (not applied) | 1.17 [0.90, 1.65] | 0.97 [0.76, 1.38] | — |
| diagnostic intercept (not applied) | −0.11 [−0.51, +0.28] | −0.24 [−0.64, +0.07] | — |
| ECE, equal-count (secondary) | 0.050 [0.035, 0.093] | 0.071 [0.048, 0.118] | 0.052 [0.041, 0.093] |
| P(AI) − raw S, Brier | −0.000 [−0.003, +0.003] | −0.003 [−0.007, +0.000] | +0.002 [−0.000, +0.004] |
| coverage (confident) | 0.495 [0.426, 0.564] | 0.505 [0.436, 0.574] | 0.452 [0.404, 0.501] |
| accuracy within confident | **0.980 [0.929, 0.994]** | 0.960 [0.902, 0.984] | 0.950 [0.907, 0.973] |
| — confident-AI | 0.955 [0.849, 0.987], 42/44 | 0.913 [0.797, 0.966], 42/46 | 0.904 [0.821, 0.950] |
| — confident-Real | 1.000 [0.934, 1.000], 54/54 | 1.000 [0.934, 1.000], 54/54 | 0.990 [0.943, 0.998] |
| accuracy, inconclusive | 0.750 [0.657, 0.825] | 0.755 [0.661, 0.830] | 0.770 [0.709, 0.821] |
| genuine photo shown confident-AI | 2 of 99 | 4 of 99 | 8 of 198 |

**Held out, nothing degraded.**

- Calibration on the test set is as good as on validation, or a little better. All
  intervals overlap, so this is the sampling noise of 99 images per class, not an
  improvement.
- The diagnostic slope's interval contains 1 and the intercept's contains 0, so no
  recalibration is indicated.
- The map again makes no measurable difference to Brier or log loss versus raw S. What it
  does fix is the average: CITL drops from +0.030 to +0.005.

**AC2, as pre-registered (pooled): met.** The τ-verdict is right on 0.980 [0.929, 0.994]
of confident results, against a target of ≥ 0.85.

**Limitation: the confident-AI side alone.** The 85 % target is met by the point
estimate but is **not established** at the Wilson-lower-bound level:

| set | confident-AI right | accuracy |
|---|---|---|
| validation (CV) | 75 / 83 | 0.904 [0.821, 0.950] |
| pilot | 42 / 44 | 0.955 [0.849, 0.987] |
| *both, pooled (exploratory, not pre-registered)* | *117 / 127* | *0.921 [0.861, 0.957]* |

- Every error on this side is a genuine photograph shown as AI Generated with
  P(AI) ≥ 0.90.
- Across both sets that happened to 10 of 297 genuine photographs:
  0.034 [0.018, 0.061].
- The 0.90 cutoff stays frozen. The pilot has now been seen, so any change to the band
  would need a fresh held-out set.

**Native vs cropped reals.** Cropping raised Brier by 0.022 and confident-AI false alarms
from 2 to 4. It was **not flagged by the pre-registered rule**: the CITL gap was 0.023
against a threshold of 0.05, and the unpaired Brier intervals overlap.

- *Descriptive supplement, added after the verdict and not changing it:* a paired
  bootstrap over the 198 scene-matched images (stratified, 2000 resamples, seed 20260907)
  puts the Brier difference, cropped minus native, at **+0.022 [+0.002, +0.043]**.
- With pairing the interval excludes zero, so the effect is small but probably real.
- The generated class is identical in both arms, so the difference comes entirely from
  the reals, and per-generator figures repeat.

**Per generator (n = 11 each, indicative only).** Mean P(AI) on the generated images is
lowest for DALL·E 3 (0.67, 6/11 detected) and highest for SD 1.4 (0.92). No generated
image was shown as confident-Real in either arm.

**What this does not show:**

- behaviour on post-2023 generators;
- behaviour on resized or otherwise processed images. Resizing takes SPAI's recall from
  0.939 to 0.616, so a low P(AI) on a resized image is not evidence that it is real;
- behaviour on any real-photo source other than RAISE's three Nikon bodies;
- behaviour on images under 224 px.

---

### Explainability: faithfulness and cost, 2026-10-03

**What the semantic map is.** It is an attention rollout of the SigLIP 2
classifier. The attention weights are recomputed from inputs captured during
the normal scoring pass; on a test image they match transformers' own eager
attention to within 1e-4, across all 12 layers and 12 heads. Rollout is
mean-pooled, because the classifier averages all 196 patch tokens and has no
CLS token. With capture on, the score is bit-identical:
`regression_check.py --xai` gives 24/24 identical, with 23 `generated` and
1 `partial` (the 128 px image has no frequency panel).

**Faithfulness (deletion sanity test)**, `ml/evaluation/xai_faithfulness.py`.
The protocol was fixed before running:
- **sample:** 40 images from the *validation* split (`sbr_val`, 20 real + 20
  generated);
- **masks**, each the same size (39 cells = 20% of the 14x14 grid):
  - top-attended cells;
  - 10 random cell sets per image;
  - bottom-attended cells;
- **fill:** every masked cell is filled with **that image's mean RGB colour**;
- **effect:** |change in SigLIP 2's P(AI)|.

**Headline: the gap over random.** Masking the top-attended 20% changes the
score more than masking random 20%:
- mean gap **+0.071, 95% bootstrap CI [0.041, 0.103]**;
- **median gap +0.019**. The distribution is skewed (sd 0.101), so a minority
  of images carries most of the effect, and for a typical image the
  advantage over random is small.

**Unit of analysis: one value per image, n = 40.** Each image's 10 random
draws are averaged *before* any test. Draws are never treated as
independent samples.

| test (top vs random, paired per image) | statistic | p |
|---|---|---|
| Wilcoxon signed-rank, exact, one-sided | W = 764 of 820 | 5.8e-8 |
| paired t-test, one-sided | t = 4.41, df = 39 | 4.0e-5 |
| sign test, one-sided | 35 of 40 positive | 6.9e-7 |

Why the Wilcoxon p is so much smaller than the t-test's: it is rank-based.
The 5 images where random beat top-k lost by tiny margins (|gap| 0.0001 to
0.015; ranks 1, 8, 12, 17, 18 of 40), so ranks favour top-k strongly, while
the magnitudes are noisy. The t-test is the more conservative figure.

For context, the mean |change| was 0.265 for top-k, 0.195 for random and
0.103 for bottom-k. The ordering top > random > bottom is what a faithful
map produces, but random masks alone already move the score a lot.

**What this supports, and no more.** Attention rollout is an
**attention-based proxy**, not a causal attribution. On these 40
validation images it ranks regions by the semantic branch's sensitivity to
them better than chance, with a small typical advantage. Limits:
1. The evidence covers **40 images and the semantic branch only**.
2. A mean-colour patch is an out-of-distribution edit.
3. The measure is the size of the change, not its direction.
4. The map says nothing about *where an image was manipulated*.
5. The **frequency panel is descriptive and has not been validated** as an
   explanation; no such test applies to it.

**What the panels look like (an observation on two images, not a finding).**
- **Semantic overlay:** on a Midjourney image, the strongest rollout cells
  sat in background corners and edges rather than on the objects. That is a
  known behaviour of ViTs, which park attention on low-content tokens. It is
  one more reason the caption claims "where the model looked" and never
  "where the image is fake".
- **Spectrum, Midjourney image:** a regular grid of isolated peaks (around
  ±56 and ±112 cycles/patch), the periodic pattern upsampling layers tend to
  leave.
- **Spectrum, camera crop:** smooth.
- **Both spectra:** a bright axis-aligned cross from the patch edges. SPAI
  applies no window before its FFT, so this is part of what SPAI sees, and
  the panel keeps it.
- **Display:** the colour range is clipped to the 1st–99.5th percentile.
  Unclipped, the DC peak made the panel almost black. The data is unchanged
  and the colourbar says so.

**The frequency panel** is not a map of evidence. It is the mean
log-magnitude spectrum of the 224x224 patches SPAI actually analyses, with
SPAI's r = 16 low/high split drawn. It is descriptive by construction, so
there is no faithfulness test for it.

**Cost**, `ml/evaluation/xai_cost.py`:
- RTX 4050 Laptop GPU, warm, 3 repeats, medians;
- through the real HTTP path (scratch SQLite);
- `wall` is the whole request; `xai` is `X-XAI-Time-Ms` (capture, spectrum,
  rendering and the D5 write); VRAM is the peak during the request.

| image | MP | SPAI patches | wall, xai off | wall, xai on | xai | peak VRAM off / on |
|---|---|---|---|---|---|---|
| DALL-E 2, 1024² | 1.0 | 16 | 0.56 s | 1.80 s | 1.23 s | 2148 / 2155 MB |
| Firefly, 1792x2304 | 4.1 | 80 | 2.64 s | 4.48 s | 2.10 s | 2273 / 2280 MB |
| RAISE JPEG, 4288x2848 | 12.2 | 228 | 6.86 s | 9.62 s | 3.11 s | 2535 / 2542 MB |
| RAISE JPEG, 3264x4928 | 16.1 | 308 | 9.26 s | 12.57 s | 3.68 s | 2672 / 2679 MB |
| RAISE JPEG, 3264x4928 | 16.1 | 308 | 9.22 s | 12.51 s | 3.56 s | 2672 / 2679 MB |

- **VRAM:** XAI adds **about 7 MB**; nothing new runs on the GPU.
- **Wall time:** it adds **1.2–3.7 s**. The table is from the re-run after
  the spectrum colour-clipping change (2026-10-03, `xai_cost_20261003T063052Z`);
  the run just before it gave 1.1–3.6 s, so the percentile clipping adds
  about 0.1 s.
- **Where the time goes:** at 16 MP, the SPAI-patch spectrum takes ~1.8 s
  (CPU FFT of 308 patches), rollout plus overlay ~1.2 s, and the spectrum
  panel ~0.6 s. Attention recomputation is under 50 ms.
- **PNG compression:** the first run used PNG `optimize=True`, which cost
  about 3 s of a 3.7 s overlay at 16 MP and doubled these figures (xai
  2.5–6.5 s). It was switched to the standard compression level, and the
  table is from the re-run.
- **Caveat:** these are three repeats on one laptop. They are cost
  indicators, not latency percentiles; Phase 7 measures those under load.

### Choosing the operating point, 2026-10-01 — a validation split

**Why a second split.** The 2026-09-30 benchmark (below) was run at
w = 0.5, τ = 0.5 and missed MM2.6 at FPR 0.162. Picking a better τ from that
same set would have turned the test set into a validation set and made every
later figure optimistic. So a **disjoint** split was built with the same
protocol — `fetch_synthbuster.py --per-model 22 --offset 99` takes scenes
99–296, the test set is scenes 0–98 — giving 198 images per class that share
nothing with it.

**Why this is not training.** CLAUDE.md §0 forbids updating model weights, and
none were touched. w and τ are configuration constants; PRD2 FR-03 describes
strategy A as "one weight, tuned on validation" and says τ "is selected on the
validation set to hold the false-positive rate on real photographs at or below
MM2.6". Step 4 had been closed as "fitting is training" — a ruling made when
no labelled data existed at all, and broader than it needed to be.

**Validation results at the old operating point** (w = 0.5, τ = 0.5):

| branch | accuracy | recall | FPR on real | AUC |
|---|---|---|---|---|
| SigLIP 2 | 0.631 [0.58, 0.68] | 0.596 | 0.333 | 0.672 [0.62, 0.72] |
| SPAI | 0.869 [0.83, 0.90] | 0.919 | 0.182 | 0.948 [0.93, 0.97] |
| fused | 0.879 [0.84, 0.91] | 0.929 | 0.172 | 0.908 [0.88, 0.94] |

Close enough to the test set (SPAI AUC 0.948 vs 0.967, FPR 0.182 vs 0.162)
that the two splits behave like samples from one population — which is what a
validation split has to be to be worth anything.

**What meeting MM2.6 costs, and why the weight mattered more than the
threshold.** Sweeping w and taking the smallest τ that holds FPR ≤ 0.10:

| w | τ | FPR | recall |
|---|---|---|---|
| 0.00 (frequency alone) | 0.945 | 0.096 | 0.843 |
| **0.25 — selected** | **0.7558** | **0.096** | **0.798** |
| 0.50 (the old value) | 0.667 | 0.096 | 0.596 |
| 0.75 | 0.764 | 0.096 | 0.439 |
| 1.00 (semantic alone) | 0.950 | 0.096 | 0.192 |

The equal-weight average was the binding constraint, not τ. SPAI is certain
(> 0.99) about 157 of the 198 validation fakes, but their mean SigLIP score is
only 0.577, so averaging drags those confident detections to ~0.79 — and a τ
high enough for MM2.6 cuts **52 of the 157**. The system was spending most of
its recall budget carrying a branch whose AUC is 0.67.

**w = 0.25 rather than 0** because the semantic branch still earns a place:
under degradation the fused score beats SPAI alone (see the arms below), so
some semantic weight buys robustness that w = 0 would throw away.

**Calibration (MM2.5) is not reachable this way.** ECE on validation is 0.113,
and the best temperature available, T = 0.97, only brings it to 0.110 against
a ≤ 0.05 target. Temperature scaling is a monotone squeeze of a score
distribution that is already bimodal; it cannot fix this. T stays at 1.0 and
MM2.5 stays missed, measured rather than assumed.

**The honest caveat.** Two constants were chosen on one 198/198 split, so they
carry its sampling noise. The test-set figures reported under "at the selected
operating point" below are the check on whether that generalised.

---

### Held out: the test set at the selected operating point, 2026-10-01

The check on whether w = 0.25 and τ = 0.7558, chosen on scenes 99–296,
generalise to scenes 0–98. Same 99 images per class as the original benchmark,
nothing re-selected.

| branch | accuracy | recall | FPR on real | AUC |
|---|---|---|---|---|
| SigLIP 2 | 0.672 [0.60, 0.73] | 0.475 | 0.131 | 0.728 [0.66, 0.80] |
| SPAI | 0.884 [0.83, 0.92] | 0.909 | 0.141 | **0.967 [0.95, 0.98]** |
| **fused** | 0.864 [0.81, 0.90] | 0.838 | **0.111 [0.06, 0.19]** | 0.941 [0.91, 0.97] |

**What moved, against the old w = 0.5 / τ = 0.5 point:**

| | old | new | |
|---|---|---|---|
| FPR on real | 0.162 | **0.111** | better — the goal |
| recall | 0.939 | 0.838 | worse — the price |
| fused AUC | 0.928 | **0.941** | better, and threshold-independent |
| accuracy | 0.889 | 0.864 | slightly worse |

**MM2.6 is still missed.** Validation said FPR 0.096; held out it is 0.111
against a ≤ 0.10 target. The interval [0.06, 0.19] covers 0.10, so the two are
not distinguishable at this sample size — which is the point: **two constants
were chosen on 198 images per class, and 1.5 points of optimism is what that
buys.** Pushing τ higher now would be fitting on the test set and is not done.

**What did generalise:** the fused AUC rose from 0.928 to 0.941. AUC does not
depend on τ, so that gain is attributable entirely to the better weight, and it
is the one result here that is not a threshold trade. The old equal-weight
average was spending recall to carry a branch with AUC 0.728.

**If MM2.6 has to be met**, the honest routes are a larger validation split
(the noise, not the method, is what failed), accepting the recall cost of a
higher τ, or a better semantic branch — not re-tuning against this table.

---

### The in-task evaluation, 2026-09-30 — Synthbuster vs RAISE-1k

The first measurement of the thing this system exists to do. AttGAN could not
provide it (out-of-scope task, network-processed "reals"); this set can.

**What it is.** 99 generated images — 11 from each of DALL·E 2, DALL·E 3,
Firefly, Glide, Midjourney v5, SD 1.3 / 1.4 / 2 / XL — against the 99
**camera-original RAISE-1k TIFFs of the same scenes**. Synthbuster's prompts
describe RAISE photographs and its filenames are RAISE ids, so every scene
appears once as a photograph and once as a generated image. Each generator was
given a disjoint slice of the scene list, so the 99 fakes span 99 distinct
scenes rather than 11 scenes nine times over. Build it with
`ml/datasets/fetch_synthbuster.py` + `fetch_raise.py`; see
`ml/datasets/README.md`.

**Primary result** (native resolution, at the **superseded** operating point
w = 0.5 / τ = 0.5 — the configuration in force when it was run; see the
section above for why it changed, and below for the same set at the selected
point). 95 % intervals — Wilson for rates, bootstrap for AUC:

| branch | accuracy | recall | FPR on real | AUC |
|---|---|---|---|---|
| SigLIP 2 | 0.646 [0.58, 0.71] | 0.616 | 0.323 | 0.728 [0.66, 0.80] |
| **SPAI** | 0.889 [0.84, 0.93] | 0.939 | 0.162 | **0.967 [0.95, 0.98]** |
| fused | 0.889 [0.84, 0.93] | 0.939 | 0.162 | 0.928 [0.89, 0.96] |

**The claim this supports, and no more:** *detection of whole-image synthesis
from 2022–23 generators versus pristine Nikon RAW-derived TIFFs, 99 images per
class.* It is **not** "the accuracy of the system". It says nothing about
newer generators (the "AI dog" miss above), about phone photographs, or about
images that have been through a learned enhancer (limitation 7).

**Six arms, all bit-identical on re-run** (the scoring path was re-verified
after M1/M3 landed mid-run: 198/198 scores reproduced exactly):

| arm | what changed | SigLIP 2 AUC | SPAI AUC | fused AUC | SPAI recall | SPAI FPR |
|---|---|---|---|---|---|---|
| **A native** | nothing | 0.728 | **0.967** | 0.928 | 0.939 | 0.162 |
| **B crop1024** | reals centre-cropped to 1024² | 0.791 | 0.936 | 0.923 | 0.939 | 0.293 |
| C resize1024 | reals downscaled to 1024² | 0.729 | 0.985 | 0.964 | 0.939 | 0.091 |
| jpeg90 | both classes re-encoded | 0.729 | 0.954 | 0.915 | 0.929 | 0.182 |
| jpeg75 | both classes re-encoded | 0.727 | 0.948 | 0.921 | 0.909 | 0.141 |
| **half** | both classes halved | 0.718 | 0.805 | **0.826** | **0.616** | 0.182 |

What the arms establish, in order of how much they matter:

1. **The confound control passes.** Reals are 4288×2848 TIFFs, fakes as small
   as 256²; a detector could in principle separate them on size alone. Arm B
   equalises resolution *and* SPAI's patch count, and costs only 0.031 AUC —
   inside the 0.05 band pre-registered before any image was scored. The
   headline number is not an artefact of resolution.
2. **Resizing is what breaks this detector; recompression is not.** JPEG q75
   on both classes costs 0.019 AUC. Halving both classes costs 0.162 AUC and
   takes SPAI's recall from 0.939 to 0.616 — more than a third of generated
   images become invisible. Limitation 5 was "unmeasured"; it is now measured,
   and the culprit is specifically **downscaling**.
3. **Fusion buys robustness, not peak accuracy.** On pristine images fusion is
   *worse* than SPAI alone (0.928 vs 0.967) and adds nothing at τ = 0.5, where
   SPAI's saturated 0/1 outputs dominate the average — accuracy, recall and FPR
   are identical to SPAI's. But under halving, fusion **beats** SPAI alone
   (0.826 vs 0.805). That reversal is the argument for leaving w = 0.5 alone:
   tuning it toward SPAI would buy 0.04 AUC on pristine data and lose the
   degraded case. **No weight was changed on the strength of these numbers**
   (§0). *(Later: w did move to 0.25 — but chosen on a separate validation
   split, not on this table. See the section above.)*
4. **MM2.6 is missed.** 0.162 [0.10, 0.25] against a ≤ 0.10 target. Sixteen
   genuine photographs called AI Generated. Raising τ would trade recall for
   this, but choosing τ from this set is fitting on the test set and was not
   done. *(Later: τ was chosen on a validation split instead, bringing this to
   0.111 — still short. See above.)*
5. **Arm C is not a control and must not be read as one.** It downscales only
   the reals, so it never tested "does low-passing destroy the evidence". What
   it shows is that SPAI's false positives on camera originals are driven by
   high-frequency content that survives at native resolution — sensor noise,
   demosaicing, in-camera sharpening. Low-pass the photographs and FPR falls to
   0.091; recall on the untouched fakes is unchanged. The prediction registered
   for this arm ("large SPAI drop") was **wrong because the arm was badly
   designed**, and it is recorded here rather than quietly dropped.

**Per-generator detection rate** (n = 11 each — indicative only; the intervals
are ±0.3 wide and no per-generator claim should be made from them):

| generator | image sizes | SigLIP 2 | SPAI | fused |
|---|---|---|---|---|
| dalle2 | 1024² | 0.818 | 0.909 | 0.909 |
| dalle3 | 1024², 1792×1024, RGBA | 0.727 | 0.818 | 0.818 |
| firefly | 1792×2304 … 2688×1536 | 0.545 | 1.000 | 0.909 |
| glide | **256²** | 0.818 | 0.818 | 0.909 |
| midjourney-v5 | 1344×896, 896×1344 | 0.455 | 1.000 | 1.000 |
| stable-diffusion-1-3 | 512² | 0.636 | 1.000 | 1.000 |
| stable-diffusion-1-4 | 512² | 0.909 | 1.000 | 1.000 |
| stable-diffusion-2 | ten aspect ratios | **0.182** | 1.000 | 1.000 |
| stable-diffusion-xl | ten aspect ratios | 0.455 | 0.909 | 0.909 |

Two things this table surfaced that were not expected:

- **The generated class is wildly heterogeneous** — 256² to 2688×1536, ten
  aspect ratios within a single generator, and DALL·E 3 carrying an alpha
  channel. Asserting sizes in the fetch script (rather than assuming 1024²)
  is what caught this. Glide's 256² images sit in SPAI's five-crop fallback
  rather than its sliding-window regime, so they are seen differently from
  every other generator.
- **The registered prediction that SigLIP 2 would be weakest on the newest
  generators was wrong.** Its worst result is Stable Diffusion 2 (0.182) and
  its best is SD 1.4 (0.909) — both 2022-era. There is no "newer is harder"
  pattern in this data.

**A defect this surfaced, since fixed (see `changes.md` §3.0).** SPAI raises `RuntimeError` on any image with a
side under 224 px (verified: 223² fails, 224² works, 200×400 fails), which
`pipeline.py`'s broad catch turns into `INF_FAILED` → **HTTP 500**. M1's caps
guard the maximum (10 MB, 25 MP); nothing guards the minimum, so a thumbnail
or avatar upload returns a server error rather than a verdict. Fixed the way Contract C2
already allowed: the branch raises `SpectralBranchUnavailable`, the pipeline
records `frequency_score = None`, and fusion degrades to the documented
passthrough. D4's column and M3's schema and PDF were made null-tolerant.

---

### Smoke test, 2026-09-12 (SigLIP 2 + SPAI, native resolution) — not a benchmark

Same 14 Wikimedia Commons images as on 2026-09-07: 7 camera photographs, 7
documented as Stable-Diffusion-generated. Scores are P(AI).

| image | truth | SigLIP 2 | SPAI | fused | verdict |
|---|---|---|---|---|---|
| A man having an idea (3072²) | AI | 0.603 | 1.000 | 0.801 | AI ✓ |
| AI artwork of mountains (1536×1056) | AI | 0.987 | 1.000 | 0.994 | AI ✓ |
| AI golem (3072²) | AI | 0.373 | 1.000 | 0.686 | AI ✓ |
| Futuristic city in destruction (8192×4096) | AI | 0.627 | 0.846 | 0.736 | AI ✓ |
| Elbish city on an exoplanet (6144²) | AI | 0.492 | 1.000 | 0.746 | AI ✓ |
| Burned city (3072²) | AI | 0.995 | 1.000 | 0.998 | AI ✓ |
| Cyborg elf (1024²) | AI | 0.997 | 1.000 | 0.999 | AI ✓ |
| Cat, November 2010 (1795×2397) | Real | 0.032 | 0.000 | 0.016 | Real ✓ |
| Common kingfisher (2000²) | Real | 0.882 | 0.006 | 0.444 | Real ✓ |
| Cat on snow (3000×2000) | Real | 0.085 | 0.000 | 0.042 | Real ✓ |
| Golden Gate Bridge (1600×1029) | Real | 0.928 | 0.000 | 0.464 | Real ✓ |
| Sunflower from Silesia (2434×1697) | Real | 0.789 | **1.000** | 0.894 | **AI ✗** |
| Tour Eiffel (2900×5367) | Real | 0.208 | 0.001 | 0.104 | Real ✓ |
| Zebra, Botswana (1234×1168) | Real | 0.043 | 0.017 | 0.030 | Real ✓ |

**13/14 fused. SPAI alone 13/14; SigLIP 2 alone 9/14.** SPAI's mean on the
generated images is 0.978 (min 0.846) and on the photographs 0.146 — the
sign-convention canary passes with a wide margin.

**Fourteen images is not a measurement.** It is a smoke test showing the
branches respond to content rather than emitting noise. Do not quote 13/14 as
an accuracy figure — it has no confidence interval and the sample was chosen
by hand.

What it surfaced, honestly:

- **The frequency branch rescued three SigLIP 2 false positives** — the
  kingfisher (0.882 → fused 0.444), the Golden Gate Bridge (0.928 → 0.464)
  and the Eiffel Tower, which the previous second branch had got wrong.
  Two of those rescues are narrow (0.444, 0.464): a slightly stronger
  semantic false positive would have carried the verdict.
- **It also rescued two SigLIP 2 misses** on generated images (0.373 and
  0.492 → fused 0.686 and 0.746).
- **False positives remain the live risk.** The sunflower photograph is a
  confident SPAI false positive (1.000) that fusion could not save; it was
  a SigLIP 2 false positive on 2026-09-07 too. Same image, both kinds of
  evidence wrong. MM2.6 (FPR ≤ 0.10) is untested and, on this sample, not
  obviously met.
- **SPAI saturates** at 0.000 / 1.000 on 11 of 14 images, like the previous
  second branch did. Its output is not calibrated and must not be read as
  a probability.
- **Resolution matters to this branch.** Capping the longest side changes
  verdicts (see §4): at 512 px two generated images drop to ~0 and a
  photograph rises to 0.98. Whatever is shown to users must say what
  resolution the verdict was computed at.

---

### A miss outside the smoke set, 2026-09-12 — a modern-generator image

A user-supplied, obviously generated image (a stylised "AI dog", 447×447 JPEG
q≈72, no EXIF — a web thumbnail) came back **Real**: SigLIP 2 0.922, SPAI
3×10⁻²⁴, fused 0.461. Diagnosis, with the alternatives ruled out:

- Not the wiring: sign convention and pipeline verified by the canary above.
- Not the size or compression: a known SD image downscaled to 447 px and
  re-encoded at q72 still scores 0.999 on SPAI; the dog saved losslessly
  still scores 3×10⁻²⁴.
- What is left is the generator. SPAI learned the spectral fingerprint of
  Latent Diffusion; this image is from a newer, heavily stylised pipeline
  (Midjourney/Flux/DALL·E 3 class, probably upscaled) whose fingerprint it
  evidently does not know. Limitation 2 below, made concrete.

The fusion consequence is the mirror of the sunflower: an unweighted average
lets one **saturated** wrong branch veto a strong right one. Re-weighting on
the strength of a single image would be fitting (§0) and would merely move
the failure to the sunflower case. The correct response is a batch of images
from the generators that matter to the project, through both branches — Step 7.

---

### First labelled evaluation, 2026-09-12 — AttGAN (4,000 images): at chance, and why

Tool: `ml/evaluation/evaluate.py` (reads weights, reports numbers, changes
nothing; per-image CSV + summary JSON under `ml/outputs/`). Set: 2,000 real /
2,000 fake, 256×256 CelebA-HQ faces, fakes = AttGAN attribute edits.

| branch | acc | recall | **FPR on "real"** | AUC | best-threshold acc (info only) |
|---|---|---|---|---|---|
| SigLIP 2 | 0.398 | 0.500 | 0.704 | 0.361 | 0.500 |
| SPAI | 0.503 | 0.957 | **0.951** | 0.445 | 0.510 |
| fused | 0.498 | 0.949 | 0.953 | 0.368 | 0.503 |

SPAI scores ≥ 0.99 on 88 % of the "real" faces and 85 % of the fakes — one
population. SigLIP 2 scores the unedited faces slightly *higher* than the
edited ones. No threshold separates them.

Reading, in order of importance:

1. **This is an out-of-scope task, measured.** Localised edit detection is
   excluded by PRD2 §1.5 / SRS §1.2. AttGAN is exactly that. Whole-image
   detectors cannot do it; now there is a number saying so.
2. **The "real" class is not camera output.** CelebA-HQ was made by running
   CelebA through a trained super-resolution network. Probe: genuine
   photographs downscaled to 256 px still score 0.000 on SPAI (five-crop
   regime is unbiased), so SPAI's 0.95 here is about these images, and is
   arguably correct.
3. **Deployment lesson (add to limitations):** real photographs that have
   been through a learned enhancer — phone "AI" camera pipelines, upscalers,
   beautify filters — will likely be called AI by the frequency branch. This
   is the most probable real-world form of the MM2.6 false-positive risk.

Do not quote these numbers as the system's accuracy for its actual task. A
set with camera originals as the real class and whole generated images as
the fake class (e.g. Synthbuster + RAISE) is what Step 7 needs.

Previous smoke test (2026-09-07, SigLIP 2 + SwinV2): 12/14, with SwinV2
rescuing two SigLIP 2 false positives and causing one of its own (Eiffel
Tower, 0.989). Kept in git history; superseded by the table above.
