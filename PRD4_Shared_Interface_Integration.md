**PRODUCT REQUIREMENTS DOCUMENT**

**PRD 4 — Shared Interface & Integration PRD**

*for TruePixels.rgb — An AI-Generated Image Detection System*

| **Field**         | **Value**                                                                      |
|-------------------|--------------------------------------------------------------------------------|
| Module / Division | Cross-cutting — the contract between M1, M2 and M3                             |
| Owner             | Joint (Amogh R Gowda, Anurag V Rao, Debanshu Mitra)                            |
| Team              | Amogh R Gowda (241IT008) · Anurag V Rao (241IT011) · Debanshu Mitra (241IT019) |
| Version           | 1.0                                                                            |
| Date              | 7 September 2026                                                               |

**Parent documents:**

- SRS for TruePixels.rgb (IEEE 830-1998), v1.1

- Design Document using SA/SD Methodology for TruePixels.rgb — DFD Model, Data Dictionary and Structured Chart

- TruePixels.rgb — Module Interface Contract, v1.0 (this PRD restructures that document; where the two differ, re-derive from the source contract rather than trusting a paraphrase)

- PRD 1 — Image & Access Management (M1); PRD 2 — Image Analysis & Prediction (M2); PRD 3 — Results & Reporting Management (M3)

Department of Information Technology

National Institute of Technology Karnataka, Surathkal

# **Table of Contents**

# **Status of this document**

This document is not another implementation PRD. It is the contract between PRD 1 (M1), PRD 2 (M2) and PRD 3 (M3): the single authoritative source for everything that crosses a module boundary — data structures, function signatures, HTTP endpoints, database ownership, error codes and logging obligations. Three independently-working implementers should be able to build PRD 1, PRD 2 and PRD 3 against this document alone, without reinterpreting the SRS or negotiating seams after the fact.

**\[IMPLEMENTATION CHOICE\]** Rule of thumb carried over from the source Interface Contract: if a change affects only the inside of one module, that module's owner decides alone. If a change affects anything in this document, all three owners must agree and this document's version number is incremented. Where a module PRD and this document disagree, this document wins.

# **1. Integration Overview**

The partition follows the Structured Chart (Figure 10) exactly. M1 authenticates and prepares input; M2 classifies; M3 explains, presents and administers. Two allocations are not obvious from the chart alone and are fixed here so no implementer has to guess.

                     M1 — Image & Access Management
                     (auth, upload, validation, preprocessing)
                                |
                     C1: PreprocessedImage       C3: SessionContext
                                |                          |
                                v                          v
                     M2 — Image Analysis & Prediction  <---+---> M3 — Results & Reporting
                     (CLIP branch, frequency branch,        (explainability, history,
                      fusion, model registry)                 reports, admin, logging)
                                |                                     ^
                                +------ C2: InferenceOutput ----------+
                                |                                     |
                                +<----------- C4: model mgmt ---------+
                                |                                     |
                     (all three)+------------- C5: emit() ------------+

## **1.1 Deviation 1 — F.19 AI Model Management is implemented by M2, surfaced by M3**

A naive reading of the Structured Chart would place model upload and activation under M3's "Reports & Administration". But D3 (Models) is read on every inference by M2, and "activate a model version" is inference semantics, not administrative semantics — splitting write access to D3 across two owners is the classic recipe for an unreproducible race condition.

Resolution: M2 owns the D3 schema and implements the model registry service and its endpoints (Contract C4). M3 implements only the administrator interface for model management and calls M2's endpoints. M3 never writes to D3 directly.

## **1.2 Deviation 2 — Explainability Generation stays in M3**

DFD process 0.5 consumes the preprocessed image and the inference output, both produced upstream, which would argue for placing it in M2. The Structured Chart places it in M3, and it stays there for consistency with the submitted design artefact. The cost of this choice is that M2 must expose intermediate model state across the module boundary, which Contract C2 (§4 below) specifies precisely — this is the widest, most failure-prone seam in the system and is treated accordingly throughout this document.

## **1.3 Data store ownership**

Exactly one module owns the schema of each data store and is the only module permitted to write to it. Any other module needing a write goes through the owner's service interface.

| **Store**          | **Schema owner** | **Writers**                                          | **Readers**                        |
|--------------------|------------------|------------------------------------------------------|------------------------------------|
| D1. Users          | M1               | M1 only                                              | M1, M3 (admin views, via M1's API) |
| D2. Images         | M1               | M1 only                                              | M1, M2, M3                         |
| D3. Models         | M2               | M2 only                                              | M2, M3 (via M2's API)              |
| D4. Predictions    | M2               | M2 only                                              | M2, M3                             |
| D5. Explainability | M3               | M3 only                                              | M3                                 |
| D6. Logs           | M3               | M3 only (all modules write via the emit() interface) | M3                                 |

Note on D1: user account enable/disable/remove (F.17) is an administrative action owned by M3 at the user-interface level, but the write is executed by M1 (Contract C3.3).

# **2. Interface Inventory**

| **ID** | **Source** | **Destination** | **Interface**                                                                      | **Purpose**                                                                                             |
|--------|------------|-----------------|------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| INT-01 | M1         | M2              | Contract C1 — PreprocessedImage (in-process call)                                  | Hand off the validated, preprocessed tensor and native original for inference.                          |
| INT-02 | M2         | M3              | Contract C2 — InferenceOutput (in-process call)                                    | Hand off the prediction, scores, and (when requested) the internal activation state for explainability. |
| INT-03 | M1         | M2, M3          | Contract C3 — SessionContext + current_session()/require_role() dependencies       | Authenticate the caller and resolve their role at the request boundary, once, for every module.         |
| INT-04 | M3         | M1              | Contract C3.3 — PATCH /api/v1/users/{user_id}/status                               | Administrator-initiated account state change, rendered by M3, executed by M1.                           |
| INT-05 | M3         | M2              | Contract C4 — model registry endpoints (GET/POST /api/v1/models, activate, active) | Administrator-initiated model registration and activation, rendered by M3, executed by M2.              |
| INT-06 | M1, M2, M3 | M3              | Contract C5 — emit() logging interface                                             | Every module records significant events to the single log store M3 owns.                                |

# **3. API Contracts**

INT-01 and INT-02 are in-process function calls (no HTTP hop) and are specified as data contracts in §4, not as API endpoints. INT-03's current_session()/require_role() are FastAPI dependencies, not endpoints, and are specified in §4.4. The API endpoints below are the only HTTP calls that cross a module boundary; every other endpoint in PRDs 1–3 is called only by that module's own frontend.

## **3.1 INT-04 — Administrative account state change**

| **Field**        | **Value**                                                                                                                                             |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Endpoint         | PATCH /api/v1/users/{user_id}/status                                                                                                                  |
| Owner / caller   | Owner: M1. Caller: M3's admin UI only.                                                                                                                |
| Auth             | require_role("Admin")                                                                                                                                 |
| Request body     | { "action": "enable" \| "disable" \| "remove" }                                                                                                       |
| Success response | 200 — { "user_id": 42, "account_status": "disabled" }                                                                                                 |
| Error responses  | AUTH_FORBIDDEN (403) — caller is not an administrator. ADM_ACTION_NOT_PERMITTED (409) — e.g. an administrator attempting to modify their own account. |

## **3.2 INT-05 — Model registry**

| **Endpoint**                      | **Purpose**                                                               | **Notes**                                                                                                           |
|-----------------------------------|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| GET /api/v1/models                | List registered models with type, version and active flag.                | Feeds M3's model management table.                                                                                  |
| POST /api/v1/models               | Register a new artefact and its metadata.                                 | multipart/form-data. M2 validates that the artefact loads and passes a canary forward pass before committing to D3. |
| POST /api/v1/models/{id}/activate | Make a version active for its type.                                       | Atomic: deactivates the previous active row of the same model_type in one transaction.                              |
| GET /api/v1/models/active         | Return the currently active semantic, frequency and fusion configuration. | Used by M3's dashboard and by M2 internally on every inference.                                                     |

All four require the Admin role. Constraint: at most one row per model_type may have is_active = true, enforced by a partial unique index in M2's schema, not by application logic — application-level enforcement fails under concurrent activation.

## **3.3 General API conventions**

- Base path /api/v1 for every module. A breaking change to any cross-boundary endpoint requires a version bump of this document, not a silent edit in place.

- All request/response bodies are JSON, except image upload (multipart/form-data) and PDF download (application/pdf).

- Identifiers are 64-bit integers in the database, serialised as JSON numbers. Session tokens are opaque strings; no module other than M1 parses one.

- Timestamps are ISO 8601 with an explicit UTC offset (e.g. 2026-08-24T09:15:00Z); the database column type is TIMESTAMPTZ. No local times anywhere.

- Scores and probabilities are floats in the closed interval \[0.0, 1.0\], serialised with at most six decimal places.

# **4. Data Contracts**

These are the exact, binding shapes for every structure that crosses a module boundary. No module PRD may define a conflicting version of any structure below.

## **4.1 Contract C1 — PreprocessedImage (M1 → M2)**

    class PreprocessedImage(BaseModel):
        image_id: int                  # FK to D2.images
        user_id: int                    # owner, for authorisation and D4 linkage
        tensor_ref: str                  # path to a .npy on the shared volume
        shape: tuple[int, int, int]      # (C, H, W) = (3, 224, 224)
        dtype: Literal["float32"]
        normalization: NormalizationParams
        source_reference: str            # path to the ORIGINAL decoded image
        created_at: datetime
     
    class NormalizationParams(BaseModel):
        mean: tuple[float, float, float]
        std: tuple[float, float, float]
        scheme: Literal["clip_openai", "imagenet"]

Field

| **Guarantee**                      | **Detail**                                                                                                                                                                                                                                                                                                                                                                      |
|------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Shape and dtype                    | The tensor at tensor_ref exists, is readable, and has exactly shape (3, 224, 224) and dtype float32. M2 asserts this on load and raises INF_FAILED if violated — it does not attempt repair.                                                                                                                                                                                    |
| Prior validation                   | The underlying image passed all four validation stages of M1's DFD 0.2 (format, size, integrity, accept/reject). M2 does not re-validate.                                                                                                                                                                                                                                       |
| Native original                    | source_reference points at the losslessly-decoded original, not the resized tensor. Both frequency-artifact analysis (M2) and explainability overlays (M3) degrade if run on an already-resampled image.                                                                                                                                                                        |
| Commit ordering                    | The D2.images row is committed before this structure is handed over, so image_id is always a valid foreign key target.                                                                                                                                                                                                                                                          |
| No resize before spectral analysis | M1 supplies both the 224×224 normalised tensor (feeds the CLIP branch) and source_reference (feeds the frequency branch, which performs its own centre crop at native resolution). M2 must not resize before spectral analysis — resizing to 224×224 is a low-pass filter that destroys exactly the high-frequency evidence the frequency-artifact classifier exists to detect. |

Invocation is an in-process call — there is no HTTP hop between M1 and M2:

    from app.m1_access.preprocess import prepare_model_input
    prepared: PreprocessedImage = prepare_model_input(image_id, session)
    result: InferenceOutput = await run_detection(prepared)

## **4.2 Contract C2 — InferenceOutput (M2 → M3)**

The widest seam in the system: M3 owns explainability while M2 owns the models explainability must interrogate. Specified in two halves — a stable public half and an explicitly unstable internal half.

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

### **4.2.1 The confidence_score definition — the single highest-risk field in this document**

Three of the four score fields are probabilities of the class "AI Generated". confidence_score is not — it is the confidence in whichever class was predicted:

    predicted_class = "AI Generated" if fusion_score >= tau else "Real"
    confidence_score = fusion_score if predicted_class == "AI Generated" \
        else 1.0 - fusion_score

**\[DECISION REQUIRED\]** This is not an open decision — it is fixed and binding — but it is flagged here at maximum visibility because it is the single most likely integration bug in the project. A fusion_score of 0.08 yields predicted_class "Real" with confidence_score 0.92. M3 must render confidence_score to the user and must never render fusion_score as a confidence: a confidently-real image would otherwise appear as 8% confident, which looks like a weak model rather than a wiring error.

### **4.2.2 Requesting activations**

    result = await run_detection(prepared, xai_requested=True)
    # xai_requested=False -> result.activations is None, no hooks registered
    # xai_requested=True  -> hooks registered; ~1.4x inference latency (budget)

When constraint C.3 applies (the active model exposes no usable internal state), M2 returns activations=None even though it was asked. M3 must handle this and surface XAI_UNAVAILABLE rather than crashing or fabricating a blank heat map.

### **4.2.3 Lifetime and stability**

- The bundle is in-memory only: never written to D4, never returned by an HTTP endpoint, never pickled to disk.

- It is valid only for the duration of the request that produced it. M3 must consume it synchronously; if explainability is deferred to a background task, M3 re-requests inference rather than holding a reference.

- Its field set is explicitly unstable — M2 may add, rename or drop fields as the model architecture evolves, with notice to M3 but without a version bump of this document. Everything above the divider line in the InferenceOutput definition is stable and may not change that way.

### **4.2.4 Who writes the prediction row**

M2 writes D4.predictions and commits before returning, so prediction_id is a valid foreign key by the time M3 receives the structure and writes its D5.explainability row against it. M3 never inserts into D4.

## **4.3 Contract C3 — SessionContext (M1 → M2, M3)**

    class SessionContext(BaseModel):
        user_id: int
        email: str
        role: Literal["User", "Admin"]
        account_status: Literal["active", "disabled", "removed"]
        session_token: str
        issued_at: datetime
        expires_at: datetime

### **4.3.1 Rules**

1.  M1 is the only module that creates, validates or revokes a token. M2 and M3 receive an already-validated SessionContext from the dependency and treat it as trusted input.

2.  Ownership checks are the calling module's job, not M1's. M1 answers "who is this?"; M2 and M3 answer "may this person see that record?". Concretely: FR-03 in PRD 3 requires that a user sees only their own history, so M3 filters D4 by session.user_id — M1 cannot do this on M3's behalf.

3.  An expired or revoked token yields AUTH_TOKEN_INVALID from the dependency itself. Downstream handler code never sees an invalid session.

## **4.4 Cross-boundary foreign keys**

| **Referencing column**       | **Declared by** | **Targets**               | **Owned by** | **On delete** |
|------------------------------|-----------------|---------------------------|--------------|---------------|
| images.user_id               | M1              | users.user_id             | M1           | RESTRICT      |
| predictions.image_id         | M2              | images.image_id           | M1           | RESTRICT      |
| predictions.model_id         | M2              | models.model_id           | M2           | RESTRICT      |
| explainability.prediction_id | M3              | predictions.prediction_id | M2           | CASCADE       |
| logs.user_id                 | M3              | users.user_id             | M1           | SET NULL      |

RESTRICT rather than CASCADE on the prediction chain is deliberate: an audit trail that silently deletes itself when a user account is removed is not an audit trail. F.17 "remove" is therefore a status change, never a row deletion.

# **5. Input / Output Contracts**

| **Component** | **Consumes**                                                                                                | **Produces**                                                                                                    | **Consumed from**             | **Provided to**                                                                     |
|---------------|-------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|-------------------------------|-------------------------------------------------------------------------------------|
| M1            | Raw HTTP requests: registration/login credentials; multipart image uploads.                                 | SessionContext (C3); PreprocessedImage (C1).                                                                    | — (entry point of the system) | SessionContext → M2, M3. PreprocessedImage → M2.                                    |
| M2            | PreprocessedImage (C1, from M1); SessionContext (C3, from M1, via the shared dependency, not re-validated). | InferenceOutput including ActivationBundle (C2); model registry state (C4).                                     | M1 (C1, C3)                   | InferenceOutput → M3. Registry responses → M3 (via C4 calls M3 initiates).          |
| M3            | InferenceOutput (C2, from M2); SessionContext (C3, from M1).                                                | D5 rows and rendered views; D6 log store (owns the reader side of C5); proxied writes to M1 (C3.3) and M2 (C4). | M2 (C2), M1 (C3)              | Rendered results, history, reports and admin views to the end user / administrator. |

Every module owns the data it produces until the consuming module's guarantees (§4) are satisfied — most concretely, M1 does not hand off PreprocessedImage until the D2 row is committed, and M2 does not hand off InferenceOutput until the D4 row is committed.

# **6. Processing Sequence**

## **6.1 Primary flow — image analysis**

    User Input (login + image upload)
        |
        v
    M1: authenticate (C3) -> validate & preprocess image -> commit D2
        |
        v  (C1: PreprocessedImage)
    M2: resolve active models -> semantic + frequency scoring -> fusion -> commit D4
        |
        v  (C2: InferenceOutput, + ActivationBundle if requested)
    M3: (optional) generate explainability -> commit D5 -> render results view
        |
        v
    Final Output: results view / history entry / downloadable PDF

## **6.2 Alternative flow — administrator account management**

    Administrator (via M3 admin UI)
        |
        v  (C3.3: PATCH /api/v1/users/{id}/status)
    M1: apply account_status change to D1, subject to the self-modification guard
        |
        v
    M3: reflects the updated status in the admin account table

## **6.3 Alternative flow — administrator model management**

    Administrator (via M3 admin UI)
        |
        v  (C4: POST /api/v1/models, POST /api/v1/models/{id}/activate)
    M2: validates artefact (canary pass), commits D3, atomically activates
        |
        v
    M3: reflects the updated registry state in the admin model table

## **6.4 Failure flow — validation or inference cannot proceed**

- An invalid upload never reaches M2: the flow terminates inside M1 with IMG_FORMAT_UNSUPPORTED, IMG_TOO_LARGE or IMG_CORRUPTED, and M1 emits the corresponding D6 event via C5.

- No active model of a required type: the flow terminates inside M2 with INF_MODEL_UNAVAILABLE before any D4 row is written; M3 never receives an InferenceOutput for that request.

- Explainability unsupported by the active model: the flow does not terminate — M3 degrades the results view and records XAI_UNAVAILABLE, per constraint C.3.

# **7. Error Contracts**

Every non-2xx response from every module has exactly this shape. This satisfies F.20 and NF.7: the message is safe to show a user, and the detail that is not safe to show goes to D6 instead.

    {
      "error": {
        "code": "IMG_FORMAT_UNSUPPORTED",
        "message": "Only JPG, JPEG and PNG images are accepted.",
        "request_id": "b41c0f7e-1d2a-4c31-9f88-6a2b0e4d1177"
      }
    }

Codes are namespaced by owning module. This registry is closed: adding a code requires a version bump of this document.

| **Code**                 | **HTTP** | **Owner** | **Meaning**                                                                                                                              |
|--------------------------|----------|-----------|------------------------------------------------------------------------------------------------------------------------------------------|
| AUTH_EMAIL_TAKEN         | 409      | M1        | Registration with an email already present in D1.                                                                                        |
| AUTH_INVALID_CREDENTIALS | 401      | M1        | Email or password did not match.                                                                                                         |
| AUTH_TOKEN_INVALID       | 401      | M1        | Missing, malformed or expired session token.                                                                                             |
| AUTH_FORBIDDEN           | 403      | M1        | Authenticated but role is insufficient for the resource.                                                                                 |
| AUTH_ACCOUNT_DISABLED    | 403      | M1        | Account state is disabled or removed.                                                                                                    |
| IMG_FORMAT_UNSUPPORTED   | 415      | M1        | File extension or sniffed content is not JPG/JPEG/PNG.                                                                                   |
| IMG_TOO_LARGE            | 413      | M1        | File exceeds the configured maximum upload size.                                                                                         |
| IMG_CORRUPTED            | 422      | M1        | Decoder could not open the file, or the file is truncated.                                                                               |
| IMG_NOT_FOUND            | 404      | M1        | image_id does not exist, or is not owned by the caller.                                                                                  |
| INF_MODEL_UNAVAILABLE    | 503      | M2        | No active model of a required type in D3, or artefact failed to load.                                                                    |
| INF_TIMEOUT              | 504      | M2        | Inference exceeded the configured wall-clock budget.                                                                                     |
| INF_FAILED               | 500      | M2        | Unhandled failure inside a classifier or the fusion module.                                                                              |
| INF_PREDICTION_NOT_FOUND | 404      | M2        | prediction_id does not exist or is not visible to the caller.                                                                            |
| XAI_UNAVAILABLE          | 501      | M3        | Explainability not supported for the active model (constraint C.3).                                                                      |
| RPT_GENERATION_FAILED    | 500      | M3        | PDF assembly failed.                                                                                                                     |
| ADM_ACTION_NOT_PERMITTED | 409      | M3\*      | Administrative action rejected by policy, e.g. self-removal. \*Enforced by M1 at the C3.3 endpoint; surfaced unchanged by M3's admin UI. |

## **7.1 Propagation and retry rules**

- A module receiving another module's error via an in-process call (C1, C2) or an internal HTTP call (C3.3, C4) surfaces the code unchanged. Re-wrapping it hides the origin of the failure from whoever is reading the log.

- INF_TIMEOUT (504) and INF_MODEL_UNAVAILABLE (503) are safe for a client to retry after a delay; the other error codes in this registry represent conditions that will not change on an immediate retry (bad credentials, unsupported format, non-existent record).

- A logging failure inside emit() (C5) never propagates as an error to the caller — it is swallowed by design (PRD 3 §8.4) and is the one deliberate exception to "never silently discard a failure" in this system.

# **8. Configuration Contracts**

| **Category**            | **Shared value**                                                                                                                                                                       |
|-------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Runtime                 | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.x, PostgreSQL 15.                                                                                                                      |
| Frontend                | React 18 with Vite; a single application, three feature folders mirroring M1/M2/M3.                                                                                                    |
| Inference stack         | PyTorch 2.x, Hugging Face Transformers; OpenCV and NumPy for preprocessing and spectral work.                                                                                          |
| Repository layout       | truepixels/app/{m1_access/, m2_analysis/, m3_results/, shared/, main.py}; tests/; frontend/. Each owner works inside their own package and touches shared/ only by agreement.          |
| Shared package contents | shared/schemas.py (PreprocessedImage, InferenceOutput, ActivationBundle, SessionContext), shared/errors.py (error envelope + code registry), shared/logging.py (emit()), shared/db.py. |

**\[DECISION REQUIRED\]** Maximum upload file size (PRD 1 open issue OI-2, proposed 10 MB) — must be a single configuration value read by both M1's API and the frontend build, not independently chosen on each side.

**\[DECISION REQUIRED\]** Session token mechanism (PRD 1 open issue OI-3): signed JWT versus server-side session row. Affects whether account-status revocation (C3.3) is immediate or takes effect only at next token validation.

**\[DECISION REQUIRED\]** Log retention policy (PRD 3 item M3-A): proposed 90 days for severity "info", 1 year for "warning"/"error", not yet confirmed against the SRS.

## **8.1 Migration policy**

4.  A migration may only touch tables owned by the author's module. A migration touching two owners' tables is reviewed by both.

5.  Foreign keys pointing across a boundary are declared by the owner of the referencing table (see §4.4) — e.g. predictions.image_id is declared by M2 even though images belongs to M1.

6.  Migration file names carry the module tag, e.g. 0007_m2_add_fusion_weights.py, so ownership is visible in a directory listing.

7.  Nobody drops or renames a column another module reads without agreement recorded in this document's change log.

# **9. Integration Dependencies**

None of the three modules can wait for the others. Each owner ships a stub of their side of every outbound contract in week 1, before the real implementation exists.

| **Stub**                 | **Provided by** | **Behaviour**                                                                                                                                                                     |
|--------------------------|-----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| prepare_model_input()    | M1              | Returns a PreprocessedImage pointing at a fixed 3×224×224 tensor of a checked-in test image, with a valid image_id seeded in D2.                                                  |
| run_detection()          | M2              | Returns a deterministic InferenceOutput derived from a hash of image_id — stable across runs, covers both classes, includes a synthetic ActivationBundle with the correct shapes. |
| emit()                   | M3              | No-op that validates its arguments and raises in test mode if a forbidden field is passed.                                                                                        |
| Model registry endpoints | M2              | In-memory list with one active model per type.                                                                                                                                    |

## **9.1 Startup and integration checkpoints**

| **Checkpoint**               | **Gate**                                                                                    | **Depends on**               |
|------------------------------|---------------------------------------------------------------------------------------------|------------------------------|
| I1 — Vertical slice          | A logged-in user uploads a JPG and receives a hardcoded prediction rendered in the browser. | M1 real, M2 stub, M3 real    |
| I2 — Real inference          | The same flow with genuine CLIP and frequency branches and real fusion.                     | M1 real, M2 real, M3 real    |
| I3 — Explainability          | The results view shows a real heat map generated from a real ActivationBundle.              | C2 internal half stable      |
| I4 — Persistence and history | Predictions survive a restart; FR-03 history shows only the caller's rows.                  | D2, D4, D5 migrations merged |
| I5 — Administration          | Dashboard, logs, analytics, user management and model activation all functional.            | C4 and C5 complete           |

Dependency order: PostgreSQL migrations for D1/D2 (M1) must be merged before M2's D3/D4 migrations, since predictions.image_id references images.image_id; D5's migration (M3) depends on D4 existing, since explainability.prediction_id references predictions.prediction_id.

# **10. Integration Testing**

For each contract there is one test file, owned jointly, living in tests/contracts/. It asserts only the properties stated in this document — shapes, ranges, the confidence_score inversion (§4.2.1), the single-active-model index, the error envelope shape. These tests run against both the stub and the real implementation, and both must pass. When a contract test fails, the fault is in the module, not in the test.

| **Test**                            | **Asserts**                                                                                                                                                                                                                         |
|-------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| C1 contract test (M1 ↔ M2, joint)   | Tensor shape (3,224,224), dtype float32, normalisation scheme, and agreement with the reference CLIPProcessor output to within 1e-5 on 20 images. Also: source_reference resolves to the original resolution, not the 224×224 copy. |
| C2 contract test (M2 ↔ M3, joint)   | Every public-half field present and in range; activations present when xai_requested and None when not; the confidence_score inversion asserted independently from both M2's and M3's side.                                         |
| C2 degraded-path test (M3)          | activations=None despite xai_requested=True yields XAI_UNAVAILABLE and a results view rendered without a visualisation, never a crash or a blank image.                                                                             |
| C3 test (M1 ↔ M2, M1 ↔ M3)          | An expired or tampered token yields AUTH_TOKEN_INVALID before any handler body executes, on every protected route in the application (route-table audit).                                                                           |
| C4 contract test (M2 ↔ M3, joint)   | Registration rejects a corrupt artefact before committing to D3; activation is atomic under two concurrent requests; a model activation performed through M3's screen is reflected in M2's active configuration.                    |
| C5 test (all modules ↔ M3)          | emit() called with a forbidden field (password, token, authorization, bearer pattern) raises in test mode and is silently redacted in production mode.                                                                              |
| Isolation suite (M3, cross-cutting) | The 8-case ownership isolation suite in PRD 3 §11.1 — no user-facing endpoint anywhere in the system can be made to return another user's data.                                                                                     |
| End-to-end (all modules)            | Upload through M1 → infer through M2 → view and download a PDF through M3, asserting the verdict and confidence in the PDF match the results view exactly.                                                                          |

# **11. Integration Acceptance Criteria**

**INT-AC-01.** *Given* a user uploads a valid image and no other module has changed since the last green build*, when* checkpoint I1's vertical slice is run*, then* the user receives a rendered prediction end to end through M1 (real), M2 (stub) and M3 (real).

**INT-AC-02.** *Given* checkpoint I2 is reached*, when* the same vertical slice is run against real M1, M2 and M3 implementations*, then* the CLIP branch, frequency branch and fusion module all execute and produce a genuine prediction.

**INT-AC-03.** *Given* a prediction is generated with xai_requested=True and the active model supports it*, when* the results view is rendered*, then* it shows a real explainability heat map derived from a real ActivationBundle, not a stub.

**INT-AC-04.** *Given* a prediction has been made and the application is restarted*, when* the same user requests their history*, then* the prediction still appears, and only that user's own predictions are returned.

**INT-AC-05.** *Given* an administrator opens the dashboard, log explorer, analytics view, user management screen and model management screen*, when* each is exercised*, then* all five are functional and every administrative action is itself logged.

**INT-AC-06.** *Given* M2 returns a fusion_score below the active threshold τ*, when* M3 renders the results view*, then* the displayed confidence percentage equals confidence_score, not fusion_score, in every case (contract test asserted from both sides).

**INT-AC-07.** *Given* two concurrent requests attempt to activate two different models of the same model_type*, when* both are submitted*, then* exactly one succeeds and the database enforces at most one active row per type, independent of application-level locking.

**INT-AC-08.** *Given* any two of the three modules are built strictly against this document, without reference to each other's source code*, when* they are integrated for the first time*, then* the contract tests in §10 pass without modification to either module.

# **12. Non-Negotiable Contracts**

The following may not be changed by any single module owner acting alone. A change to any of these requires the agreement of all three owners and a version increment of this document.

- The stable (public) half of InferenceOutput (Contract C2, above the divider in §4.2) — field names, types and the confidence_score inversion formula.

- The SessionContext shape (Contract C3) and the rule that only M1 creates, validates or revokes a token.

- The PreprocessedImage shape, its (3, 224, 224) float32 tensor convention, and the requirement that source_reference always points at the native-resolution original.

- The error envelope shape ({"error": {"code", "message", "request_id"}}) and the closed error code registry in §7 — a new code requires a version bump, not an ad-hoc addition.

- Data store ownership (§1.3): exactly one writer per store, enforced by which module's migrations may touch which tables.

- The single-active-model-per-type invariant on D3, and that it is enforced by a database constraint, not application logic.

- The emit() function signature (Contract C5) and the rule that a logging failure never fails the request that triggered it.

- The cross-boundary foreign key ownership table in §4.4, including RESTRICT semantics on the prediction chain (predictions are never hard-deleted).

**\[IMPLEMENTATION CHOICE\]** Explicitly exempt from the above: the unstable (internal) half of Contract C2 — ActivationBundle's field set. M2 may add, rename or drop fields there as the model architecture evolves; M2 need only notify M3, without a version bump of this document (§4.2.3).
