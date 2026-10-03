"""Contract C2 - InferenceOutput (M2 -> M3).

Transcribed from PRD2 section 7.3. Specified in two halves:

- The **public half** is stable. Every field above the divider may be
  serialised, shown to a user, and depended on by M3. Changing it is a
  breaking change requiring a version bump of the Interface Contract.
- The **internal half** (``activations``) is explicitly UNSTABLE. M2 may add,
  rename or drop ActivationBundle fields as the architecture evolves, with
  notice to M3 but without a contract version bump. It is an in-process
  structure only and is never serialised over HTTP (Contract C2 section 5.4):
  shipping attention tensors to a browser would be both large and pointless.

CHANGE LOG relative to PRD2 section 7.3.

Revision 1 (2026-09-07), when the system moved from training its own heads
to using pretrained detectors: ``frequency_score`` became ``float | None`` and
was always None (no frequency classifier existed), and a ``secondary_score``
field was added for a second semantic detector (SwinV2).

Revision 2 (2026-09-12): the second semantic detector was removed and the
frequency branch is now realised by a pretrained spectral detector (SPAI).
``secondary_score`` is gone; ``frequency_score`` is populated again with what
PRD2 always meant by it - P(AI Generated) from frequency-domain evidence. It
stays ``float | None`` only because the branch can be disabled by
configuration, in which case fusion is a documented passthrough and the field
is None rather than a stand-in number.

``semantic_score`` keeps its name and meaning throughout (P(AI Generated) from
the semantic vision branch); what changed underneath is that it comes from a
pretrained SigLIP 2 detector rather than a head we trained. The public field
set is now exactly PRD2 section 7.3's again.

Revision 3 (2026-09-30), M1/M3 integration: M2 now writes the D4 row and
commits before returning (PRD4 section 4.2.4), so ``prediction_id`` and
``model_id`` are ``int`` again, as PRD4 specifies. They had been
``int | None`` only because there was no database.

The confidence inversion rule (Contract C2 section 5.2, PRD2 section 8.3) is
the single most likely integration bug in the project, so it is restated here:
``semantic_score``, ``frequency_score`` and ``fusion_score`` are all
P(AI Generated). ``confidence_score`` is the odd one out - it is confidence in
whichever class was actually predicted. A fusion_score of 0.08 yields
("Real", 0.92). Never render fusion_score as a confidence figure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ActivationBundle(BaseModel):
    """Internal model state M3 needs for explainability. UNSTABLE by design.

    The array fields are typed ``Any`` because they carry raw numpy arrays,
    which Pydantic cannot validate structurally. The bundle never leaves the
    process, so this is a deliberate trade rather than a gap.

    Populated only when ``xai_requested=True`` (Phase 3, milestone M2.5).

    NOTICE TO M3 (2026-10-03, changes.md 6.7) - fields changed, as PRD2 7.3
    allows for this unstable structure:
    - ``backbone`` admits ``"siglip_b16"`` - the semantic model is SigLIP
      (patch 16, 224 px, 14x14 grid), not CLIP.
    - ``pooling`` is new: ``"mean"`` for SigLIP, whose classifier mean-pools
      all patch tokens and has NO CLS token, so rollout must aggregate over
      every query token; ``"cls"`` keeps the original CLS-row behaviour.
    - ``spectrum`` is now the mean log-magnitude spectrum of the 224x224
      patches the frequency detector (SPAI) actually analyses, and
      ``spectrum_meta`` says so (patch size, patch count, SPAI's mask radius).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    backbone: Literal["clip_vit_b32", "clip_vit_l14", "siglip_b16"]
    patch_grid: tuple[int, int]  # e.g. (7, 7) for ViT-B/32 at 224px
    attention: Any | None = None  # (layers, heads, tokens, tokens)
    patch_embeddings: Any | None = None  # (tokens, dim)
    head_gradients: Any | None = None  # only when xai_requested=True
    spectrum: Any | None = None  # mean log-magnitude FFT of SPAI's 224x224 patches
    pooling: Literal["cls", "mean"] = "cls"
    spectrum_meta: dict | None = None  # {"patch_size", "patches", "mask_radius", ...}
    timings_ms: dict | None = None  # capture costs, for the XAI cost measurement


class InferenceOutput(BaseModel):
    """The result of one inference. Produced by M2, consumed by M3."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- public half: stable, safe to serialise, safe to show a user ---
    # FR-05: the D4 row is written AND committed before this structure is
    # returned, so prediction_id is a valid foreign key the instant M3
    # receives it.
    prediction_id: int
    image_id: int
    user_id: int
    model_id: int  # the FUSION config row (D3) active at inference
    predicted_class: Literal["Real", "AI Generated"]
    confidence_score: float  # [0,1], confidence IN predicted_class
    semantic_score: float  # [0,1], P(AI Generated) from the semantic branch
    # P(AI Generated) from the frequency branch - the pretrained SPAI spectral
    # detector. None when that branch had no evidence to give: either it is
    # switched off in configuration, or the image is smaller than its 224px
    # patch (M1 accepts images from 64px, so that is a normal upload, not an
    # edge case). Fusion then falls back to the documented passthrough and the
    # verdict comes from the semantic branch alone. Never a stand-in value -
    # a zero here would read as "confidently not AI".
    frequency_score: float | None = None
    fusion_score: float  # [0,1], P(AI Generated) after fusion
    prediction_timestamp: datetime
    latency_ms: int

    # --- internal half: UNSTABLE, never serialised over HTTP ---
    activations: ActivationBundle | None = None
