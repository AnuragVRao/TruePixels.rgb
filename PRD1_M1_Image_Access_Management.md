**PRODUCT REQUIREMENTS DOCUMENT**

**PRD 1 — Image & Access Management (M1)**

*for TruePixels.rgb — An AI-Generated Image Detection System*

| **Field**         | **Value**                                                                           |
|-------------------|-------------------------------------------------------------------------------------|
| Module / Division | M1 — Image & Access Management (Structured Chart, Figure 10; DFD processes 0.1–0.3) |
| Owner             | Amogh R Gowda (241IT008)                                                            |
| Team              | Amogh R Gowda (241IT008) · Anurag V Rao (241IT011) · Debanshu Mitra (241IT019)      |
| Version           | 1.0                                                                                 |
| Date              | 7 September 2026                                                                    |

**Parent documents:**

- SRS for TruePixels.rgb (IEEE 830-1998), v1.1

- Design Document using SA/SD Methodology for TruePixels.rgb — DFD Model, Data Dictionary and Structured Chart

- TruePixels.rgb — Module Interface Contract, v1.0 (defines Contracts C1, C3, C5 referenced throughout)

Department of Information Technology

National Institute of Technology Karnataka, Surathkal

# **Table of Contents**

# **1. Component Overview**

| **Field**                 | **Value**                                                     |
|---------------------------|---------------------------------------------------------------|
| Component name            | M1 — Image & Access Management                                |
| SRS requirements realised | F.1, F.2, F.3, F.4, F.5, F.6, F.7, and the write half of F.17 |
| DFD processes realised    | 0.1 (0.1.1–0.1.4), 0.2 (0.2.1–0.2.5), 0.3 (0.3.1–0.3.4)       |
| Data stores owned         | D1. Users, D2. Images                                         |

## **1.1 Purpose**

M1 owns everything that happens between a person arriving at TruePixels.rgb and a normalised tensor being ready for inference. It answers two questions, in order: who is this, and is what they gave us usable.

Analogy: airport check-in and security. Identity is verified once at the desk (authentication); the bag is inspected against a published list of what may be carried (validation); and what passes is repacked into the standard container the aircraft hold accepts (preprocessing). Nothing further down the chain re-inspects the bag — which is also the responsibility: if an unsupported or corrupted file reaches M2, that is an M1 defect, not an M2 defect.

## **1.2 Role in the overall project**

M1 is the first tier-1 module of the Structured Chart and sits directly under Root. It has one outbound data contract (to M2), one service contract it publishes to both other modules (session and role resolution), and one obligation to M3 (log emission).

    User / Administrator
      |
      v
    +-------------------------------------------+
    | M1 Image & Access Management               |
    | 1.1 User Authentication & Access  --> SessionContext (to M2, M3)
    | 1.2 Image Upload & Validation                |
    | 1.3 Image Preprocessing           --> PreprocessedImage (to M2)
    +-------------------------------------------+
         |                  |
         v                  v
     D1. Users          D2. Images

## **1.3 Problem it solves**

Every request into TruePixels.rgb needs two independent guarantees before any classification work is worth doing: that the caller is who they claim to be (and is allowed to do what they're asking), and that the uploaded file is a genuine, decodable, appropriately-sized still image rather than an accident or an attack. M1 is the single place both guarantees are established, so no other module has to re-derive or re-check either one.

## **1.4 Responsibilities**

- Account creation with server-side validation and uniqueness enforcement (FR-01).

- Credential verification and session establishment for users (FR-02) and administrators (FR-03).

- Role-based authorisation enforced at the request boundary for every protected endpoint in the system, including endpoints owned by M2 and M3 (FR-04).

- Receipt of uploaded still images and their persistence as file references with metadata in D2 (FR-05).

- Four-stage validation — format, size, integrity, accept/reject — before anything downstream sees the file (FR-06).

- Deterministic preprocessing into the tensor form the CLIP branch expects, plus preservation of the native-resolution original for the frequency branch (FR-07).

- Execution of administrator-initiated account state changes against D1 (FR-08, the write half of F.17).

## **1.5 What this component does NOT handle**

- Any classification, scoring or fusion logic — owned by M2.

- Explainability, history views, PDF reports, the administrator dashboard and analytics — owned by M3.

- The administrator-facing screens for account management. M1 provides the endpoint; M3 renders the screen.

- Reading D6. Logs. M1 emits log events but never queries them.

- Password reset and email verification. Neither appears in the SRS; both are recorded as Future Scope, not silently implemented.

# **2. Scope**

## **2.1 In Scope**

- FR-01 User Registration — account creation with uniqueness and password-policy validation.

- FR-02 / FR-03 User and Administrator Authentication — credential verification and session issuance.

- FR-04 Role-Based Access Control — authorisation enforced at the request boundary for every protected route in the whole system, not only M1's own routes.

- FR-05 Image Upload — receipt and persistence of uploaded still images as file references with metadata in D2.

- FR-06 Input Validation — format, size and integrity checks, with a rejection reason recorded for every failure.

- FR-07 Image Preprocessing — deterministic tensor preparation for the CLIP branch, plus the untouched native-resolution original for the frequency branch.

- FR-08 Account state changes (enable / disable / remove) executed against D1 on an administrator's instruction.

**\[IMPLEMENTATION CHOICE\]** A minimum-dimension rejection (shorter side \< 64 px) and an explicit decoder pixel ceiling are implemented as part of FR-06 even though the SRS does not state them. They are proposed as a new constraint C.9 for the next SRS revision (source PRD item M1-A) but are already enforced.

## **2.2 Out of Scope**

- Semantic feature extraction, frequency-artifact analysis, decision fusion and confidence scoring — M2 (F.8, F.9).

- Explainability visualisation, results view, prediction history, PDF reports, administrator dashboard, logging storage and analytics — M3 (F.10, F.11, F.13–F.16, F.18).

- The administrator screens that call FR-08's endpoint — M3 renders them; M1 only exposes the endpoint.

- Reading or querying D6. Logs — M3 owns the read side; M1 only emits.

- Model registry and AI model management (F.19) — M2.

## **2.3 Future Scope**

- Federated or social login (explicitly a non-goal for release 1).

- Multi-image or batch upload — NF.12 lists batch processing as a future enhancement; the D2 schema does not preclude it, but the endpoint accepts exactly one file per request today.

- Password reset and email verification — absent from the SRS entirely; recorded as a candidate enhancement, not implemented.

- Deduplication reuse: whether a duplicate upload (identical content_sha256) should reuse an existing prediction rather than trigger fresh inference. Deferred because it interacts with F.13 history semantics and with model version changes.

# **3. Functional Requirements**

Each requirement below realises one SRS functional requirement (cross-referenced) and one or more DFD processes.

### **FR-01 — User Registration (realises F.1, DFD 0.1.1)**

| **Aspect** | **Specification**                                                                                                                                                                                                                                                                            |
|------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input      | full_name, email, account_password                                                                                                                                                                                                                                                           |
| Validation | full_name: 2–120 characters after trimming. email: syntactic check plus case-insensitive uniqueness against D1 (CITEXT column). password: minimum 10 characters, at least one letter and one digit, rejected if present in a bundled list of the 10,000 most common passwords.               |
| Processing | Normalise email to lowercase; hash the password with Argon2id; insert into D1 with role "User" and account_status "active". The unique index on D1.email is the actual uniqueness guarantee; the application-level check exists only to produce a friendly message ahead of a possible race. |
| Output     | Registration confirmation with the new user_id, or a validation error naming the specific failing field.                                                                                                                                                                                     |
| Errors     | AUTH_EMAIL_TAKEN (409) on a duplicate email, resolved from a translated unique-constraint violation rather than a generic 500; field validation errors (422).                                                                                                                                |
| Logging    | event_type "authentication", severity "info" on success, "warning" on a duplicate-email attempt.                                                                                                                                                                                             |

### **FR-02 — User Authentication (realises F.2, DFD 0.1.2)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                       |
|-------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | email, account_password                                                                                                                                                                                                                                                                                                                 |
| Processing  | Look up by normalised email; verify the password against the stored Argon2id hash; check account_status; issue a session token.                                                                                                                                                                                                         |
| Output      | auth-result = session token + user_id + role + expires_at, or an authentication failure message.                                                                                                                                                                                                                                        |
| Errors      | AUTH_INVALID_CREDENTIALS (401); AUTH_ACCOUNT_DISABLED (403) for a disabled or removed account with otherwise correct credentials.                                                                                                                                                                                                       |
| Constraints | When the email is not found, the server still performs a dummy Argon2id verification against a fixed dummy hash before returning, and the failure message and HTTP status are identical for "unknown email" and "wrong password". Without this, the login endpoint becomes an account-enumeration oracle through a timing side channel. |
| Logging     | Every attempt, successful or not. On failure the email is recorded; the submitted password never is.                                                                                                                                                                                                                                    |

### **FR-03 — Administrator Authentication (realises F.3, DFD 0.1.3)**

| **Aspect** | **Specification**                                                                                                                                                                                                                                |
|------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input      | Administrator email, account_password                                                                                                                                                                                                            |
| Processing | Same credential store and verification path as FR-02, on a distinct endpoint, with an additional assertion that role = "Admin". There is no separate administrator table — a single D1 with a role column is what the Data Dictionary specifies. |
| Output     | An authenticated administrative session, or an access-denied message.                                                                                                                                                                            |
| Errors     | AUTH_INVALID_CREDENTIALS (401) for a wrong password; AUTH_FORBIDDEN (403) for a correct password on a non-admin account — logged at severity "warning" since it is a signal worth surfacing on the administrator dashboard.                      |

### **FR-04 — Role-Based Access Control (realises F.4, DFD 0.1.4)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                       |
|-------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | Authenticated session (validated token) and associated role; requested resource.                                                                                                                                                                                                                        |
| Processing  | Implemented as two FastAPI dependencies, current_session() and require_role(role), exported from shared/deps.py and imported by all three modules. The role travels on the validated session token; there is no per-request round trip to M1. Both dependencies raise before the handler body executes. |
| Output      | Granted or denied access to the requested resource.                                                                                                                                                                                                                                                     |
| Errors      | AUTH_TOKEN_INVALID (401) for a missing, malformed or expired token; AUTH_FORBIDDEN (403) for an authenticated principal with the wrong role; AUTH_ACCOUNT_DISABLED (403) if the account is no longer active.                                                                                            |
| Constraints | current_session()/require_role() answer only "who is this?", never "may this person see record N?" — record-level ownership checks belong to whichever module owns the record (e.g. FR-03 in PRD 3 restricts history to the caller's own predictions).                                                  |

### **FR-05 — Image Upload (realises F.5, DFD 0.2.1)**

| **Aspect** | **Specification**                                                                                                                                                                                                                                                                                                    |
|------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input      | multipart/form-data with exactly one file part (JPG, JPEG or PNG).                                                                                                                                                                                                                                                   |
| Processing | Streams the body to a temporary file, aborting the moment the byte count exceeds the configured cap — the request body is never fully buffered in memory first. Computes the SHA-256 of the content during the same pass. Inserts a D2 row with validation_status "pending" so a rejected upload is still auditable. |
| Output     | Acknowledgement that the image was received for processing (with image_id), or a rejection message.                                                                                                                                                                                                                  |
| Errors     | IMG_FORMAT_UNSUPPORTED, IMG_TOO_LARGE, IMG_CORRUPTED — assigned during FR-06.                                                                                                                                                                                                                                        |

### **FR-06 — Input Validation (realises F.6 and C.1, DFD 0.2.2–0.2.5)**

| **Aspect**                 | **Specification**                                                                                                                                                                                                                                                                                                                                                                              |
|----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input                      | The temporary uploaded file from FR-05.                                                                                                                                                                                                                                                                                                                                                        |
| Processing — format        | Determined by inspecting leading bytes, never the filename or client-supplied MIME type. JPEG = FF D8 FF ... FF D9; PNG = 89 50 4E 47 0D 0A 1A 0A. Anything else is IMG_FORMAT_UNSUPPORTED.                                                                                                                                                                                                    |
| Processing — size          | Byte size bounded by a configured maximum (see §4 configuration). Pixel dimensions are also bounded: shorter side must be ≥ 64 px (rejects a thumbnail upsampled into a blurred, spectrally-empty image), and an explicit decoder pixel ceiling guards against decompression bombs (e.g. a 50,000×50,000 PNG that is a few hundred KB on disk but many GB decoded).                            |
| Processing — integrity     | Integrity means the file decodes fully, not that its header parses. Pillow's verify() alone is insufficient (checks structure without decompressing pixel data). Both a verify() pass and a full load() pass are required; any exception from either is IMG_CORRUPTED, and warnings Pillow would normally suppress are promoted to errors.                                                     |
| Processing — accept/reject | On acceptance: move the temp file to its permanent content-addressed path, set validation_status "valid", record width/height/format, strip EXIF metadata, and return the image_id. On rejection: set validation_status "invalid", record rejection_reason from the closed set {unsupported-format, file-too-large, corrupted-file}, delete the temp file, and return the corresponding error. |
| Output                     | A validated D2 row, or a specific rejection reason.                                                                                                                                                                                                                                                                                                                                            |
| Errors                     | IMG_FORMAT_UNSUPPORTED (415), IMG_TOO_LARGE (413), IMG_CORRUPTED (422).                                                                                                                                                                                                                                                                                                                        |

### **FR-07 — Image Preprocessing (realises F.7, DFD 0.3.1–0.3.4)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | A validated image (file reference from FR-06).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Processing  | 0.3.1 load original, apply EXIF orientation, convert to three-channel RGB (palette/greyscale/CMYK/RGBA all collapse here). 0.3.2 resize: shorter side to 224 px with bicubic resampling, then a 224×224 centre crop (reproduces CLIP's own preprocessing; a direct squash would distort the aspect ratio and shift the embedding off-distribution). 0.3.3 normalise: scale to \[0,1\], then subtract the CLIP per-channel mean (0.48145466, 0.4578275, 0.40821073) and divide by the CLIP per-channel std (0.26862954, 0.26130258, 0.27577711) — ImageNet statistics are an easy, silent mistake here. 0.3.4 transpose to (C,H,W), cast to float32, persist as .npy, assemble the PreprocessedImage structure carrying both tensor_ref and source_reference. |
| Output      | PreprocessedImage (Contract C1) — see §7 and §10.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Constraints | The native-resolution original must be supplied alongside the resized tensor, never only the tensor. Resizing to 224×224 is a low-pass filter that removes exactly the high-frequency evidence the frequency-artifact classifier looks for; supplying only the tensor would silently cripple half of M2's hybrid framework and the damage would surface as a weak model in M2 rather than a preprocessing defect in M1.                                                                                                                                                                                                                                                                                                                                      |
| Determinism | The resampling filter is named explicitly in code, never left to a library default. Pillow and NumPy versions are pinned. No random cropping, no augmentation, no jitter at inference time.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

### **FR-08 — Account State Change (write half of F.17, DFD 0.7.2 M1 side)**

| **Aspect** | **Specification**                                                                                                                                                                                                                                                                                            |
|------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input      | Administrator session; target user_id; action ∈ {enable, disable, remove}.                                                                                                                                                                                                                                   |
| Processing | PATCH /api/v1/users/{user_id}/status, Admin-only. "remove" sets account_status = "removed" — it does not delete the row, because D4 predictions reference D2 images which reference D1 users, and an audit trail that erases itself is not an audit trail. An administrator may not change their own status. |
| Output     | Updated account_status, e.g. { "user_id": 42, "account_status": "disabled" }.                                                                                                                                                                                                                                |
| Errors     | AUTH_FORBIDDEN (non-admin caller); ADM_ACTION_NOT_PERMITTED (409) for self-modification, preventing the last administrator locking the system out of itself.                                                                                                                                                 |

**\[DECISION REQUIRED\]** Whether a status change takes effect immediately or only on the token's next validation depends on the session-token mechanism (see OI-3 under §4 Technical Requirements). This must be resolved before FR-08 can be called correct.

# **4. Technical Requirements**

| **Category**              | **Requirement**                                                                                                                                                                               |
|---------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Language / runtime        | Python 3.11 (backend); server host may be Windows, Linux or macOS (SRS §3.2.3).                                                                                                               |
| Framework                 | FastAPI; Pydantic v2 for request/response schemas; SQLAlchemy 2.x ORM; Alembic for migrations.                                                                                                |
| Libraries                 | Pillow (decode, EXIF handling, resize); NumPy (tensor assembly); argon2-cffi (primary password hashing) with passlib\[bcrypt\] as a documented fallback if the argon2 binding is unavailable. |
| Database                  | PostgreSQL 15, with the citext extension enabled for case-insensitive email uniqueness.                                                                                                       |
| Hardware — server minimum | Intel Core i3 (or equivalent), 4 GB RAM, 2 GB free storage (SRS §3.2.2).                                                                                                                      |
| Hardware — recommended    | Intel Core i5 / AMD Ryzen 5 or higher, 8 GB RAM, 5 GB free storage. A CUDA-enabled GPU is recommended system-wide for M2's inference workload; M1 itself has no GPU dependency.               |
| Transport                 | HTTPS in deployment; session tokens carried only in the Authorization header, never in a query string.                                                                                        |
| Shared infrastructure     | A filesystem volume reachable by both the upload path (M1) and the inference path (M2) for tensor_ref and source_reference resolution.                                                        |

## **4.1 Configuration**

**\[DECISION REQUIRED\]** Maximum upload file size (source PRD open issue OI-2). Proposed value: 10 MB. No implementation should proceed without this number fixed, since the browser-side and server-side checks must agree.

**\[DECISION REQUIRED\]** Session token mechanism (source PRD open issue OI-3): signed JWT versus a server-side session row. This determines whether FR-08 account-disable and FR-04 revocation take effect immediately or only at next token validation. Default if left undecided at the relevant checkpoint: server-side session rows, because immediate revocation is the safer failure mode.

Fixed configuration values already decided:

- Session token lifetime: 8 hours from issuance, carried in SessionContext.expires_at.

- Minimum accepted image dimension: shorter side ≥ 64 px (implementation choice ahead of a formal SRS constraint, see §2.1).

## **4.2 Security Configuration**

| **Control**      | **Decision**                                                                                                                             | **Rationale**                                                                                                                                                                                   |
|------------------|------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Password hashing | Argon2id — memory 64 MiB, time cost 3, parallelism 4. bcrypt cost 12 as fallback.                                                        | Memory-hard by design, which is what makes GPU brute force expensive. A general-purpose hash such as SHA-256 is unsuitable regardless of salting because its speed is the attacker's advantage. |
| Salting          | Per-password random salt, stored inside the Argon2id hash string.                                                                        | Handled by the algorithm; no separate column, no home-made scheme.                                                                                                                              |
| Session token    | Opaque to every module except M1. Mechanism per OI-3 above.                                                                              | A signed JWT cannot be revoked before expiry; a server-side session row can.                                                                                                                    |
| Transport        | HTTPS in deployment; token in Authorization header only.                                                                                 | A token in a query string ends up in server logs, browser history and referrer headers.                                                                                                         |
| Throttling       | Exponential backoff after 5 consecutive failed attempts for the same email or source address.                                            | Returns AUTH_INVALID_CREDENTIALS with added delay rather than a distinct error code, to avoid a contract change.                                                                                |
| Upload safety    | Magic-byte sniffing, streamed size cap, explicit decoder pixel limit, content-addressed storage paths, EXIF stripped from stored copies. | The upload endpoint is the largest untrusted-input surface in the system.                                                                                                                       |

# **5. Architecture / Internal Workflow**

M1 executes three sub-modules in a fixed pipeline order. Authentication and authorisation (1.1) gate every request; upload and validation (1.2) and preprocessing (1.3) run only for authenticated users submitting an image.

    Input: registration / login / image-upload request
       |
       v
    1.1  User Authentication & Access   (0.1.1-0.1.4)
       |  -- issues SessionContext --
       v
    1.2  Image Upload & Validation      (0.2.1-0.2.5)
       |  -- format / size / integrity / accept-reject --
       v
    1.3  Image Preprocessing            (0.3.1-0.3.4)
       |  -- resize / normalize / tensor assembly --
       v
    Output: PreprocessedImage --> M2   |   SessionContext --> M2, M3

Sub-module 1.1 is also invoked, independently of the upload path, whenever any protected endpoint anywhere in the system (including M2 and M3 endpoints) is called — its current_session()/require_role() dependencies sit in front of every non-public route in the application.

# **6. Module Breakdown**

Internal package layout: app/m1_access/{router_auth.py, router_images.py, router_users.py, security.py, validation.py, preprocess.py, storage.py, models.py, schemas.py}

| **Module**       | **Purpose**                                                                                                                                                | **Inputs**                               | **Outputs**                                      | **Depends on**                       |
|------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------|--------------------------------------------------|--------------------------------------|
| security.py      | Password hashing/verification, session token issue & verify, and the current_session()/require_role() dependencies used across all three project modules.  | Raw password, stored hash, request token | Verified session / SessionContext; auth decision | D1 (Users) via models.py             |
| router_auth.py   | HTTP endpoints for FR-01, FR-02, FR-03 (register, login, admin login, logout, session introspection).                                                      | HTTP requests                            | auth-result / registration confirmation          | security.py, models.py, schemas.py   |
| router_users.py  | HTTP endpoint for FR-08 (admin account state change).                                                                                                      | Admin session, target user_id, action    | Updated account_status                           | security.py, models.py               |
| validation.py    | FR-06: format, size and integrity checks (DFD 0.2.2–0.2.5).                                                                                                | Temporary uploaded file                  | validation_status, rejection_reason              | Pillow                               |
| router_images.py | HTTP endpoint for FR-05, orchestrates streaming receipt and calls validation.py and storage.py.                                                            | multipart upload                         | image_id, validation_status                      | validation.py, storage.py, models.py |
| preprocess.py    | FR-07: prepare_model_input() — the DFD 0.3.1–0.3.4 pipeline and the Contract C1 producer.                                                                  | Validated image file reference           | PreprocessedImage                                | Pillow, NumPy                        |
| storage.py       | Content-addressed blob store: uploads/\<sha\[0:2\]\>/\<sha\[2:4\]\>/\<sha\>.\<ext\>. Guarantees no attacker-supplied filename ever reaches the filesystem. | File bytes, content hash                 | file_reference (path)                            | —                                    |
| models.py        | SQLAlchemy models for D1 (Users) and D2 (Images), the only writer of both.                                                                                 | —                                        | ORM row objects                                  | PostgreSQL                           |
| schemas.py       | Pydantic request/response models, including PreprocessedImage, NormalizationParams and SessionContext (shared with M2/M3 via shared/schemas.py).           | —                                        | —                                                | Pydantic v2                          |

# **7. Data Requirements**

## **7.1 D1. Users (schema owner: M1)**

    CREATE EXTENSION IF NOT EXISTS citext;
    CREATE TABLE users ( -- D1
      user_id BIGSERIAL PRIMARY KEY,
      full_name VARCHAR(120) NOT NULL,
      email CITEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      role VARCHAR(10) NOT NULL DEFAULT 'User' CHECK (role IN ('User','Admin')),
      account_status VARCHAR(10) NOT NULL DEFAULT 'active'
        CHECK (account_status IN ('active','disabled','removed')),
      registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

**\[DECISION REQUIRED\]** citext availability in the deployment database (source PRD item M1-D). Fallback if the extension cannot be enabled: a generated lowercase column with a unique index, decided before the first migration.

## **7.2 D2. Images (schema owner: M1)**

    CREATE TABLE images ( -- D2
      image_id BIGSERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
      file_reference TEXT NOT NULL,
      content_sha256 CHAR(64) NOT NULL,
      file_format VARCHAR(5) NOT NULL CHECK (file_format IN ('JPG','JPEG','PNG')),
      file_size BIGINT NOT NULL,
      width INTEGER,
      height INTEGER,
      upload_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      validation_status VARCHAR(10) NOT NULL
        CHECK (validation_status IN ('pending','valid','invalid')),
      rejection_reason VARCHAR(32)
        CHECK (rejection_reason IS NULL OR rejection_reason IN
          ('unsupported-format','file-too-large','corrupted-file'))
    );
    CREATE INDEX idx_images_user_time ON images (user_id, upload_timestamp DESC);
    CREATE INDEX idx_images_sha ON images (content_sha256);

Three columns extend the SRS Data Dictionary's definition of D2, each for a stated reason: content_sha256 enables deduplication and a deterministic storage path; width/height support the FR-06 dimension check and let M3 scale an explainability overlay back to original geometry; rejection_reason gives the Data Dictionary's rejection-reason data flow somewhere to live, so FR-06 rejections are auditable. idx_images_user_time exists because per-user history (owned by M3) is always a reverse-chronological, per-user query.

## **7.3 Produced data structures**

These structures are defined here because M1 is their producer; their role as cross-module contracts is detailed in §10 and formally owned by PRD 4.

    class PreprocessedImage(BaseModel):
        image_id: int              # FK to D2.images
        user_id: int                # owner, for authorisation and D4 linkage
        tensor_ref: str              # path to a .npy on the shared volume
        shape: tuple[int, int, int]  # (C, H, W) = (3, 224, 224)
        dtype: Literal["float32"]
        normalization: NormalizationParams
        source_reference: str        # path to the ORIGINAL decoded image
        created_at: datetime
     
    class NormalizationParams(BaseModel):
        mean: tuple[float, float, float]
        std: tuple[float, float, float]
        scheme: Literal["clip_openai", "imagenet"]
     
    class SessionContext(BaseModel):
        user_id: int
        email: str
        role: Literal["User", "Admin"]
        account_status: Literal["active", "disabled", "removed"]
        session_token: str
        issued_at: datetime
        expires_at: datetime

# **8. Algorithms / Processing Logic**

## **8.1 Password hashing and timing-safe verification**

- Argon2id with memory 64 MiB, time cost 3, parallelism 4 (§4.2). Deliberately expensive: verification cost is required to be ≥ 50 ms per attempt so that a fast hash cannot be brute-forced in bulk.

- On login, when the submitted email is not found in D1, the code still performs a dummy Argon2id verification against a fixed dummy hash before returning, and returns the identical message/status as a wrong-password case. This removes the timing side channel that would otherwise let the login form be used to enumerate registered emails.

## **8.2 Image format detection (magic-byte sniffing)**

Format is determined purely from leading file bytes, never from filename extension or client-supplied Content-Type:

- JPEG: FF D8 FF … and the file must end with FF D9.

- PNG: 89 50 4E 47 0D 0A 1A 0A.

- Anything else → IMG_FORMAT_UNSUPPORTED. The declared extension is retained in the D2 row for diagnostics only.

## **8.3 Integrity verification (two-pass decode)**

    with Image.open(tmp) as im:
        im.verify()      # structural check; invalidates the handle
    with Image.open(tmp) as im:   # reopen: verify() cannot be followed by load()
        im.load()          # forces full pixel decode -> truncation surfaces here
        width, height = im.size

Any exception from either pass is IMG_CORRUPTED. This two-pass approach exists because Pillow's verify() alone checks structure without decompressing pixel data — a JPEG truncated at 60% of its length passes verify() and would otherwise fail deep inside M2 instead.

## **8.4 Image preprocessing pipeline (FR-07 detail)**

| **Step** | **Operation**           | **Detail**                                                                                                                                                                                                       |
|----------|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0.3.1    | Receive validated image | Load from file reference; apply EXIF orientation; convert to RGB. Palette, greyscale, CMYK and RGBA all collapse to three channels here — later stages assume RGB unconditionally.                               |
| 0.3.2    | Resize                  | Shorter side to 224 px, bicubic resampling, then a 224×224 centre crop. Reproduces CLIP's own preprocessing; a direct squash to 224×224 would distort the aspect ratio and shift the embedding off-distribution. |
| 0.3.3    | Normalize               | Scale to \[0,1\]; subtract CLIP mean (0.48145466, 0.4578275, 0.40821073) and divide by CLIP std (0.26862954, 0.26130258, 0.27577711), per channel.                                                               |
| 0.3.4    | Prepare model input     | Transpose to (C, H, W); cast to float32; persist as .npy; assemble PreprocessedImage carrying both tensor_ref and source_reference.                                                                              |

**\[IMPLEMENTATION CHOICE\]** The resampling filter is pinned in code (never a library default) and Pillow/NumPy versions are pinned, so that a minor library release cannot silently change every tensor the system produces. No random cropping, augmentation or jitter is applied at inference time.

# **9. Internal Interfaces**

Communication between M1's own sub-modules (all in-process, no HTTP hop):

| **Source**              | **Destination**                   | **Interface**                                           | **Behaviour**                                                                                                                                       |
|-------------------------|-----------------------------------|---------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| 1.1 Auth & Access       | 1.2 Upload & Validation           | current_session() dependency result (SessionContext)    | Attaches the authenticated user_id to every uploaded image; upload is rejected before it starts if the dependency raises.                           |
| 1.2 Upload & Validation | 1.3 Preprocessing                 | Validated image file reference (image_id, storage path) | 1.3 only runs against images with validation_status "valid"; it performs no re-validation of its own.                                               |
| security.py             | router_images.py, router_users.py | current_session() / require_role(role) dependencies     | Raise before the handler body executes on any auth or role failure; both are exported from shared/deps.py for reuse by M2 and M3 as well (see §10). |

# **10. External Interfaces**

Interfaces M1 exposes to (or consumes from) M2 and M3. Full cross-module contracts are the authority of PRD 4; this section states M1's side of each one.

| **Contract**                         | **Direction**                          | **What crosses the boundary**                                                                                                                                                                                                                                                                                     |
|--------------------------------------|----------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| C1 — Preprocessed image              | M1 → M2 (in-process call, no HTTP hop) | prepare_model_input(image_id, session) returns PreprocessedImage. M1 guarantees: the tensor exists with the declared shape/dtype; the underlying image passed all four FR-06 validation stages; source_reference is the losslessly-decoded original; the D2 row is committed before the structure is handed over. |
| C3 — Session and identity            | M1 → M2, M3 (shared/deps.py)           | current_session() and require_role(role) FastAPI dependencies, and the SessionContext structure. M1 is the only module that creates, validates or revokes a token.                                                                                                                                                |
| C3.3 — Administrative account writes | M3 → M1 (HTTP)                         | PATCH /api/v1/users/{user_id}/status, owned and implemented by M1, called by M3's admin UI. M1 issues no UI for this; M3 issues no direct write to D1.                                                                                                                                                            |
| C5 — Logging (M1 as emitter)         | M1 → M3 (in-process call)              | M1 calls M3's emit() for every registration, every login success/failure, every rejected upload with its rejection reason, and every 403 from the role check.                                                                                                                                                     |

## **10.1 Public REST API**

| **Method & path**               | **Auth**     | **Request**                | **Success**                          | **Errors**                                           |
|---------------------------------|--------------|----------------------------|--------------------------------------|------------------------------------------------------|
| POST /api/v1/auth/register      | public       | full_name, email, password | 201 + user_id                        | AUTH_EMAIL_TAKEN, 422                                |
| POST /api/v1/auth/login         | public       | email, password            | 200 + token, role, expires_at        | AUTH_INVALID_CREDENTIALS, AUTH_ACCOUNT_DISABLED      |
| POST /api/v1/auth/admin/login   | public       | email, password            | 200 + elevated token                 | AUTH_INVALID_CREDENTIALS, AUTH_FORBIDDEN             |
| POST /api/v1/auth/logout        | user         | —                          | 204                                  | AUTH_TOKEN_INVALID                                   |
| GET /api/v1/auth/me             | user         | —                          | 200 + SessionContext (token omitted) | AUTH_TOKEN_INVALID                                   |
| POST /api/v1/images             | user         | multipart file             | 201 + image_id, validation_status    | IMG_FORMAT_UNSUPPORTED, IMG_TOO_LARGE, IMG_CORRUPTED |
| GET /api/v1/images/{id}         | user (owner) | —                          | 200 + image metadata                 | IMG_NOT_FOUND                                        |
| PATCH /api/v1/users/{id}/status | admin        | action                     | 200 + account_status                 | AUTH_FORBIDDEN, ADM_ACTION_NOT_PERMITTED             |

GET /api/v1/images/{id} returns IMG_NOT_FOUND — not AUTH_FORBIDDEN — when the image exists but belongs to another user, so that a caller cannot use the error type to enumerate which image IDs exist.

# **11. Error Handling and Edge Cases**

Every failure in M1 exits through the shared error envelope (Contract C.3.4 of the Interface Contract):

    {
      "error": {
        "code": "IMG_FORMAT_UNSUPPORTED",
        "message": "Only JPG, JPEG and PNG images are accepted.",
        "request_id": "b41c0f7e-1d2a-4c31-9f88-6a2b0e4d1177"
      }
    }

| **Code**                 | **HTTP** | **Meaning**                                                       |
|--------------------------|----------|-------------------------------------------------------------------|
| AUTH_EMAIL_TAKEN         | 409      | Registration with an email already present in D1.                 |
| AUTH_INVALID_CREDENTIALS | 401      | Email or password did not match.                                  |
| AUTH_TOKEN_INVALID       | 401      | Missing, malformed or expired session token.                      |
| AUTH_FORBIDDEN           | 403      | Authenticated but role is insufficient for the resource.          |
| AUTH_ACCOUNT_DISABLED    | 403      | Account state is disabled or removed.                             |
| IMG_FORMAT_UNSUPPORTED   | 415      | File extension or sniffed content is not JPG/JPEG/PNG.            |
| IMG_TOO_LARGE            | 413      | File exceeds the configured maximum upload size or pixel ceiling. |
| IMG_CORRUPTED            | 422      | Decoder could not open the file, or the file is truncated.        |
| IMG_NOT_FOUND            | 404      | image_id does not exist, or is not owned by the caller.           |
| ADM_ACTION_NOT_PERMITTED | 409      | Administrative action rejected by policy (e.g. self-removal).     |

## **11.1 Handling rules**

1.  The user receives a message that names the cause and nothing about internals — no file paths, no stack frames, no library names, no SQL.

2.  The log receives the same message plus request_id, user_id when known, and internal detail. Never the password, never the token, never image bytes.

3.  An unexpected exception becomes a 500 with a generic message and a severity "error" log entry — never a leaked traceback in a JSON body.

## **11.2 Edge cases**

- Concurrent registration with the same email from two clients: exactly one succeeds; the other receives AUTH_EMAIL_TAKEN, not a 500 (the unique index is what actually enforces this, not the pre-check).

- A filename such as "../../etc/passwd.jpg": accepted or rejected on content, but stored at a content-addressed path — the supplied name never reaches the filesystem.

- An animated PNG: accepted, with its first frame used.

- A file exactly at the size cap: accepted; one byte over: IMG_TOO_LARGE.

- A polyglot file (e.g. GIF/JPEG or ZIP-with-JPEG-header): rejected as IMG_FORMAT_UNSUPPORTED or IMG_CORRUPTED depending on which check it fails first.

- An SVG containing a script tag, renamed to .png: rejected as IMG_FORMAT_UNSUPPORTED (magic-byte sniffing never inspects file content as markup).

# **12. Performance Requirements**

| **SRS ID**                | **Obligation on M1**                                                                                                                                           | **Verification**                                           |
|---------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------|
| NF.1 Response time        | Upload-to-validated ≤ 400 ms p95; preprocessing ≤ 150 ms p95.                                                                                                  | Instrumented server-side timers.                           |
| NF.4 Resource utilisation | Streamed upload, bounded decode, no whole-body buffering — a 10 MB upload must cost the server roughly 10 MB of reading, not the full request buffered in RAM. | Memory profile of a 10 MB upload; target peak under 60 MB. |

## **12.1 Success metrics**

| **ID** | **Metric**                       | **Target**                                                                                       |
|--------|----------------------------------|--------------------------------------------------------------------------------------------------|
| MM1.1  | Adversarial file corpus rejected | 100% (25/25 cases) — a single leak is a release blocker.                                         |
| MM1.2  | Valid-file false rejection rate  | 0, on a 200-image acceptance corpus spanning 64 px–8000 px and 4 KB–size cap.                    |
| MM1.3  | Upload-to-validated latency, p95 | ≤ 400 ms for a 5 MB file, excluding network transfer.                                            |
| MM1.4  | Preprocessing latency, p95       | ≤ 150 ms per image on CPU.                                                                       |
| MM1.5  | Preprocessing determinism        | Byte-identical tensor SHA-256 across 100 repeat runs and 2 hosts.                                |
| MM1.6  | Password verification cost       | ≥ 50 ms per attempt (deliberate floor).                                                          |
| MM1.7  | Authorisation coverage           | Every non-public route carries a role dependency, proven by an automated route-table audit test. |

# **13. Testing Requirements**

## **13.1 Unit tests**

- Password policy: accepted and rejected samples, including boundary lengths and a common-password hit.

- Hash round-trip: verify succeeds for the correct password, fails for a near-miss, and the stored string is never the plaintext password.

- Magic-byte sniffing across every combination of {real JPEG, real PNG, text file, zero bytes} × {claimed .jpg, claimed .png}.

- Colour-mode conversion: L, P, RGBA, CMYK and RGB inputs all yield a (3, 224, 224) float32 tensor.

- EXIF orientation: all eight orientation tags rotate to the same visual result.

## **13.2 Integration tests**

- Register → login → upload → preprocess, asserting the D1 and D2 rows and the returned PreprocessedImage.

- Contract test for C1, shared with M2: shape, dtype, normalisation scheme, and that source_reference resolves to the full-resolution original rather than the 224×224 copy.

- Route-table audit: every non-public route carries a role dependency (MM1.7).

- Concurrent registration with the same email from two clients: exactly one succeeds.

## **13.3 Adversarial corpus (25 checked-in cases, all must be rejected correctly)**

| **Case** | **File**                                                                                                                                                         | **Expected**                                                          |
|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| 1–3      | A PNG, a GIF and a PDF, each renamed to .jpg                                                                                                                     | IMG_FORMAT_UNSUPPORTED                                                |
| 4–5      | JPEG truncated at 30% and at 95% of its length                                                                                                                   | IMG_CORRUPTED                                                         |
| 6        | Valid JPEG header followed by random bytes                                                                                                                       | IMG_CORRUPTED                                                         |
| 7        | Zero-byte file with a .png extension                                                                                                                             | IMG_CORRUPTED                                                         |
| 8        | PNG decompression bomb, 50,000×50,000, ~400 KB on disk                                                                                                           | IMG_TOO_LARGE (dimension bound)                                       |
| 9        | File one byte over the size cap                                                                                                                                  | IMG_TOO_LARGE                                                         |
| 10       | A 40×30 thumbnail                                                                                                                                                | Rejected on the minimum-dimension rule                                |
| 11–12    | GIF/JPEG polyglot; ZIP with a JPEG header prepended                                                                                                              | IMG_FORMAT_UNSUPPORTED or IMG_CORRUPTED                               |
| 13       | Filename "../../etc/passwd.jpg"                                                                                                                                  | Accepted/rejected on content only; stored at a content-addressed path |
| 14       | SVG containing a script tag, renamed .png                                                                                                                        | IMG_FORMAT_UNSUPPORTED                                                |
| 15–25    | Valid controls: greyscale, CMYK, RGBA, palette, progressive JPEG, interlaced PNG, 16-bit PNG, EXIF-rotated, exactly 64 px, exactly at the size cap, animated PNG | All accepted except the animated PNG uses its first frame             |

## **13.4 Performance tests**

- Twenty concurrent 5 MB uploads: p95 upload-to-validated latency and peak server memory recorded against MM1.3 and NF.4.

- One hundred repeat preprocessing runs on a fixed image across two hosts, comparing tensor SHA-256 (MM1.5).

# **14. Acceptance Criteria**

## **AC group 1 — Registration (FR-01)**

**AC-01.** *Given* a well-formed name, an unused email and a compliant password*, when* I submit registration*, then* a D1 row is created with role "User" and account_status "active", and I receive a confirmation.

**AC-02.** *Given* an email that already exists in D1 under any letter casing*, when* I submit registration*, then* it fails with AUTH_EMAIL_TAKEN and no row is created.

**AC-03.** *Given* a password shorter than the configured minimum*, when* I submit registration*, then* it fails with a message naming the specific rule that failed, not a generic "invalid input".

**AC-04.** *Given* any registration attempt, successful or not*, when* the response, log entry or database is inspected*, then* the submitted password is never present in a reversible form.

## **AC group 2 — Login (FR-02)**

**AC-05.** *Given* correct credentials on an active account*, when* I log in*, then* I receive a session token carrying my user_id and role, and an expiry timestamp.

**AC-06.** *Given* a wrong password, or an email that is not registered at all*, when* I attempt to log in*, then* both cases return the identical message and identical HTTP status.

**AC-07.** *Given* a disabled or removed account with otherwise correct credentials*, when* I attempt to log in*, then* login fails with AUTH_ACCOUNT_DISABLED.

**AC-08.** *Given* any login attempt*, when* the attempt completes*, then* a D6 log event of type "authentication" is produced.

## **AC group 3 — Administrator login (FR-03)**

**AC-09.** *Given* credentials for an account with role "Admin"*, when* the admin login endpoint is called*, then* an elevated-privilege session is returned.

**AC-10.** *Given* valid credentials for an account with role "User"*, when* the admin login endpoint is called*, then* AUTH_FORBIDDEN is returned and the attempt is logged at severity "warning".

## **AC group 4 — Authorisation (FR-04)**

**AC-11.** *Given* a request with no token, an expired token or a tampered token*, when* any protected route is called*, then* AUTH_TOKEN_INVALID is returned before the handler body executes.

**AC-12.** *Given* a "User" token*, when* an admin route is called*, then* AUTH_FORBIDDEN is returned and the attempt is logged.

**AC-13.** *Given* the full FastAPI route table*, when* an automated test enumerates it*, then* the test fails if any non-public route lacks a role dependency.

## **AC group 5 — Upload and validation (FR-05, FR-06)**

**AC-14.** *Given* a valid JPG, JPEG or PNG within the size cap*, when* it is uploaded*, then* it is stored, produces a D2 row with validation_status "valid", and returns an image_id.

**AC-15.** *Given* a file whose extension says .jpg but whose bytes are not a JPEG*, when* it is uploaded*, then* it is rejected with IMG_FORMAT_UNSUPPORTED.

**AC-16.** *Given* a truncated or structurally broken image*, when* it is uploaded*, then* it is rejected with IMG_CORRUPTED, even when its header parses.

**AC-17.** *Given* a file above the size cap*, when* it is uploaded*, then* it is rejected with IMG_TOO_LARGE and the server stops reading the stream rather than buffering the whole body first.

**AC-18.** *Given* any rejected upload*, when* the rejection is recorded*, then* its reason is named in D2.rejection_reason and in a D6 log entry.

## **AC group 6 — Preprocessing (FR-07)**

**AC-19.** *Given* a validated image*, when* it is preprocessed*, then* the returned tensor is float32 with shape (3, 224, 224) and CLIP normalisation applied.

**AC-20.** *Given* the resulting PreprocessedImage*, when* source_reference is resolved*, then* it resolves to the decoded original at native resolution, never the resized copy.

**AC-21.** *Given* an image with an EXIF orientation tag*, when* it is preprocessed*, then* it is rotated to its display orientation before resizing.

**AC-22.** *Given* greyscale, palette-indexed, CMYK and RGBA inputs*, when* each is preprocessed*, then* all converge to a three-channel RGB tensor without raising.

**AC-23.** *Given* the same file*, when* the pipeline is repeated 100 times*, then* the SHA-256 of the resulting tensor is identical every time.

# **15. Definition of Done**

M1 is done when every acceptance criterion in §14 passes; MM1.1 through MM1.7 are met and recorded; the C1 contract test passes against both M2's stub and M2's real implementation; and no route in the application is reachable without a role decision having been made about it.

## **15.1 Milestones**

| **Milestone**              | **Deliverable**                                                                                       | **Gate**                                |
|----------------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------|
| M1.0 — Stubs               | prepare_model_input() stub returning a fixed valid PreprocessedImage; D1 and D2 migrations merged.    | Unblocks M2 and M3 against a real seam. |
| M1.1 — Auth                | FR-01–FR-04 complete; dependencies exported; route-table audit green.                                 | Integration checkpoint I1.              |
| M1.2 — Upload & validation | FR-05, FR-06 complete; adversarial corpus 25/25.                                                      | Integration checkpoint I1.              |
| M1.3 — Preprocessing       | FR-07 complete; C1 contract test green including the CLIPProcessor equivalence check with M2.         | Integration checkpoint I2.              |
| M1.4 — Admin write path    | FR-08 (write half of F.17); self-modification guard.                                                  | Integration checkpoint I5.              |
| M1.5 — Hardening           | Throttling, EXIF stripping, performance targets met, security checklist signed off by both reviewers. | Release candidate.                      |
