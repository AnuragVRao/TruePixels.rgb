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
       +--> [xai only] attention + SPAI-patch spectrum -> ActivationBundle         v
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

from app.m2_analysis import detectors, frequency_detector, fusion, registry
from app.m2_analysis.models import Prediction
from app.shared.contracts.c1 import PreprocessedImage
from app.shared.contracts.c2 import ActivationBundle, InferenceOutput
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
        xai_requested: also return the ActivationBundle for M3's
            explainability: SigLIP attention (recomputed from passively
            captured inputs; the score is unchanged) and the mean spectrum of
            SPAI's own 224x224 patches. Assembled after the timed region;
            on any failure ``activations`` is None and a D6 warning is
            written - the prediction itself is never affected (SRS C.3).

    ``latency_ms`` is inference time only - both branches and fusion. It
    excludes one-time model loading (done at startup by the warm-up, or before
    the timer otherwise), preprocessing hand-off and the D3/D4 writes.

    Raises:
        ModelUnavailableError: a checkpoint could not be loaded or verified,
            or the primary's labels could not be resolved to an AI class.
        InferenceError: an unhandled failure inside either branch or fusion.
            The WHOLE request fails - M2 never returns a prediction based on
            the surviving branch alone (PRD2 section 11.1, AC-03).
    """
    models = registry.active()

    try:
        # One-time model loads happen HERE, outside the timed region, so
        # latency_ms measures inference only. Normally both are already
        # resident (startup warm-up, app/m2_analysis/warmup.py) and these return
        # immediately; if the warm-up was off or failed, the load still happens
        # - it is just not counted as this request's inference time.
        cold_start = not detectors.primary.is_loaded or (
            models.frequency_detector is not None and not frequency_detector.frequency.is_loaded
        )
        detectors.primary.load()
        if models.frequency_detector is not None:
            frequency_detector.frequency.load()

        started = time.perf_counter()

        # Semantic branch: the SigLIP 2 fine-tune. With xai on, passive hooks
        # also record each attention layer's input (the score is unchanged).
        semantic = detectors.primary.score(prepared.source_reference, capture=xai_requested)
        semantic_score = semantic.score

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
                    prepared.source_reference
                ).score
            except frequency_detector.SpectralBranchUnavailable:
                frequency_score = None

        # Fusion, thresholding, and the confidence inversion.
        fusion_score, predicted_class, confidence_score = fusion.combine(
            semantic_score, frequency_score, models.fusion
        )
    except InferenceError:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see PRD2 11.1
        raise InferenceError(f"inference failed: {exc}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    timestamp = datetime.now(timezone.utc)

    # Explainability data, OUTSIDE the timed region (latency_ms stays
    # inference-only). Never fails the prediction (SRS C.3): any problem
    # leaves activations None and is reported, not raised.
    bundle = None
    if xai_requested:
        bundle = _activation_bundle(prepared, semantic, models)

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
            cold_start=cold_start,
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
        activations=bundle,
    )


def _activation_bundle(prepared: PreprocessedImage, semantic, models) -> ActivationBundle | None:
    """Assemble the C2 ActivationBundle; None (and a D6 warning) on any failure."""
    from app.m2_analysis import xai
    from app.shared.logging import emit

    started = time.perf_counter()
    try:
        maps = detectors.primary.attention_maps(semantic.activations)
        attention_ms = (time.perf_counter() - started) * 1000

        spectrum, meta = None, None
        spectrum_started = time.perf_counter()
        if models.frequency_detector is not None:
            try:
                spectrum, meta = xai.spai_patch_spectrum(
                    prepared.source_reference, resize_to=models.frequency_detector.resize_to
                )
            except frequency_detector.SpectralBranchUnavailable:
                spectrum, meta = None, None  # below one SPAI patch: no frequency evidence to show
        spectrum_ms = (time.perf_counter() - spectrum_started) * 1000

        return ActivationBundle(
            backbone=maps["backbone"],
            patch_grid=maps["patch_grid"],
            attention=maps["attention"],
            pooling=maps["pooling"],
            spectrum=spectrum,
            spectrum_meta=meta,
            timings_ms={"attention": round(attention_ms, 1), "spectrum": round(spectrum_ms, 1)},
        )
    except Exception as exc:  # noqa: BLE001 - explainability never fails a prediction
        emit("error", f"Explainability capture failed for image_id={prepared.image_id}: "
             f"{type(exc).__name__}: {exc}", severity="warning", user_id=prepared.user_id)
        return None
