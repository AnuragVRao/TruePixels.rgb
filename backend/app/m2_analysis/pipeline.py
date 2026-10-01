"""M2's single entry point and the Contract C2 producer.

Orchestrates the two pretrained branches, fusion, and (from Step 5)
persistence.

    Input: PreprocessedImage (from M1, Contract C1)
       |
       v
    registry.active()  -- raises INF_MODEL_UNAVAILABLE if a model is missing
       |
       +--> 2.1 semantic branch  (SigLIP 2 fine-tune) -> semantic_score  --\\
       |                                                                   \\
       +--> 2.2 frequency branch (SPAI, spectral)     -> frequency_score ---+--> 2.3 fusion
       |                                                                          |
       +--> [xai only] FFT features -> ActivationBundle.spectrum                  v
                                                                  2.4 prediction & confidence
                                                                                  |
                                                                                  v
                                                        record D3 rows, persist D4 -> commit
                                                                                  |
                                                                                  v
                                                                    InferenceOutput --> M3

Both branches read the NATIVE-RESOLUTION original and apply their own
preprocessing: SigLIP 2 resizes to 224x224 with its own processor, SPAI tiles
the full image into 224x224 patches and must never see a resized copy
(Contract C1 section 4.3). Neither reads C1's tensor_ref.

The branches are independent and may eventually run concurrently, but PRD2
section 5 is explicit that concurrency is a latency optimisation for MM2.7 -
added once the numbers say it is needed, not a day-one design requirement.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.m2_analysis import detectors, frequency, frequency_detector, fusion, registry
from app.m2_analysis.models import Prediction
from app.shared.contracts.c1 import PreprocessedImage
from app.shared.contracts.c2 import InferenceOutput
from app.shared.contracts.errors import InferenceError
from app.shared.db import SessionLocal


async def run_detection(
    prepared: PreprocessedImage,
    db: Session | None = None,
    *,
    xai_requested: bool = False,
) -> InferenceOutput:
    """Classify one preprocessed image and persist the prediction to D4.

    Args:
        prepared: the Contract C1 structure handed over by M1.
        db: session to write D3/D4 through. Optional so that PRD4's
            ``run_detection(prepared)`` call form still works; a private
            session is opened and closed when it is omitted.
        xai_requested: capture internal model state for M3's explainability.
            Currently this computes the spectral features; the full
            ActivationBundle is assembled in Step 6 (milestone M2.5).

    Raises:
        ModelUnavailableError: a checkpoint could not be loaded or verified,
            or the primary's labels could not be resolved to an AI class.
        InferenceError: an unhandled failure inside either branch or fusion.
            The WHOLE request fails - M2 never returns a prediction based on
            the surviving branch alone (PRD2 section 11.1, AC-03).
    """
    models = registry.active()

    started = time.perf_counter()
    try:
        # Semantic branch: the SigLIP 2 fine-tune.
        semantic_score = detectors.primary.score(
            prepared.source_reference, capture=xai_requested
        ).score

        # Frequency branch: SPAI, a different kind of evidence entirely.
        # Two ways it can yield nothing, both ending in the same documented
        # passthrough: the branch is switched off in config, or the image is
        # smaller than SPAI's 224px patch (M1 admits images down to 64px, so
        # this is reachable from a normal upload). Either way the score is
        # NULL, never a stand-in, and the verdict comes from the semantic
        # branch alone.
        frequency_score = None
        if models.frequency_detector is not None:
            try:
                frequency_score = frequency_detector.frequency.score(
                    prepared.source_reference, capture=xai_requested
                ).score
            except frequency_detector.SpectralBranchUnavailable:
                frequency_score = None

        # Fusion, thresholding, and the confidence inversion.
        fusion_score, predicted_class, confidence_score = fusion.combine(
            semantic_score, frequency_score, models.fusion
        )

        # Spectral FEATURES for M3's explainability - the hand-written FFT
        # pipeline, not the detector. Computed ONLY when asked: a 512x512 FFT
        # on every request would be paid for nothing, since this produces no
        # score. Never fails the request - explainability is a nice-to-have,
        # a verdict is not.
        if xai_requested:
            try:
                frequency.extract_features(
                    prepared.source_reference, models.spectral_features
                )
            except Exception:  # noqa: BLE001
                pass
    except InferenceError:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see PRD2 11.1
        raise InferenceError(f"inference failed: {exc}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    timestamp = datetime.now(timezone.utc)

    # D4 write and commit BEFORE the return, so prediction_id is a valid
    # foreign key the instant M3 receives this structure (FR-05, AC-08,
    # PRD4 4.2.4). If the write fails the request fails: a prediction shown
    # to a user but absent from history is worse than an error (AC-10).
    owns_session = db is None
    session = SessionLocal() if owns_session else db
    try:
        recorded = registry.record(session, models)
        row = Prediction(
            image_id=prepared.image_id,
            model_id=recorded.fusion_id,
            branch_model_ids=recorded.branch_ids(),
            predicted_class=predicted_class,
            confidence_score=confidence_score,
            semantic_score=semantic_score,
            frequency_score=frequency_score,
            fusion_score=fusion_score,
            latency_ms=latency_ms,
            prediction_timestamp=timestamp,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        prediction_id, model_id = row.prediction_id, row.model_id
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise InferenceError(f"could not persist the prediction: {exc}") from exc
    finally:
        if owns_session:
            session.close()

    return InferenceOutput(
        prediction_id=prediction_id,
        image_id=prepared.image_id,
        user_id=prepared.user_id,
        model_id=model_id,
        predicted_class=predicted_class,
        confidence_score=confidence_score,
        semantic_score=semantic_score,
        frequency_score=frequency_score,
        fusion_score=fusion_score,
        prediction_timestamp=timestamp,
        latency_ms=latency_ms,
        activations=None,  # Step 6
    )
