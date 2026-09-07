**PRODUCT REQUIREMENTS DOCUMENT**

**PRD 3 — Results & Reporting Management (M3)**

*for TruePixels.rgb — An AI-Generated Image Detection System*

| **Field**         | **Value**                                                                                |
|-------------------|------------------------------------------------------------------------------------------|
| Module / Division | M3 — Results & Reporting Management (Structured Chart, Figure 10; DFD processes 0.5–0.7) |
| Owner             | Debanshu Mitra (241IT019)                                                                |
| Team              | Amogh R Gowda (241IT008) · Anurag V Rao (241IT011) · Debanshu Mitra (241IT019)           |
| Version           | 1.0                                                                                      |
| Date              | 7 September 2026                                                                         |

**Parent documents:**

- SRS for TruePixels.rgb (IEEE 830-1998), v1.1

- Design Document using SA/SD Methodology for TruePixels.rgb — DFD Model, Data Dictionary and Structured Chart

- TruePixels.rgb — Module Interface Contract, v1.0 (defines Contracts C2, C3, C4, C5 referenced throughout)

Department of Information Technology

National Institute of Technology Karnataka, Surathkal

# **Table of Contents**

# **1. Component Overview**

| **Field**                 | **Value**                                                                    |
|---------------------------|------------------------------------------------------------------------------|
| Component name            | M3 — Results & Reporting Management                                          |
| SRS requirements realised | F.10, F.11, F.13, F.14, F.15, F.16, F.17 (interface), F.18, F.19 (interface) |
| DFD processes realised    | 0.5 (0.5.1–0.5.2), 0.6 (0.6.1–0.6.3), 0.7 (0.7.1–0.7.4)                      |
| Data stores owned         | D5. Explainability, D6. Logs                                                 |

## **1.1 Purpose**

M3 turns a prediction into something a person can act on, and gives an administrator visibility into the system. It covers three distinct jobs: explaining a prediction, presenting and preserving results for the user who owns them, and operating the system.

Analogy: if M1 is the check-in desk and M2 is the laboratory, M3 is the report the laboratory hands back plus the operations room the laboratory sits inside. The report has to be readable and honest about its own limits; the operations room has to show what happened without exposing anything it should not. Both obligations — legible to a non-expert, and disciplined about what it reveals — run through every part of this module.

**\[ASSUMPTION\]** M3 carries eight of the twenty SRS functional requirements against seven for M1 and four for M2. This is not accidental — the Structured Chart groups everything user-facing and everything administrative under one tier-1 module — but two things offset it: none of M3's work is open-ended research (unlike M2), and F.17/F.19 are surfaced by M3 but implemented elsewhere. If load still proves uneven, the analytics half of F.18 is the natural piece to reassign (source PRD item M3-E).

## **1.2 Role in the overall project**

    M2 --- InferenceOutput (scores + ActivationBundle) ---> M3
    M1 --- SessionContext -------------------------------> M3
    +------------------------------------------------------------+
    | M3 Results & Reporting Management                            |
    | 3.1 Explainability Generation (F.10)                          |
    | 3.2 Results & History Management (F.11, F.13, F.14)           |
    | 3.3 Reports & Administration (F.15, F.16, F.18)                |
    |     + admin UI over M1's F.17 and M2's F.19                   |
    +------------------------------------------------------------+
         |                    |
         v                    v
     D5. Explainability   D6. Logs

## **1.3 Problem it solves**

A prediction is not useful on its own — a non-expert user needs to understand what the verdict means and how much to trust it, needs to be able to find it again later, and needs a portable artefact to share outside the system. An administrator needs to see what the system is doing without querying the database directly. M3 is where a raw model output becomes a legible result, a personal record, and an operable system.

## **1.4 Responsibilities**

- Generating and storing an explainability visualisation from the activation state M2 exposes (FR-01).

- The results view: label, confidence, visualisation and status messages in a single presentation (FR-02).

- Per-user prediction history, strictly scoped to the requesting account (FR-03).

- Downloadable PDF reports for predictions the requester owns (FR-04).

- Ownership of D6 and the emit() interface every module logs through (FR-05).

- The administrator dashboard, log review and monitoring views (FR-06).

- Aggregate analytics over predictions and logs (FR-07).

- Administrator screens for account management and model management, calling M1 and M2 respectively (FR-08, FR-09).

## **1.5 What this component does NOT handle**

- Running any model or producing any score — M3 renders what M2 computed and never recomputes it.

- Writing to D1, D2, D3 or D4 — every such write goes through the owning module's endpoint.

- Authentication and token validation — M3 consumes SessionContext and trusts it (M1 owns Contract C3).

- Record-level ownership enforcement is delegated to M3 by contract, not skipped: it is M3's primary security obligation (§11) precisely because no other module can perform it on M3's behalf.

# **2. Scope**

## **2.1 In Scope**

- FR-01 Generating and storing an explainability visualisation from M2's activation state (F.10).

- FR-02 The results view: verdict, confidence, visualisation and status message (F.11).

- FR-03 Per-user prediction history, strictly scoped to the requesting account (F.13).

- FR-04 Downloadable PDF reports for predictions the requester owns (F.14).

- FR-05 Ownership of D6 and the emit() logging interface used by all three modules (F.15).

- FR-06 The administrator dashboard, log review and monitoring views (F.16).

- FR-07 Aggregate analytics over predictions and logs (F.18).

- FR-08 / FR-09 Administrator screens for account management and model management, calling M1's and M2's endpoints respectively (F.17, F.19 — interface halves only).

## **2.2 Out of Scope**

- Semantic/frequency classification, decision fusion and confidence computation — M2 (F.8, F.9).

- Image upload, validation and preprocessing, and the write side of account status changes — M1 (F.5, F.6, F.7, F.17 write half).

- The model registry's write side — M2 (F.19 write half); M3 never writes D3.

- Any direct write to D1, D2, D3 or D4 — M3 issues no write to any store it does not own.

## **2.3 Future Scope**

- Real-time dashboard streaming — polling on refresh is sufficient at the stated scale; explicit non-goal.

- Report customisation, branding or templating — one clear layout only, for release 1.

- Log export to an external SIEM, alerting, or retention automation beyond the documented policy (§7.2).

- Explaining the model in general, as opposed to one prediction on one image — F.10 is scoped to single-prediction explanation only.

- A nightly pre-aggregated analytics table, if the direct-query approach does not meet MM3.6 at realistic volume (source PRD item M3-D) — decide from measurement, not in advance.

# **3. Functional Requirements**

### **FR-01 — Explainability Generation (realises F.10 and C.3, DFD 0.5.1–0.5.2)**

| **Aspect**        | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
|-------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input             | InferenceOutput with activations != None (Contract C2).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Processing        | 1\) Build a token-level relevance vector via attention rollout or gradient-weighted attribution (see §8.1). 2) Drop the CLS token; reshape the remainder to the patch grid (e.g. 7×7). 3) Normalise to \[0,1\] over the map. 4) Upsample bicubically to the ORIGINAL image dimensions — read width/height from D2, never from the 224×224 tensor. 5) Apply a perceptually-uniform colormap; alpha-blend over the original at ~0.45 opacity. 6) Render a second panel for the frequency branch: the log-magnitude spectrum with the radial bands that drove frequency_score marked. 7) Write PNGs to the blob store; insert D5 rows; return references. |
| Output            | Two D5 rows (one per branch) with visualization_reference, or XAI_UNAVAILABLE.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Timing            | Synchronous, in the same request as inference — the ActivationBundle is in-memory only and does not survive the request (Contract C2 §5.4). Only generated when requested (the results view requests it; a bulk history load reuses the stored D5 reference instead).                                                                                                                                                                                                                                                                                                                                                                                  |
| Constraints (C.3) | When activations comes back None despite being requested, M3 returns XAI_UNAVAILABLE, records a D6 entry at severity "warning", and the results view degrades gracefully — verdict and confidence are still shown, with a plain statement that no visualisation is available. A blank image is never shown; it would look like the model found nothing.                                                                                                                                                                                                                                                                                                |

### **FR-02 — Display Prediction Result (realises F.11, DFD 0.6.1)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                            |
|-------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | InferenceOutput (public half), D5 references.                                                                                                                                                                                                                                                                                                                                                                                |
| Processing  | Assembles the single results view: verdict (predicted_class, exact strings "Real" / "AI Generated" per C.2, no synonyms), confidence as a percentage to one decimal place with a qualitative band (high ≥ 85%, moderate 65–85%, low \< 65%), branch scores in an expandable secondary panel, the dual-panel visualisation beside the original image with a permanent interpretive caption, and a small model-version footer. |
| Output      | A rendered results view payload.                                                                                                                                                                                                                                                                                                                                                                                             |
| Constraints | The displayed percentage derives from confidence_score, never from fusion_score (Contract C2 §5.2) — the wrong field produces a plausible, wrong, confident-looking number.                                                                                                                                                                                                                                                  |

### **FR-03 — Prediction History (realises F.13, DFD 0.6.2)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                              |
|-------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | Authenticated user session.                                                                                                                                                                                                                                                                    |
| Processing  | Ownership is enforced as a WHERE clause inside the query itself, joining Prediction to Image on Image.user_id == session.user_id — never as a post-fetch filter (see §8.2 for why this distinction matters). No user_id request parameter exists on any user-facing history endpoint.          |
| Output      | A chronological, paginated list of the user's own predictions, newest first.                                                                                                                                                                                                                   |
| Constraints | Single-record fetches for a prediction owned by another user return INF_PREDICTION_NOT_FOUND, never a 403 — a 403 would confirm the record exists. Administrative views that legitimately span users live on separate, role-gated endpoints; the user endpoint never gains an admin-mode flag. |

### **FR-04 — Generate PDF Report (realises F.14, DFD 0.6.3)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                                              |
|-------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | A selected prediction_id, owned by the requester.                                                                                                                                                                                                                                                                                                              |
| Processing  | Assembles a PDF containing: header with system name and generation timestamp; the original image; verdict and confidence; both visualisation panels; branch scores; model name and version; prediction timestamp; the same interpretive caveat that appears in the results view (§8.3), because the report will be read by people who never saw the interface. |
| Output      | application/pdf, streamed to the client rather than assembled fully in memory.                                                                                                                                                                                                                                                                                 |
| Constraints | The same ownership predicate as FR-03 is applied before any rendering work starts. The same prediction yields the same report content on every generation — the generation timestamp is the only field that varies, and it is labelled as such.                                                                                                                |
| Errors      | INF_PREDICTION_NOT_FOUND for a prediction the requester does not own; RPT_GENERATION_FAILED, logged at severity "error", with no partial file ever returned, on an assembly failure.                                                                                                                                                                           |

### **FR-05 — System Logging (realises F.15)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                                                             |
|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | event_type, event_detail, severity, optional user_id and request_id, from any of the three modules.                                                                                                                                                                                                                                                                           |
| Processing  | emit() is synchronous, non-throwing and best-effort — it catches everything internally; a logging failure is written to stderr and the request continues (see §8.4). A redaction filter runs over event_detail before insertion, dropping anything matching password, token, authorization or bearer patterns. Reading D6 is itself logged as an administrative-action event. |
| Output      | A committed D6 row, or a swallowed failure that never propagates.                                                                                                                                                                                                                                                                                                             |
| Constraints | Retention: 90 days for severity "info", 1 year for "warning" and "error" (proposed policy, not yet in the SRS — see §4).                                                                                                                                                                                                                                                      |

### **FR-06 — Administrator Dashboard and Monitoring (realises F.16, DFD 0.7.1)**

| **Aspect** | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
|------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input      | Authenticated administrator session.                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Processing | Summary tiles (total predictions, predictions in the last 24 hours, class distribution, error count in the last 24 hours, active model versions per type) computed as bounded aggregate queries — never a select-everything-and-count-in-Python pattern, which works on a demo database and stops working at the scale MM3.6 is measured at. A recent-activity feed from D6, newest first. A log explorer filterable by event_type, severity and date range, paginated. |
| Output     | Aggregated monitoring views.                                                                                                                                                                                                                                                                                                                                                                                                                                            |

### **FR-07 — System Analytics (realises F.18, DFD 0.7.3)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
|-------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | Stored prediction and log data; an optional date range and metric selection.                                                                                                                                                                                                                                                                                                                                                                                                      |
| Processing  | Prediction count (total and per day); class distribution (Real vs AI Generated); usage over time (predictions per day, distinct active users per day); confidence-score distribution in ten bins (not required by F.18, but the actual signal an administrator needs to spot model drift); error rate from D6. Indexes on prediction_timestamp and on (event_type, log_timestamp) are mandatory — these queries scan the two largest tables and run on every dashboard page load. |
| Output      | Aggregated analytics views.                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Constraints | Analytics never expose credentials, password hashes or session tokens; only aggregates are shown, per F.18.                                                                                                                                                                                                                                                                                                                                                                       |

### **FR-08 — User Account Management — interface half (realises F.17 interface, DFD 0.7.2)**

| **Aspect**  | **Specification**                                                                                                                                                                                                                            |
|-------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input       | Administrator session; target user; enable/disable/remove action.                                                                                                                                                                            |
| Processing  | M3 renders the account table and calls M1's PATCH /api/v1/users/{id}/status (Contract C3.3). M3 issues no direct write to D1 and surfaces M1's AUTH_FORBIDDEN and ADM_ACTION_NOT_PERMITTED unchanged, including the self-modification guard. |
| Output      | Updated account state as returned by M1, or M1's error surfaced verbatim.                                                                                                                                                                    |
| Constraints | Destructive actions require an explicit confirmation step naming the target account.                                                                                                                                                         |

### **FR-09 — AI Model Management — interface half (realises F.19 interface, DFD 0.7.4)**

| **Aspect** | **Specification**                                                                                                                                                                                                                                                     |
|------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Input      | Administrator session; model artefact and metadata, or a target model_id to activate.                                                                                                                                                                                 |
| Processing | M3 renders the model list, upload form and activation control, calling M2's registry endpoints (Contract C4). It never writes D3, and it displays the metrics JSONB M2 recorded at registration so an administrator can see a version's numbers before activating it. |
| Output     | Registry state as returned by M2, or M2's error surfaced verbatim.                                                                                                                                                                                                    |

# **4. Technical Requirements**

| **Category**         | **Requirement**                                                                                                                |
|----------------------|--------------------------------------------------------------------------------------------------------------------------------|
| Language / runtime   | Python 3.11 backend (FastAPI); React 18 frontend.                                                                              |
| Libraries — backend  | NumPy, Pillow and Matplotlib (colormaps only) for the overlay; WeasyPrint or ReportLab for PDF generation.                     |
| Libraries — frontend | Recharts or Chart.js for the analytics views.                                                                                  |
| Database             | PostgreSQL 15 (shared instance; D5 and D6 owned by M3).                                                                        |
| Dependency on M2     | M2's ActivationBundle, including patch_grid and the spectrum, per Contract C2.                                                 |
| Dependency on M1     | M1's SessionContext, and the width/height columns in D2 — without them the overlay cannot be scaled back to original geometry. |

**\[DECISION REQUIRED\]** PDF generation library: WeasyPrint (HTML/CSS to PDF, reusing the results-view markup) or ReportLab (source PRD item M3-B). Needed by milestone M3.2.

**\[DECISION REQUIRED\]** Log retention policy — proposed 90 days for severity "info", 1 year for "warning"/"error" — is not yet in the SRS and needs confirmation or amendment (source PRD item M3-A). Needed by milestone M3.4.

**\[DECISION REQUIRED\]** Whether the frequency-spectrum panel is shown to General Users by default or only in the expandable panel — informative to an expert, potentially confusing to a novice (source PRD item M3-C). Needed by checkpoint I3.

**\[ASSUMPTION\]** D5 visualisations are stored as file references, consistent with the SRS Data constraint that images are referenced rather than stored as binary content in the database.

**\[ASSUMPTION\]** The administrator population is small, so per-administrator personalisation and fine-grained admin roles are unnecessary for release 1.

# **5. Architecture / Internal Workflow**

    Input: InferenceOutput (from M2, Contract C2) + SessionContext (from M1, Contract C3)
       |
       v
    3.1 Explainability Generation (0.5.1-0.5.2)  -- only when requested --> D5 rows
       |
       v
    3.2 Results & History Management (0.6.1-0.6.3)
       |    - Display Prediction Result (F.11)
       |    - Prediction History, scoped by session.user_id (F.13)
       |    - PDF report generation (F.14)
       v
    3.3 Reports & Administration (0.7.1-0.7.4)
            - System Logging (F.15, all modules write via emit())
            - Admin dashboard, log explorer (F.16)
            - Analytics (F.18)
            - Admin UI proxies to M1 (F.17) and M2 (F.19)

Explainability (3.1) executes synchronously inside the same request as inference, because the ActivationBundle does not survive the request boundary. The other two sub-modules (3.2, 3.3) operate independently, against already-persisted D4/D5/D6 data.

# **6. Module Breakdown**

Internal package layout: app/m3_results/{router_results.py, router_history.py, router_reports.py, router_admin.py, explain.py, overlay.py, reporting.py, analytics.py, logging_service.py, models.py}. Frontend: ResultView, HistoryList, AdminDashboard, and a shared ErrorBanner.

| **Module**                       | **Purpose**                                                                         | **Inputs**                     | **Outputs**                                       | **Depends on**                                              |
|----------------------------------|-------------------------------------------------------------------------------------|--------------------------------|---------------------------------------------------|-------------------------------------------------------------|
| explain.py                       | FR-01 (0.5.1): attention rollout / gradient attribution over ActivationBundle.      | ActivationBundle               | Relevance map (patch grid)                        | M2's ActivationBundle (Contract C2)                         |
| overlay.py                       | FR-01 (0.5.2): colormap, upsample to original dimensions, alpha-blend, persist PNG. | Relevance map, D2 width/height | D5 rows, PNG files                                | Pillow, Matplotlib                                          |
| router_results.py                | FR-02: results view data assembly.                                                  | prediction_id                  | Results view payload                              | explain.py, overlay.py                                      |
| router_history.py                | FR-03: per-user paginated history.                                                  | Session                        | Paginated prediction list                         | models.py                                                   |
| reporting.py / router_reports.py | FR-04: PDF assembly and endpoint.                                                   | prediction_id                  | application/pdf stream                            | WeasyPrint or ReportLab                                     |
| logging_service.py               | FR-05: emit(), redaction filter, retention policy. Imported by all three modules.   | Log event fields               | Committed D6 row (or swallowed failure)           | PostgreSQL                                                  |
| router_admin.py                  | FR-06–FR-09: dashboard, log explorer, analytics, and proxy screens for F.17/F.19.   | Admin session                  | Dashboard/analytics payloads; proxied M1/M2 calls | analytics.py, M1's status endpoint, M2's registry endpoints |
| analytics.py                     | FR-07: aggregate queries over D4 and D6.                                            | Date range, metric selection   | Aggregated analytics                              | Indexed D4/D6 tables                                        |
| models.py                        | SQLAlchemy models for D5 (Explainability) and D6 (Logs).                            | —                              | ORM row objects                                   | PostgreSQL                                                  |

# **7. Data Requirements**

## **7.1 D5. Explainability (schema owner: M3)**

    CREATE TABLE explainability ( -- D5
      explainability_id BIGSERIAL PRIMARY KEY,
      prediction_id BIGINT NOT NULL REFERENCES predictions(prediction_id) ON DELETE CASCADE,
      branch VARCHAR(12) NOT NULL CHECK (branch IN ('semantic','frequency')),
      technique VARCHAR(40) NOT NULL, -- attention-rollout | grad-attribution
      visualization_reference TEXT NOT NULL,
      generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (prediction_id, branch)
    );
    CREATE INDEX idx_xai_prediction ON explainability (prediction_id);

D5 extends the SRS Data Dictionary with branch and technique, and a uniqueness constraint on (prediction_id, branch): the hybrid design produces two visualisations per prediction (one per branch), which the Data Dictionary's original one-visualisation-per-prediction assumption cannot represent without this column. CASCADE on prediction deletion is a correctness guarantee, not a routine path — predictions themselves are never deleted per the Interface Contract §9.1.

## **7.2 D6. Logs (schema owner: M3)**

    CREATE TABLE logs ( -- D6
      log_id BIGSERIAL PRIMARY KEY,
      user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
      event_type VARCHAR(24) NOT NULL CHECK (event_type IN
        ('authentication','prediction-request','administrative-action','error')),
      event_detail TEXT NOT NULL,
      severity VARCHAR(8) NOT NULL CHECK (severity IN ('info','warning','error')),
      request_id UUID,
      log_timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX idx_logs_time ON logs (log_timestamp DESC);
    CREATE INDEX idx_logs_type_time ON logs (event_type, log_timestamp DESC);
    CREATE INDEX idx_logs_sev_time ON logs (severity, log_timestamp DESC) WHERE severity <> 'info';

request_id is added beyond the Data Dictionary so a user-facing error and its log entry can be tied together — what makes the shared error envelope (§11) actually useful in support.

## **7.3 Retention policy (proposed — see DECISION REQUIRED in §4)**

| **Severity**    | **Retention** |
|-----------------|---------------|
| info            | 90 days       |
| warning / error | 1 year        |

# **8. Algorithms / Processing Logic**

## **8.1 Explainability technique for a Vision Transformer**

SRS Appendix A Figure A.1 shows Grad-CAM, which requires convolutional feature maps. The system uses a CLIP Vision Transformer, whose intermediate representation is a sequence of patch tokens rather than a spatial feature map — Figure A.1 predates the hybrid design and no longer describes the system (recorded as an open item for the SRS, see §4 and PRD 4).

| **Technique**                       | **How it works**                                                                                                                                               | **Assessment**                                                                                                                               |
|-------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| Attention rollout                   | Multiply attention matrices across layers, accounting for the residual connection, to trace how much each input patch contributes to the final representation. | No gradients needed — cheaper, works under torch.no_grad(). Class-agnostic: shows overall attention, not what drove this particular verdict. |
| Gradient-weighted patch attribution | Weight patch embeddings by the gradient of the predicted-class logit with respect to them, then reshape to the patch grid.                                     | Class-specific, which is what F.10 actually asks for. Costs a backward pass — the 1.4× latency budget declared in Contract C2 §5.3.          |

**\[DECISION REQUIRED\]** Explainability technique for the ViT backbone — attention rollout or gradient-weighted attribution — decided jointly with M2. Recommended approach: implement attention rollout first (simpler, no gradients needed), then add gradient attribution and compare the two on a fixed set of images by eye, choosing whichever produces maps a non-expert can actually read.

## **8.2 Why the prediction-history query must embed ownership**

    # CORRECT — scope is part of the query, and cannot be widened
    stmt = (select(Prediction)
            .join(Image, Image.image_id == Prediction.image_id)
            .where(Image.user_id == session.user_id)   # <-- not optional
            .order_by(Prediction.prediction_timestamp.desc())
            .limit(page_size).offset(offset))
     
    # WRONG — fetch then filter. Works in testing, leaks under pagination,
    # and any future code path that forgets the filter returns everything.
    rows = session.execute(select(Prediction)).scalars().all()
    rows = [r for r in rows if owner_of(r) == session.user_id]

Ownership travels through D2: predictions reference images, and images carry user_id, so the join is mandatory. This is why M1's idx_images_user_time index exists. The ownership predicate is in the query on every code path, with no path that constructs the query without it.

## **8.3 Interpretability, honestly (NF.13)**

Saliency maps are persuasive out of proportion to what they establish. A user shown a highlighted region will tend to conclude that region was manipulated; what the map actually says is that those patches carried weight in the representation. Two consequences are treated as requirements, not suggestions: the caption is permanent and adjacent to the image (never hidden behind a tooltip), and the wording avoids causal language — "regions the model weighted most heavily", never "regions that were AI-generated", which the system did not determine and cannot support.

## **8.4 Non-throwing logging (G4)**

emit() catches everything internally. A logging failure is written to the application's stderr stream and the request continues — this is the one place in the system where an exception is deliberately not propagated, and it should remain commented as such in the source. The alternative — a failed audit write taking down a successful prediction — is worse than a missing log line.

# **9. Internal Interfaces**

| **Source**                                | **Destination**                  | **Interface**                                                 | **Behaviour**                                                                                                                                                                 |
|-------------------------------------------|----------------------------------|---------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 3.1 Explainability Generation             | 3.2 Results & History            | D5 rows / visualization_reference                             | 3.2's results view reads the stored D5 reference rather than asking 3.1 to regenerate on every view.                                                                          |
| Any sub-module (3.1, 3.2, 3.3)            | logging_service.py               | emit(event_type, event_detail, severity, user_id, request_id) | Synchronous, non-throwing, best-effort — see §8.4. Shared by all three project modules, not only M3's own code.                                                               |
| router_admin.py (F.17/F.19 proxy screens) | router_history.py / analytics.py | Internal aggregate read of D4                                 | Dashboard tiles and analytics read the same prediction store FR-03 protects; admin-facing reads are role-gated on separate endpoints, never by widening the user-facing ones. |

# **10. External Interfaces**

| **Contract**                         | **Direction**                                          | **What crosses the boundary**                                                                                                                                                         |
|--------------------------------------|--------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| C2 — Inference output                | M2 → M3 (in-process, consumed)                         | M3 consumes InferenceOutput including the ActivationBundle when xai_requested. M3 never writes D4; M2 has already committed the prediction row by the time M3 receives the structure. |
| C3 — Session and identity            | M1 → M3 (consumed)                                     | M3 receives an already-validated SessionContext and trusts it; it performs its own record-level ownership checks (FR-03, §8.2) but no credential checks.                              |
| C3.3 — Administrative account writes | M3 → M1 (HTTP)                                         | M3's admin UI calls M1's PATCH /api/v1/users/{user_id}/status (FR-08). M3 issues no write to D1.                                                                                      |
| C4 — Model management                | M3 → M2 (HTTP)                                         | M3's admin UI calls M2's registry endpoints (FR-09). M3 issues no write to D3.                                                                                                        |
| C5 — Logging (M3 as owner)           | M1, M2 → M3 (in-process call); M3 owns the reader side | M3 implements and owns emit() and D6. M1 and M2 import and call it; only M3 reads D6.                                                                                                 |

## **10.1 Public REST API**

| **Method & path**                          | **Auth**     | **Returns**                         | **Errors**                                      |
|--------------------------------------------|--------------|-------------------------------------|-------------------------------------------------|
| GET /api/v1/results/{prediction_id}        | user (owner) | Full results view payload           | INF_PREDICTION_NOT_FOUND                        |
| GET /api/v1/explainability/{prediction_id} | user (owner) | Visualisation references per branch | INF_PREDICTION_NOT_FOUND, XAI_UNAVAILABLE       |
| GET /api/v1/history                        | user         | Paginated own predictions           | AUTH_TOKEN_INVALID                              |
| GET /api/v1/reports/{prediction_id}        | user (owner) | application/pdf                     | INF_PREDICTION_NOT_FOUND, RPT_GENERATION_FAILED |
| GET /api/v1/admin/summary                  | admin        | Dashboard tiles                     | AUTH_FORBIDDEN                                  |
| GET /api/v1/admin/logs                     | admin        | Paginated, filtered log rows        | AUTH_FORBIDDEN                                  |
| GET /api/v1/admin/analytics                | admin        | Aggregates per FR-07                | AUTH_FORBIDDEN                                  |
| GET /api/v1/admin/users                    | admin        | Account list                        | AUTH_FORBIDDEN                                  |

No history or results endpoint accepts a user_id parameter of any kind — scope comes only from the session (§8.2).

# **11. Error Handling and Edge Cases**

| **Code**                 | **HTTP** | **Meaning**                                                                                             |
|--------------------------|----------|---------------------------------------------------------------------------------------------------------|
| XAI_UNAVAILABLE          | 501      | Explainability not supported for the active model (constraint C.3).                                     |
| RPT_GENERATION_FAILED    | 500      | PDF assembly failed.                                                                                    |
| INF_PREDICTION_NOT_FOUND | 404      | prediction_id does not exist or is not visible to the caller (owned by M2's namespace, surfaced by M3). |

M3 surfaces M1's and M2's codes unchanged when proxying (FR-08, FR-09) — re-wrapping them would hide the origin of a failure from the administrator reading the log.

## **11.1 Record-level ownership — the highest-priority edge cases in this module**

| **\#** | **Attempt**                                                | **Expected**                                                                     |
|--------|------------------------------------------------------------|----------------------------------------------------------------------------------|
| 1      | User A requests GET /history                               | Only A's rows, at every page                                                     |
| 2      | User A requests user B's prediction by ID                  | INF_PREDICTION_NOT_FOUND                                                         |
| 3      | User A requests a PDF report of B's prediction             | INF_PREDICTION_NOT_FOUND                                                         |
| 4      | User A requests B's explainability by prediction ID        | INF_PREDICTION_NOT_FOUND                                                         |
| 5      | User A appends ?user_id=B to every user-facing endpoint    | Parameter ignored; only A's data returned                                        |
| 6      | User A requests any /admin/\* endpoint                     | AUTH_FORBIDDEN                                                                   |
| 7      | User A pages past the end of their own history             | Empty page, never a spill into another user's rows                               |
| 8      | User A requests a prediction ID that does not exist at all | INF_PREDICTION_NOT_FOUND — identical to case 2, so the two are indistinguishable |

Case 8 is the one most often forgotten: if "not yours" and "does not exist" produce different responses, an attacker can map the entire prediction table by probing IDs.

## **11.2 Other edge cases**

- activations comes back None despite being requested: XAI_UNAVAILABLE surfaced, D6 warning logged, results view still shows verdict and confidence.

- A logging or explainability failure never fails the underlying request — the verdict is still returned; only the ancillary feature degrades.

- A model activation performed through M3's admin screen must be reflected in M2's active configuration on the very next read (contract test, §13.3).

# **12. Performance Requirements**

| **SRS ID**             | **Obligation on M3**                                                                                    | **Verification**                                             |
|------------------------|---------------------------------------------------------------------------------------------------------|--------------------------------------------------------------|
| NF.1 Response time     | Explainability ≤ 900 ms; history ≤ 300 ms; analytics ≤ 1.5 s; PDF ≤ 2 s — all p95.                      | Load test against a seeded database, not an empty one.       |
| NF.2 Capacity          | History and analytics remain responsive at 100,000 predictions and 1,000,000 log rows.                  | Seeded volume test.                                          |
| NF.6 Availability      | A logging or explainability failure never fails the underlying request.                                 | Fault injection into emit() and the overlay path.            |
| NF.7 Security          | Ownership predicates in every query; no credential data in analytics; redaction filter on D6.           | Isolation suite (§11.1) and automated secret-redaction scan. |
| NF.13 Interpretability | A visualisation for every prediction where C.3 permits, with an honest caption, covering both branches. | Caption present in both the results view and the PDF.        |

## **12.1 Success metrics**

| **ID** | **Metric**                             | **Target**                                                                                                           |
|--------|----------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| MM3.1  | Cross-user data access                 | 0 across the full isolation suite — a single leak is a release blocker.                                              |
| MM3.2  | Explainability generation latency, p95 | ≤ 900 ms after inference returns (excludes M2's inference time).                                                     |
| MM3.3  | Explainability availability            | ≥ 95% of predictions when the active model supports it; the remainder surfaces XAI_UNAVAILABLE, never a blank image. |
| MM3.4  | History page latency, p95              | ≤ 300 ms for 20 rows at 100,000 rows in D4.                                                                          |
| MM3.5  | PDF generation latency, p95            | ≤ 2 s per report, including fetching and embedding the visualisation.                                                |
| MM3.6  | Analytics query latency, p95           | ≤ 1.5 s at 100,000 predictions and 1,000,000 log rows.                                                               |
| MM3.7  | Log write overhead                     | ≤ 5 ms added to the request that emitted it.                                                                         |
| MM3.8  | Secret redaction                       | 0 passwords, tokens or image bytes present in D6, verified by an automated scan.                                     |

# **13. Testing Requirements**

## **13.1 Unit tests**

- Token relevance vector reshapes correctly to the patch grid; the CLS token is excluded.

- The overlay upsamples to the original dimensions — asserted on a deliberately non-square image (e.g. 1600×900), where a 224-shaped map would be visibly wrong.

- Confidence banding at the boundaries 0.649, 0.650, 0.849, 0.850.

- The redaction filter strips passwords, bearer tokens and long base64 blobs from event_detail.

- Analytics aggregations produce correct counts against a small fixture whose answers are known by hand.

## **13.2 Isolation suite (FR-03) — the highest-priority tests in this module**

Two seeded users, A and B, each with predictions. Every attempt in §11.1 must fail to return B's data to A; all 8 cases must pass before any other work on this module is considered complete.

## **13.3 Integration and contract tests**

- C2 with M2: every field present and in range; the confidence inversion asserted from M3's side independently of M2's own test; activations None when not requested.

- C2 degraded path: activations None despite being requested yields XAI_UNAVAILABLE and a rendered result without a visualisation.

- C5: emit() called with a forbidden field raises in test mode and is silently redacted in production mode.

- C4 proxy: a model activation performed through M3's screen is reflected in M2's active configuration.

- End-to-end: upload through M1, infer through M2, view, then download the PDF, asserting that the verdict and confidence in the PDF match the view exactly.

## **13.4 Performance and volume tests**

- Seed 100,000 predictions and 1,000,000 log rows, then measure MM3.4 and MM3.6 — running these against an empty database proves nothing.

- Fifty concurrent PDF generations, watching peak memory (MM3.5).

- Log-write overhead measured with emit() enabled and disabled (MM3.7).

## **13.5 Usability check**

Three people outside the team read one results page and one PDF, and are asked what the system concluded and how sure it was. If they describe the heat map as showing "the fake part", the caption wording has failed and needs revision — this is a real design outcome to check for, not a formality.

# **14. Acceptance Criteria**

## **AC group 1 — See and understand a result (FR-01, FR-02)**

**AC-01.** *Given* a completed prediction*, when* the results view is opened*, then* it shows predicted_class, confidence_score as a percentage, the explainability overlay beside the original image, and a status message.

**AC-02.** *Given* the displayed confidence percentage*, when* its source is inspected*, then* it derives from confidence_score, never from fusion_score.

**AC-03.** *Given* explainability is unavailable for the active model*, when* the results view is opened*, then* it states plainly that no visualisation could be produced and shows the result anyway — never an empty box or blank heat map.

**AC-04.** *Given* any results view*, when* it is inspected*, then* it carries a short, permanent caption explaining that highlighted regions indicate where the model focused and are not proof of manipulation.

## **AC group 2 — Review my own history (FR-03)**

**AC-05.** *Given* a user's history is requested*, when* the list is returned*, then* it is ordered newest first and paginated.

**AC-06.** *Given* any row in the returned history*, when* its owner is checked*, then* it belongs to the requesting user.

**AC-07.** *Given* another user's prediction is requested by ID*, when* the request is made*, then* it returns INF_PREDICTION_NOT_FOUND, not a 403.

**AC-08.** *Given* any query parameter (user_id, filter, sort or otherwise)*, when* it is supplied on a history request*, then* it cannot widen the scope beyond the session's own user.

## **AC group 3 — Download a report (FR-04)**

**AC-09.** *Given* a prediction the requester owns*, when* a PDF report is requested*, then* the PDF contains the image, verdict, confidence, visualisation, timestamp and model version used.

**AC-10.** *Given* a prediction the requester does not own*, when* a PDF report is requested*, then* it returns INF_PREDICTION_NOT_FOUND.

**AC-11.** *Given* any generated PDF report*, when* it is inspected*, then* it carries the same interpretive caveat that appears in the interface.

**AC-12.** *Given* a failure occurs during PDF assembly*, when* the request completes*, then* it returns RPT_GENERATION_FAILED and is logged; no truncated PDF is ever returned.

## **AC group 4 — Operate the system (FR-06, FR-07)**

**AC-13.** *Given* the administrator dashboard is opened*, when* the tiles render*, then* they show total predictions, class distribution, recent errors and currently active model versions.

**AC-14.** *Given* the log explorer is used*, when* logs are queried*, then* they are filterable by event_type, severity and date range, and paginated.

**AC-15.** *Given* analytics are viewed*, when* the data is inspected*, then* no credentials, password hashes or session tokens are exposed — only aggregates.

**AC-16.** *Given* any administrative action, including a read of the logs*, when* it occurs*, then* it is itself logged with the acting administrator's user_id and the target.

## **AC group 5 — Manage users and models (FR-08, FR-09)**

**AC-17.** *Given* an administrator enables, disables or removes an account*, when* the action is submitted*, then* M3 calls M1's PATCH /users/{id}/status and issues no direct write to D1.

**AC-18.** *Given* an administrator registers or activates a model*, when* the action is submitted*, then* M3 calls M2's registry endpoints and issues no direct write to D3.

**AC-19.** *Given* either proxy screen encounters an error*, when* M1 or M2 returns one*, then* M3 surfaces the owning module's error code verbatim rather than inventing a new one.

**AC-20.** *Given* a destructive action (disable, remove, or model deactivation) is initiated*, when* the administrator proceeds*, then* an explicit confirmation step names the target account or model.

# **15. Definition of Done**

M3 is done when every acceptance criterion in §14 passes; the isolation suite (§13.2) is 8/8 with MM3.1 at zero; MM3.2 through MM3.8 are measured at realistic volume and reported; contract tests C2, C4 and C5 are green; and the interpretive caption appears in both the results view and the PDF in non-causal wording.

## **15.1 Milestones**

| **Milestone**              | **Deliverable**                                                                        | **Gate**                        |
|----------------------------|----------------------------------------------------------------------------------------|---------------------------------|
| M3.0 — Stubs               | emit() no-op with argument validation; D5 and D6 migrations merged.                    | Unblocks M1 and M2 immediately. |
| M3.1 — Results view        | FR-02 against M2's stub, including the confidence-band logic and the caption.          | Checkpoint I1.                  |
| M3.2 — History and reports | FR-03 with the full isolation suite green; FR-04 PDF generation.                       | Checkpoint I4.                  |
| M3.3 — Explainability      | FR-01 with attention rollout, dual-panel output, D5 persistence, C.3 degradation path. | Checkpoint I3.                  |
| M3.4 — Logging             | FR-05: emit(), redaction filter, retention policy, indexes.                            | Checkpoint I2.                  |
| M3.5 — Administration      | FR-06, FR-07, and the FR-08/FR-09 proxy screens.                                       | Checkpoint I5.                  |
| M3.6 — Hardening           | Volume tests at target scale; usability check; secret-redaction scan clean.            | Release candidate.              |
