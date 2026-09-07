**PRODUCT REQUIREMENTS DOCUMENT**

**PRD 2 — Image Analysis & Prediction (M2)**

*for TruePixels.rgb — An AI-Generated Image Detection System*

| **Field**         | **Value**                                                                       |
|-------------------|---------------------------------------------------------------------------------|
| Module / Division | M2 — Image Analysis & Prediction (Structured Chart, Figure 10; DFD process 0.4) |
| Owner             | Anurag V Rao (241IT011)                                                         |
| Team              | Amogh R Gowda (241IT008) · Anurag V Rao (241IT011) · Debanshu Mitra (241IT019)  |
| Version           | 1.0                                                                             |
| Date              | 7 September 2026                                                                |

**Parent documents:**

- SRS for TruePixels.rgb (IEEE 830-1998), v1.1

- Design Document using SA/SD Methodology for TruePixels.rgb — DFD Model, Data Dictionary and Structured Chart

- TruePixels.rgb — Module Interface Contract, v1.0 (defines Contracts C1, C2, C4, C5 referenced throughout)

Department of Information Technology

National Institute of Technology Karnataka, Surathkal

# **Table of Contents**

# **1. Component Overview**

| **Field**                 | **Value**                        |
|---------------------------|----------------------------------|
| Component name            | M2 — Image Analysis & Prediction |
| SRS requirements realised | F.8, F.9, F.12, F.19             |
| DFD processes realised    | 0.4 (0.4.1–0.4.4)                |
| Data stores owned         | D3. Models, D4. Predictions      |

## **1.1 Purpose**

M2 is the detector. Given a preprocessed image it produces a class label, a confidence score and a persisted prediction record, by running two independent classifiers and combining their outputs. It also owns the model registry, because the meaning of "which model produced this prediction" is an inference concern.

The two branches deliberately look at different things. The CLIP branch asks a semantic question — does this scene hold together the way photographs of the world hold together? The frequency branch asks a physical question — does this pixel grid carry the spectral fingerprint of a synthesis pipeline? They fail in different circumstances, and that is the entire argument for fusing them: a generator that defeats one has no particular reason to have defeated the other.

Analogy: a document examiner working with a handwriting expert. One reads the content and asks whether the story is plausible; the other ignores content entirely and looks at ink, paper fibre and pen pressure. A good forger usually beats one of them. Beating both at once is a much harder problem, and the fusion module is where the two opinions are reconciled into a single verdict.

## **1.2 Role in the overall project**

    M1 --- PreprocessedImage (tensor + native original) ----> M2
                                                                |
    +----------------------------------------------------------+
    | M2 Image Analysis & Prediction                             |
    | 2.1 Semantic Analysis (CLIP)      -> semantic_score          |
    | 2.2 Frequency Artifact Analysis   -> frequency_score        |
    | 2.3 Decision Fusion & Prediction  -> fusion_score            |
    | 2.4 Model Registry (F.19)                                    |
    +----------------------------------------------------------+
         |              |               |
         v              v               v
     D3. Models   D4. Predictions   InferenceOutput --> M3

## **1.3 Problem it solves**

A single classifier trained on one kind of evidence has one kind of blind spot. M2 exists to combine two independent forms of evidence — learned visual semantics and physical frequency-domain fingerprints — into one calibrated, traceable verdict, and to make sure the model configuration that produced any given verdict is always identifiable later.

## **1.4 Responsibilities**

- Semantic feature extraction with a CLIP image encoder and a classification head over its embedding (FR-01).

- Frequency-domain artifact analysis on the native-resolution image and a classifier over the resulting spectral features (FR-02).

- Decision fusion producing a single score, a class label and a calibrated confidence (FR-03, FR-04).

- Persistence of the prediction record with its image, model and timestamp linkage (FR-05).

- The model registry: registration, versioning, artefact validation and atomic activation (FR-06, FR-07).

- Exposing the internal model state that M3 needs for explainability, under Contract C2.

- Model evaluation against NF.3 and honest reporting of those figures (§13.5).

## **1.5 What this component does NOT handle**

- Any file handling, format validation or preprocessing — M1. M2 assumes the tensor is correct and does not defensively re-derive it.

- Generating the explainability visualisation — M3. M2 supplies the raw material (ActivationBundle); M3 renders it.

- The administrator screens for model management — M3. M2 provides the endpoints only.

- Identifying which generative model produced an image, localised edit detection, and video analysis — explicitly excluded by SRS §1.2 and C.7.

- Training-data collection and labelling as a product feature. Training happens offline; only the resulting artefacts enter the running system.

# **2. Scope**

## **2.1 In Scope**

- FR-01 Semantic feature extraction with a CLIP image encoder and a trainable classification head.

- FR-02 Frequency-domain artifact analysis on the native-resolution original.

- FR-03 / FR-04 Decision fusion producing a single score, class label and calibrated confidence.

- FR-05 Persistence of the prediction record with image, model and timestamp linkage.

- FR-06 / FR-07 The model registry — registration, versioning, artefact validation and atomic activation.

- Exposing sufficient internal model state (ActivationBundle) for M3's explainability, per Contract C2.

- Model evaluation against NF.3 and reporting of accuracy, calibration and robustness figures.

## **2.2 Out of Scope**

- File handling, format validation, EXIF handling and tensor preparation — M1 (F.5, F.6, F.7).

- Rendering the explainability visualisation, results view, history, PDF reports — M3 (F.10, F.11, F.13, F.14).

- The administrator UI for model management — M3 renders it; M2 only implements the endpoints it calls.

- Generator attribution, localised edit detection, video/multimedia analysis — explicitly out of scope per SRS §1.2 and constraint C.7.

- Training-data collection and labelling as a runtime feature — training happens offline in a separate, non-deployed tree.

## **2.3 Future Scope**

- Real-time video or streaming inference — explicit non-goal.

- A third detection branch, addable by implementing one scoring interface and one fusion entry without touching M1 or M3 (supports NF.10/NF.12 extensibility).

- A CNN over the 2-D log-spectrum for the frequency branch — highest capacity, highest overfitting risk on a small dataset; deferred as an NF.12 extension.

- Gradient-boosted trees as an alternative frequency-branch classifier — worth an ablation, deferred because it adds a second runtime and complicates the D3 artefact format.

- On-line or continual learning from user submissions — model updates remain deliberate, versioned, administrator-initiated events (FR-06/FR-07) by design.

# **3. Functional Requirements**

### **FR-01 — Semantic Analysis — CLIP branch (realises part of F.8, DFD 0.4.1)**

| **Aspect**          | **Specification**                                                                                                                                                                                                                                                                                                                                        |
|---------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input               | PreprocessedImage.tensor_ref (3, 224, 224 float32 tensor) from Contract C1.                                                                                                                                                                                                                                                                              |
| Processing          | CLIP ViT-B/32 image encoder (Hugging Face Transformers), weights frozen, producing a 512-d pooled embedding. A small trainable head: Linear(512→256) → GELU → Dropout(0.2) → Linear(256→1) → sigmoid. Inference under model.eval() and torch.no_grad(), except when activations are requested (gradients enabled for the head only).                     |
| Output              | semantic_score = P(AI Generated) in \[0,1\].                                                                                                                                                                                                                                                                                                             |
| Constraints         | The backbone is frozen — training only the head — so the representation stays a general-purpose visual embedding rather than one specialised to the training set's specific generators (see §8.1 for the full rationale).                                                                                                                                |
| Contract dependency | The tensor from M1 must match CLIP's expected preprocessing exactly. A mismatch does not raise; it silently shifts the embedding off-distribution. The joint C1 contract test (owned jointly with M1) asserts agreement with the reference CLIPProcessor output to within 1e-5 and must be green before any accuracy figure from this branch is trusted. |

**\[DECISION REQUIRED\]** Backbone selection (source PRD item M2-A): ViT-B/32 versus ViT-L/14 (768-d embedding). ViT-L/14 is the documented fallback if ViT-B/32 underperforms and the latency budget (MM2.7/MM2.8) allows. Resolve during milestone M2.1 by measuring accuracy against latency.

### **FR-02 — Frequency Artifact Analysis (realises part of F.8, DFD 0.4.2)**

| **Aspect**        | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
|-------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input             | PreprocessedImage.source_reference — the native-resolution original. Never the resized 224×224 tensor: Contract C1 §4.3 makes this binding, since a bicubic downsample already erases the high-frequency evidence this branch looks for.                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Processing        | 1\) Convert to single-channel luminance. 2) Centre-crop to a fixed square at native resolution (e.g. 512×512), padding by reflection when the image is smaller — a fixed size is required because spectra of different-sized images are not comparable. 3) Optional high-pass residual (light Gaussian blur subtraction) to suppress scene content. 4) Apply a 2-D Hann window (see §8.2 — not optional). 5) 2-D FFT, fftshift, log(1 + \|F\|). 6) Azimuthal average to a 1-D radial power spectrum of N=128 bins. 7) Additional scalar features: high-frequency energy ratio; peak count and prominence in the radial profile; DCT block-boundary energy. 8) Classifier over the feature vector. |
| Output            | frequency_score = P(AI Generated) in \[0,1\].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Classifier choice | A small MLP over the 128-bin radial profile plus scalars is the primary implementation (trains in seconds, few parameters, shares the PyTorch runtime with the CLIP head). Gradient-boosted trees are a documented ablation option; a CNN over the 2-D log-spectrum is deferred (see §2.3 Future Scope).                                                                                                                                                                                                                                                                                                                                                                                          |

**\[DECISION REQUIRED\]** Frequency branch input geometry (source PRD open issue OI-5): whether the branch operates on the full native image or a fixed centre crop, and at what size. Affects comparability of spectra across images. Resolve by checkpoint I2.

**\[DECISION REQUIRED\]** Whether the frequency branch should operate per colour channel rather than on luminance (source PRD item M2-C). Resolve by ablation during milestone M2.2, not by argument.

### **FR-03 — Decision Fusion (realises part of F.8, DFD 0.4.3)**

| **Aspect**              | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                     |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input                   | semantic_score, frequency_score.                                                                                                                                                                                                                                                                                                                                                                                      |
| Processing — strategy A | Weighted average: fusion = w·semantic + (1−w)·frequency. One weight, tuned on validation. Trivial to explain; cannot overfit; assumes both scores are on comparable scales, which uncalibrated sigmoid outputs are not.                                                                                                                                                                                               |
| Processing — strategy B | Logistic meta-classifier: fusion = σ(β₀ + β₁·semantic + β₂·frequency). Three coefficients fit on a held-out validation split (never on training-set predictions, which would leak and inflate every downstream number). Learns the relative reliability of each branch.                                                                                                                                               |
| Output                  | fusion_score ∈ \[0,1\] — the probability of "AI Generated" after fusion.                                                                                                                                                                                                                                                                                                                                              |
| Decision threshold      | τ converts fusion_score into a label. τ = 0.5 is not used by default, because the two error types are not equally costly: telling a journalist a genuine photograph is AI-generated is more damaging than missing a synthetic one. τ is selected on the validation set to hold the false-positive rate on real photographs at or below MM2.6, and is stored in the fusion configuration in D3 rather than hard-coded. |

**\[DECISION REQUIRED\]** Fusion strategy A or B (source PRD open issue OI-1). Determines whether D3 stores a single float or a serialised model. Recommended approach: implement A first so the end-to-end path closes early, then evaluate B against it and keep whichever wins on the held-out generator split (MM2.2), not the in-distribution split. Decision due at checkpoint I2.

### **FR-04 — Generate Prediction and Confidence (realises F.9, DFD 0.4.4)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                      |
|-------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | fusion_score, τ.                                                                                                                                                                                                                                                                                                                       |
| Processing  | predicted_class = "AI Generated" if fusion_score ≥ τ else "Real". confidence_score = fusion_score if predicted_class == "AI Generated", else 1.0 − fusion_score.                                                                                                                                                                       |
| Output      | predicted_class ∈ {"Real", "AI Generated"} (binary only — constraint C.2); confidence_score ∈ \[0,1\].                                                                                                                                                                                                                                 |
| Calibration | Raw sigmoid outputs are not probabilities and are typically overconfident. Temperature scaling — one scalar fitted on the validation split after training — is applied at inference, and expected calibration error is reported as MM2.5.                                                                                              |
| Constraints | This inversion is the single most likely integration bug in the whole project: it fails quietly and plausibly (a confidently-real image would show as, e.g., 8% confident, which looks like a weak model rather than a wiring error). It is fixed by Contract C2 §5.2 and asserted by a contract test that M3 also runs independently. |

### **FR-05 — Prediction Storage (realises F.12)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                                  |
|-------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | predicted_class, confidence_score, semantic_score, frequency_score, fusion_score, active model IDs, latency_ms.                                                                                                                                                                                                                                                                                                                    |
| Processing  | One D4 row per inference, written and committed before the response is returned, so prediction_id is a valid foreign key the instant M3 receives InferenceOutput. model_id references the fusion configuration row active at the moment of inference (not the one active at read time); individual branch model IDs are recorded in a JSONB column so a prediction remains fully reconstructible after any artefact is superseded. |
| Output      | A committed D4 row and its prediction_id.                                                                                                                                                                                                                                                                                                                                                                                          |
| Constraints | If persistence fails, the request fails — a prediction shown to a user but absent from history is worse than an error. M2 never writes D5 (Explainability) and never reads D6 (Logs); both belong to M3.                                                                                                                                                                                                                           |

### **FR-06 — Model Registry — Register (realises part of F.19, DFD 0.7.4 M2 side)**

| **Aspect** | **Specification**                                                                                                                                                                                                                                                          |
|------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input      | Model artefact (multipart upload); metadata (name, version, model_type, training reference).                                                                                                                                                                               |
| Processing | Persist the artefact to the model store, load it, run one forward pass on a fixed canary tensor, assert the output shape and range — only then insert the D3 row. A bad artefact must fail here, in front of the administrator uploading it, not later in front of a user. |
| Output     | A registered D3 row (model_id) and confirmation, or a rejection before commit.                                                                                                                                                                                             |
| Errors     | 422 on a failed canary pass; AUTH_FORBIDDEN for a non-admin caller.                                                                                                                                                                                                        |

### **FR-07 — Model Registry — List / Activate / Resolve Active (realises part of F.19)**

| **Aspect**                  | **Specification**                                                                                                                                                                                                                                     |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input                       | Admin session; for activation, a target model_id.                                                                                                                                                                                                     |
| Processing — activate       | Single transaction: deactivate the current active row of the same model_type, activate the target. Enforced additionally by a partial unique index (uq_models_one_active_per_type) so concurrent activations cannot both succeed.                     |
| Processing — resolve active | Returns the active semantic, frequency and fusion configuration. Cached in-process with an invalidation hook on activation, since re-reading three rows on every inference is wasteful and a stale cache after activation would be a correctness bug. |
| Output                      | List: all versions with type, version, active flag, registration timestamp. Activate: the newly active set. Resolve: the currently active configuration.                                                                                              |
| Constraints                 | At most one row per model_type may have is_active = true, enforced by the database, not application code.                                                                                                                                             |

# **4. Technical Requirements**

| **Category**                 | **Requirement**                                                                                                                                       |
|------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Language / runtime           | Python 3.11; inference must remain viable on CPU (SRS §3.2.2), a GPU is used only where available.                                                    |
| ML framework                 | PyTorch 2.x; Hugging Face Transformers for the CLIP backbone.                                                                                         |
| Supporting libraries         | NumPy; SciPy or OpenCV for the FFT path; scikit-learn for calibration and baseline classifiers.                                                       |
| Database                     | PostgreSQL 15 (shared instance; D3 and D4 owned by M2).                                                                                               |
| Hardware — training          | A GPU is required for training (§9.1 of the source PRD).                                                                                              |
| Hardware — inference minimum | CPU-only per SRS §3.2.2 minimum server spec (Intel i3, 4 GB RAM); CUDA-enabled NVIDIA GPU recommended and used automatically where available.         |
| Dependency on M1             | M1's PreprocessedImage, including source_reference at native resolution (Contract C1).                                                                |
| Dataset dependency           | A labelled dataset of real and AI-generated images spanning at least two generator families, with a third held out entirely for the MM2.2 evaluation. |

**\[DECISION REQUIRED\]** Dataset sources and licensing, and whether a third generator family can be held out cleanly (source PRD item M2-B). Needed by milestone M2.1.

**\[DECISION REQUIRED\]** Where model artefacts live — repository, object store or shared volume — and whether they are versioned outside the database (source PRD item M2-D). Needed by milestone M2.4.

**\[ASSUMPTION\]** Images have not been heavily recompressed or resized between generation and upload. Where they have, the frequency branch degrades (see risk in §11).

**\[ASSUMPTION\]** The two branches are sufficiently independent for fusion to help. If their errors prove strongly correlated, MM2.4 will not be met and the fusion design needs revisiting.

# **5. Architecture / Internal Workflow**

    Input: PreprocessedImage (from M1, Contract C1)
       |
       v
    registry.active()  -- raises INF_MODEL_UNAVAILABLE if a required model type has no active version
       |
       +--> 2.1 Semantic Analysis (CLIP)     -> semantic_score  --\
       |                                                              \
       +--> 2.2 Frequency Artifact Analysis  -> frequency_score  ---+--> 2.3 Decision Fusion -> fusion_score
                                                                              |
                                                                              v
                                                              2.4/0.4.4 Generate prediction & confidence
                                                                              |
                                                                              v
                                                        Persist D4 row  --> commit --> InferenceOutput --> M3

The two branches (2.1, 2.2) are independent of each other and may be executed concurrently once the sequential version is correct — concurrency is a latency optimisation for MM2.7, added after the numbers say it is needed, not a day-one design requirement.

# **6. Module Breakdown**

Internal package layout: app/m2_analysis/{router_predict.py, router_models.py, pipeline.py, semantic.py, frequency.py, fusion.py, registry.py, hooks.py, models.py}, plus an offline training/ tree kept outside the application package so nothing the FastAPI process imports can start a training run.

| **Module**          | **Purpose**                                                                                                                                                | **Inputs**                            | **Outputs**                                     | **Depends on**                                              |
|---------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------|-------------------------------------------------|-------------------------------------------------------------|
| pipeline.py         | run_detection() — the single entry point and the Contract C2 producer; orchestrates the branches, fusion, persistence and (optionally) activation capture. | PreprocessedImage, xai_requested flag | InferenceOutput                                 | semantic.py, frequency.py, fusion.py, registry.py, hooks.py |
| semantic.py         | FR-01: CLIP backbone + trainable head (DFD 0.4.1).                                                                                                         | tensor_ref                            | semantic_score (+ activations if requested)     | PyTorch, Hugging Face Transformers                          |
| frequency.py        | FR-02: spectral feature extraction + classifier (DFD 0.4.2).                                                                                               | source_reference                      | frequency_score (+ spectrum if requested)       | NumPy, SciPy/OpenCV                                         |
| fusion.py           | FR-03/FR-04: fusion, calibration, thresholding (DFD 0.4.3–0.4.4).                                                                                          | semantic_score, frequency_score       | fusion_score, predicted_class, confidence_score | Active fusion configuration (D3)                            |
| registry.py         | FR-06/FR-07: D3 access, artefact loading, caching, activation.                                                                                             | Model artefact / model_id             | Active model set; registered model rows         | PostgreSQL, model store                                     |
| hooks.py            | Activation capture for Contract C2 — registers forward/backward hooks only when xai_requested is true.                                                     | Model internals during a forward pass | ActivationBundle                                | semantic.py, frequency.py                                   |
| router_predict.py   | HTTP endpoints for FR-01–FR-05 (create/read predictions).                                                                                                  | HTTP requests                         | InferenceOutput (public half only)              | pipeline.py                                                 |
| router_models.py    | HTTP endpoints for FR-06/FR-07 (registry).                                                                                                                 | HTTP requests                         | Registry responses                              | registry.py                                                 |
| models.py           | SQLAlchemy models for D3 (Models) and D4 (Predictions).                                                                                                    | —                                     | ORM row objects                                 | PostgreSQL                                                  |
| training/ (offline) | train_semantic.py, train_frequency.py, fit_fusion.py, evaluate.py — never imported by the running application.                                             | Labelled dataset                      | Model artefacts, evaluation reports             | PyTorch, scikit-learn                                       |

# **7. Data Requirements**

## **7.1 D3. Models (schema owner: M2)**

    CREATE TABLE models ( -- D3
      model_id BIGSERIAL PRIMARY KEY,
      model_name VARCHAR(120) NOT NULL,
      model_version VARCHAR(40) NOT NULL,
      model_type VARCHAR(32) NOT NULL CHECK (model_type IN
        ('semantic-classifier','frequency-artifact-classifier','fusion-configuration')),
      artifact_ref TEXT NOT NULL,
      artifact_sha256 CHAR(64) NOT NULL,
      hyperparameters JSONB, -- tau, temperature, fusion weights
      metrics JSONB,          -- NF.3 figures at registration time
      is_active BOOLEAN NOT NULL DEFAULT false,
      registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (model_name, model_version)
    );
    -- At most ONE active model per type, enforced by the database:
    CREATE UNIQUE INDEX uq_models_one_active_per_type
      ON models (model_type) WHERE is_active;

artifact_sha256 makes it possible to prove which weights produced a prediction. hyperparameters and metrics keep τ, the calibration temperature and the NF.3 figures attached to the version they belong to.

## **7.2 D4. Predictions (schema owner: M2)**

    CREATE TABLE predictions ( -- D4
      prediction_id BIGSERIAL PRIMARY KEY,
      image_id BIGINT NOT NULL REFERENCES images(image_id) ON DELETE RESTRICT,
      model_id BIGINT NOT NULL REFERENCES models(model_id) ON DELETE RESTRICT,
      branch_model_ids JSONB NOT NULL, -- {semantic: 3, frequency: 7}
      predicted_class VARCHAR(14) NOT NULL CHECK (predicted_class IN ('Real','AI Generated')),
      confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
      semantic_score REAL NOT NULL,
      frequency_score REAL NOT NULL,
      fusion_score REAL NOT NULL,
      latency_ms INTEGER,
      prediction_timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX idx_pred_image ON predictions (image_id);
    CREATE INDEX idx_pred_time ON predictions (prediction_timestamp DESC);

The three branch-score columns are what make the fusion-gain metric (MM2.4) measurable retrospectively, without re-running the whole pipeline. latency_ms is the evidence for NF.1. images.user_id (M1-owned) is joined by M3 for ownership filtering — see PRD 4 §4.

## **7.3 Produced data structure — InferenceOutput (Contract C2)**

    class InferenceOutput(BaseModel):
        # --- public half: stable, safe to serialise, safe to show a user ---
        prediction_id: int
        image_id: int
        user_id: int
        model_id: int                          # the FUSION config row active at inference
        predicted_class: Literal["Real", "AI Generated"]
        confidence_score: float                 # [0,1], confidence IN predicted_class
        semantic_score: float                   # [0,1], P(AI Generated) from CLIP branch
        frequency_score: float                  # [0,1], P(AI Generated) from spectral branch
        fusion_score: float                     # [0,1], P(AI Generated) after fusion
        prediction_timestamp: datetime
        latency_ms: int
        # --- internal half: UNSTABLE, never serialised over HTTP ---
        activations: ActivationBundle | None
     
    class ActivationBundle(BaseModel):
        backbone: Literal["clip_vit_b32", "clip_vit_l14"]
        patch_grid: tuple[int, int]              # e.g. (7, 7) for ViT-B/32 at 224px
        attention: NDArray | None                # (layers, heads, tokens, tokens)
        patch_embeddings: NDArray | None         # (tokens, dim)
        head_gradients: NDArray | None           # populated only when xai_requested=True
        spectrum: NDArray | None                 # log-magnitude FFT, native resolution

**\[IMPLEMENTATION CHOICE\]** ActivationBundle's field set is explicitly unstable — M2 may add, rename or drop fields as the model architecture evolves, with notice to M3 but without a version bump of the Interface Contract. Everything in InferenceOutput above the divider is stable and may not change that way.

# **8. Algorithms / Processing Logic**

## **8.1 Why the CLIP backbone is frozen**

1.  Data: fine-tuning a ViT on a student-scale dataset overfits it to the specific generators in that dataset. The frozen embedding is a general-purpose representation of visual semantics; a fine-tuned one becomes a representation of "the generators I happened to see" — the exact failure mode the held-out-generator goal (§12) is designed to avoid.

2.  Evidence: linear probes on frozen CLIP features are a well-established strong baseline for cross-generator synthetic-image detection and hold up better than fine-tuned CNNs on unseen generator families.

3.  Cost: a frozen backbone means training the head takes minutes on a single GPU, keeping the experiment loop fast enough to actually iterate.

## **8.2 Why the Hann window is not optional (frequency branch)**

An image is a finite signal, and the FFT treats it as one period of an infinitely repeating one. The left edge therefore sits next to the right edge, producing a discontinuity that does not exist in the scene. That discontinuity leaks energy across the entire spectrum as a bright cross through the origin, in every image, real or generated. Without windowing, a substantial fraction of the spectral energy the classifier sees is an artifact of the transform rather than of the image. A 2-D Hann window costs one multiplication per pixel and removes the problem.

## **8.3 The confidence_score inversion (critical algorithm)**

    predicted_class = "AI Generated" if fusion_score >= tau else "Real"
    confidence_score = fusion_score if predicted_class == "AI Generated" \
        else 1.0 - fusion_score

Three of the four score fields (semantic, frequency, fusion) are probabilities of the class "AI Generated". confidence_score is the odd one out: it is the confidence in whichever class was actually predicted. A fusion_score of 0.08 yields predicted_class "Real" with confidence_score 0.92 — never render fusion_score as a confidence figure.

## **8.4 Determinism controls (NF.5)**

- model.eval() everywhere at inference — dropout off, batch-norm statistics frozen.

- torch.no_grad() unless activations were explicitly requested.

- No test-time augmentation, no random cropping, no sampling.

- torch.use_deterministic_algorithms(True) with fixed seeds, so GPU code paths take the reproducible variant even where a faster non-deterministic one exists.

- Cross-device exactness is not claimed: CPU and GPU floating-point reductions differ in the last bits. The contract test asserts numeric agreement to 1e-6 and asserts the predicted label is identical.

# **9. Internal Interfaces**

    async def run_detection(
        prepared: PreprocessedImage,
        *, xai_requested: bool = False,
    ) -> InferenceOutput:
        models = registry.active()                    # raises INF_MODEL_UNAVAILABLE
        with timed() as t:
            sem = semantic.score(prepared.tensor_ref, models.semantic, capture=xai_requested)
            freq = frequency.score(prepared.source_reference, models.frequency, capture=xai_requested)
            fused, label, conf = fusion.combine(sem.score, freq.score, models.fusion)
            row = persist_prediction(prepared, models, label, conf, fused, sem.score, freq.score, t.ms)
        return InferenceOutput(..., activations=bundle(sem, freq) if xai_requested else None)

| **Source**  | **Destination**           | **Interface**                                          | **Behaviour**                                                                                                                                                                              |
|-------------|---------------------------|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| pipeline.py | registry.py               | registry.active()                                      | Resolves the currently active semantic, frequency and fusion configuration; cached with invalidation on activation. Raises INF_MODEL_UNAVAILABLE if any required type has no active model. |
| pipeline.py | semantic.py, frequency.py | score(tensor_or_source, model, capture)                | Independent per-branch scoring; capture=True registers hooks that populate the ActivationBundle.                                                                                           |
| pipeline.py | fusion.py                 | combine(semantic_score, frequency_score, fusion_model) | Applies the active fusion strategy, calibration and threshold τ; returns fused score, label and confidence.                                                                                |
| pipeline.py | models.py (D4)            | persist_prediction(...)                                | Writes and commits the D4 row before InferenceOutput is returned.                                                                                                                          |

# **10. External Interfaces**

| **Contract**                 | **Direction**                          | **What crosses the boundary**                                                                                                                                                                                     |
|------------------------------|----------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| C1 — Preprocessed image      | M1 → M2 (in-process call, no HTTP hop) | M2 consumes PreprocessedImage from prepare_model_input(). M2 asserts tensor shape/dtype on load and raises INF_FAILED if violated — it does not attempt repair, and never re-validates what M1 already validated. |
| C2 — Inference output        | M2 → M3 (in-process call)              | M2 produces InferenceOutput including the ActivationBundle (only when xai_requested). M2 writes D4 and commits before returning, so prediction_id is a valid foreign key the instant M3 receives the structure.   |
| C3 — Session and identity    | M1 → M2 (consumed)                     | M2 receives an already-validated SessionContext via M1's current_session()/require_role() dependencies and treats it as trusted input; M2 performs no credential checks of its own.                               |
| C4 — Model management        | M3 → M2 (HTTP)                         | M2 exposes the registry (GET/POST /api/v1/models, POST /api/v1/models/{id}/activate, GET /api/v1/models/active); M3's admin UI is the only caller. All four require the Admin role.                               |
| C5 — Logging (M2 as emitter) | M2 → M3 (in-process call)              | M2 calls M3's emit() for every prediction request (with latency and model_id), every INF\_\* error, and every model registration/activation.                                                                      |

## **10.1 Public REST API**

| **Method & path**                 | **Auth**     | **Request**                   | **Success**                          | **Errors**                                                    |
|-----------------------------------|--------------|-------------------------------|--------------------------------------|---------------------------------------------------------------|
| POST /api/v1/predictions          | user         | image_id, xai (bool)          | 201 + prediction, scores, confidence | IMG_NOT_FOUND, INF_MODEL_UNAVAILABLE, INF_TIMEOUT, INF_FAILED |
| GET /api/v1/predictions/{id}      | user (owner) | —                             | 200 + prediction record              | INF_PREDICTION_NOT_FOUND                                      |
| GET /api/v1/models                | admin        | —                             | 200 + list                           | AUTH_FORBIDDEN                                                |
| POST /api/v1/models               | admin        | multipart artefact + metadata | 201 + model_id                       | AUTH_FORBIDDEN, 422 on failed canary                          |
| POST /api/v1/models/{id}/activate | admin        | —                             | 200 + active set                     | AUTH_FORBIDDEN, 404                                           |
| GET /api/v1/models/active         | admin        | —                             | 200 + active configuration           | INF_MODEL_UNAVAILABLE                                         |

The HTTP response never contains the activation bundle — it is in-process only, per Contract C2 §5.4. Serialising attention tensors to a browser would be both large and pointless.

# **11. Error Handling and Edge Cases**

| **Code**                 | **HTTP** | **Meaning**                                                               |
|--------------------------|----------|---------------------------------------------------------------------------|
| INF_MODEL_UNAVAILABLE    | 503      | No active model of a required type in D3, or the artefact failed to load. |
| INF_TIMEOUT              | 504      | Inference exceeded the configured wall-clock budget.                      |
| INF_FAILED               | 500      | Unhandled failure inside a classifier or the fusion module.               |
| INF_PREDICTION_NOT_FOUND | 404      | prediction_id does not exist or is not visible to the caller.             |

## **11.1 Edge cases**

- No active model exists for a required type: the request fails with INF_MODEL_UNAVAILABLE rather than silently falling back to a single branch — a hybrid detector running on one branch is a different system and must not pretend otherwise.

- A raised exception inside either branch: the whole request fails with INF_FAILED and no D4 row is written, rather than a prediction based on the surviving branch alone.

- An artefact that cannot load: registration fails at upload time (FR-06's canary pass), not at the next user's prediction.

- Two concurrent activation requests for the same model_type: exactly one succeeds, enforced by the partial unique index, not by application-level locking.

- Submitting the identical image twice with an unchanged active model set: identical scores are returned (determinism, §8.4).

## **11.2 Known risks**

| **Risk**                                                                                                               | **Impact**                                                                    | **Mitigation**                                                                                                                                             |
|------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| The detector learns the dataset rather than the phenomenon (high in-distribution accuracy, poor on unseen generators). | High — the system looks excellent in the report and fails in deployment.      | Held-out generator split reported first (MM2.2); frozen backbone; source-level (not file-level) train/test splitting.                                      |
| Data leakage between splits through paired or near-duplicate images.                                                   | High — every reported figure is inflated invisibly.                           | Split on source identity, plus a perceptual-hash duplicate check across splits before training.                                                            |
| JPEG recompression and social-media resizing erase the spectral fingerprint.                                           | High — the frequency branch is the more fragile of the two in the real world. | Augment training with recompression; measure MM2.10 explicitly; allow fusion to learn to down-weight the branch when recompression signatures are present. |
| CPU inference exceeds the latency budget with two branches running.                                                    | Medium — NF.1 missed on the deployment target.                                | ViT-B/32 rather than L/14; concurrent branch execution once correctness is established; cached model loading.                                              |

# **12. Performance Requirements**

| **SRS ID**                                | **Obligation on M2**                                                                                                           | **Verification**                                                    |
|-------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| NF.1 Response time                        | p95 ≤ 2.5 s CPU, ≤ 0.6 s GPU, excluding explainability. Explainability adds up to 1.4× (Contract C2 §5.3).                     | latency_ms column, aggregated over a load test.                     |
| NF.3 Accuracy                             | Accuracy, Precision, Recall, F1 and ROC-AUC on an independent test set, reported per generator and for the held-out generator. | Evaluation report, §13.5.                                           |
| NF.4 Resource utilisation                 | Models loaded once and cached; GPU used when available; no per-request artefact load from disk.                                | Memory and startup profile.                                         |
| NF.5 Reliability                          | Deterministic inference; a failure in one branch fails the request cleanly rather than degrading to the other.                 | MM2.9 determinism test; fault-injection test.                       |
| NF.10 / NF.12 Scalability & extensibility | A third branch can be added by implementing one scoring interface and one fusion entry, without touching M1 or M3.             | Demonstrated with a throwaway dummy branch in the ablation harness. |
| NF.13 Interpretability                    | Expose sufficient internal state for M3 to explain a prediction, for both branches.                                            | Checkpoint I3.                                                      |

## **12.1 Success metrics**

| **ID** | **Metric**                              | **Target**                                                                                                 |
|--------|-----------------------------------------|------------------------------------------------------------------------------------------------------------|
| MM2.1  | Accuracy, in-distribution test set      | ≥ 0.90                                                                                                     |
| MM2.2  | Accuracy, held-out generator            | ≥ 0.80 — the number that actually predicts deployment behaviour; report honestly even if lower than hoped. |
| MM2.3  | ROC-AUC, combined test set              | ≥ 0.95 (threshold-independent).                                                                            |
| MM2.4  | Fusion gain                             | ≥ +2 percentage points over the better single branch.                                                      |
| MM2.5  | Calibration error (ECE, 10 bins)        | ≤ 0.05, measured after temperature scaling on the validation split.                                        |
| MM2.6  | False positive rate on real photographs | ≤ 0.10 at the chosen operating point τ.                                                                    |
| MM2.7  | Inference latency, p95, CPU             | ≤ 2.5 s per image without explainability.                                                                  |
| MM2.8  | Inference latency, p95, GPU             | ≤ 0.6 s per image where CUDA is available.                                                                 |
| MM2.9  | Determinism                             | Identical scores across 100 runs on fixed hardware; tolerance 1e-6 across devices.                         |
| MM2.10 | JPEG robustness                         | Accuracy drop ≤ 10 points at quality 75.                                                                   |

These targets are commitments to measure and report, not claims. NF.3 explicitly defers final figures to system validation; any target missed is reported as missed rather than restated downward.

# **13. Testing Requirements**

## **13.1 Unit tests**

- Spectral feature extraction is invariant to overall brightness scaling and returns a fixed-length vector for any input size.

- The Hann window is applied — asserted by checking that the spectral cross artifact is suppressed on a synthetic image with mismatched opposite edges.

- Fusion arithmetic across a grid of (semantic, frequency) pairs including the boundaries 0.0, τ and 1.0.

- The confidence inversion, explicitly: fusion_score 0.08 must yield ("Real", 0.92).

- Registry: activating a second model of the same type deactivates the first, in one transaction.

## **13.2 Integration and contract tests**

- C1 with M1: tensor shape, dtype, normalisation, and CLIPProcessor equivalence within 1e-5.

- C2 with M3: every field present and in range; activations present when requested and None when not; the inversion rule asserted from M3's side as well.

- C4 with M3: registration rejects a corrupt artefact before committing; activation is atomic under two concurrent requests.

- Fault injection: a raised exception inside the frequency branch produces INF_FAILED and no D4 row, rather than a prediction based on the semantic branch alone.

## **13.3 Model quality gates (release gates, not aspirations)**

| **Gate** | **Condition**                                                                        |
|----------|--------------------------------------------------------------------------------------|
| Q1       | In-distribution accuracy ≥ 0.90 (MM2.1).                                             |
| Q2       | Held-out generator accuracy ≥ 0.80 (MM2.2).                                          |
| Q3       | Fusion beats the better single branch by ≥ 2 points on the held-out split (MM2.4).   |
| Q4       | ECE ≤ 0.05 after calibration (MM2.5).                                                |
| Q5       | False positive rate on real photographs ≤ 0.10 at the chosen τ (MM2.6).              |
| Q6       | Accuracy at JPEG quality 75 is within 10 points of the uncompressed figure (MM2.10). |

A model artefact that fails any gate is not activated.

## **13.4 Performance tests**

- Fifty sequential inferences on CPU and on GPU; p50 and p95 latency recorded against MM2.7 and MM2.8.

- The same with xai_requested true, confirming the 1.4× budget declared in Contract C2 §5.3 is real.

- Ten concurrent requests, confirming cached model loading holds and memory does not grow per request.

## **13.5 Evaluation protocol (NF.3)**

- Splits are by source image, not by file — if a dataset contains a real photograph and its AI-generated counterpart from the same scene, splitting on filenames alone can put both in different splits and let the model learn the scene rather than the artefact.

- A held-out generator split: at least one generator family appears only in test. MM2.2 is quoted first, since it is the only figure estimating behaviour on generators that did not exist when the model was trained.

- The test set is touched once, at the end. Any threshold, temperature or fusion weight tuned on the test set turns it into a validation set and invalidates the reported figures.

- Reported: Accuracy, Precision, Recall, F1, ROC-AUC overall and per generator family; the confusion matrix at the chosen τ; expected calibration error and a reliability diagram; the ablation (semantic alone / frequency alone / fused); a robustness sweep at JPEG quality 95/85/75/60, 50% downscaling, and mild Gaussian noise.

- Honest reporting: if the fused model does not beat both branches, that result is reported and investigated rather than hidden behind a more favourable in-distribution number.

# **14. Acceptance Criteria**

## **AC group 1 — Classification (FR-01–FR-04)**

**AC-01.** *Given* a valid PreprocessedImage*, when* the module classifies it*, then* it returns exactly one of "Real" or "AI Generated" — never "uncertain", never a third class.

**AC-02.** *Given* any classification request*, when* both branches run*, then* both semantic_score and frequency_score are present in the output, even when one alone would have been sufficient to decide.

**AC-03.** *Given* no active model exists for a required type*, when* a prediction is requested*, then* the request fails with INF_MODEL_UNAVAILABLE rather than silently falling back to a single branch.

**AC-04.** *Given* the same image is submitted twice with the active model set unchanged*, when* both requests are classified*, then* the scores are identical.

## **AC group 2 — Confidence score (FR-04)**

**AC-05.** *Given* any completed prediction*, when* confidence_score is read*, then* it lies in \[0,1\] and follows the inversion rule of Contract C2 §5.2.

**AC-06.** *Given* the validation set's predictions in the 0.9–1.0 confidence band*, when* empirical correctness is measured*, then* they are correct at least 85% of the time.

**AC-07.** *Given* any completed prediction*, when* the record is inspected*, then* both branch scores are recorded alongside the fused score, so disagreement between branches is recoverable after the fact.

## **AC group 3 — Prediction storage (FR-05)**

**AC-08.** *Given* a completed inference*, when* InferenceOutput is returned*, then* a D4 row has already been written and committed, so prediction_id is a valid foreign key.

**AC-09.** *Given* a prediction row*, when* model_id is inspected*, then* it references the fusion configuration that was active at the moment of inference, not the one active at read time.

**AC-10.** *Given* persistence of the D4 row fails for any reason*, when* the request completes*, then* the request itself fails rather than returning a prediction absent from history.

## **AC group 4 — Model management (FR-06, FR-07)**

**AC-11.** *Given* a new model artefact is registered*, when* the canary forward pass is run*, then* registration is rejected before any row is committed if the artefact fails to load or produces the wrong output shape.

**AC-12.** *Given* a model of a given type is activated*, when* the transaction commits*, then* the previous active version of the same type is deactivated in the same transaction.

**AC-13.** *Given* the models table*, when* is inspected at any time*, then* at most one row per model_type has is_active true.

**AC-14.** *Given* a model is activated after some predictions were already made*, when* history is reviewed*, then* predictions made before the activation continue to reference the older model_id; history is never rewritten.

# **15. Definition of Done**

M2 is done when every acceptance criterion in §14 passes; quality gates Q1–Q6 (§13.3) are evaluated and their outcomes reported whether or not they were met; contract tests C1, C2 and C4 are green against both stubs and real implementations; and the evaluation report leads with the held-out generator figure (MM2.2) rather than the in-distribution one.

## **15.1 Milestones**

| **Milestone**               | **Deliverable**                                                                                                                      | **Gate**                                |
|-----------------------------|--------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------|
| M2.0 — Stub                 | run_detection() returning a deterministic InferenceOutput derived from image_id, with a correctly-shaped synthetic ActivationBundle. | Unblocks M3 immediately; checkpoint I1. |
| M2.1 — Semantic branch      | CLIP embedding extraction, trained head, first accuracy figures, C1 equivalence test green.                                          | Before checkpoint I2.                   |
| M2.2 — Frequency branch     | Spectral pipeline with windowing, trained classifier, ablation against the semantic branch.                                          | Before checkpoint I2.                   |
| M2.3 — Fusion & calibration | Strategy A and B compared on the held-out split, τ selected, temperature fitted, OI-1 closed.                                        | Checkpoint I2.                          |
| M2.4 — Persistence          | D3 and D4 migrations, prediction writing, registry endpoints, atomic activation.                                                     | Checkpoint I4.                          |
| M2.5 — Activation capture   | Hooks and ActivationBundle for both branches, delivered with M3.                                                                     | Checkpoint I3.                          |
| M2.6 — Evaluation report    | Full NF.3 report including per-generator breakdown, ablation, calibration and the robustness sweep.                                  | Release candidate.                      |
