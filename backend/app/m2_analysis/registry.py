"""FR-06 / FR-07 - the model registry.

Current scope: an in-process stand-in. ``active()`` returns the configuration
from ``shared/config.py`` instead of reading D3 rows, because there is no
database yet.

Note on what a "model version" now means: since we never train, a D3 row will
record which third-party checkpoint was active, not an artefact we produced.
FR-06's canary forward pass still applies - a checkpoint that will not load,
or whose labels cannot be resolved, must fail in front of the administrator
rather than in front of a user.

The call signature is the one Step 5 (PRD milestone M2.4) will keep, so
``pipeline.py`` does not change when D3 arrives. What changes here is only the
body of ``active()``: it will read the three active rows, cache them
in-process, and invalidate that cache on activation. Registration
(FR-06, with its canary forward pass) and atomic activation (FR-07, guarded by
the ``uq_models_one_active_per_type`` partial unique index) land at the same
time, alongside ``router_models.py``.

Since the M1/M3 integration, D3 exists (the table M3 designed, now in
``models.py``) and every D4 row needs a ``model_id``. ``record()`` bridges the
gap: it writes one D3 row per artefact that actually ran, from config, and
returns their ids. The direction is still config -> D3, never the reverse;
M3's admin "activate" endpoint flips ``is_active`` but does not change what
runs, and the next prediction marks the configured rows active again. Making
D3 authoritative is still Step 5.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.shared import config
from app.shared.contracts.errors import ModelUnavailableError


@dataclass(frozen=True)
class DetectorConfig:
    """Active configuration for one pretrained detector.

    ``checkpoint`` is the only thing that identifies the model. There is no
    artefact path and no head geometry, because we never train anything: the
    weights come from the Hugging Face hub as published.
    """

    model_id: int | None  # D3 row id; None until Step 5
    checkpoint: str
    role: str  # "primary"


@dataclass(frozen=True)
class SpectralDetectorConfig:
    """Active configuration for the pretrained frequency-domain detector (SPAI).

    Identified by the weights file and the pinned digest of its contents,
    because the weights come from the authors as published and are converted
    once, offline, into that file - see frequency_detector.py.
    """

    model_id: int | None  # D3 row id; None until Step 5
    name: str
    filename: str
    weights_digest: str
    ai_is_positive: bool
    resize_to: int | None
    feature_batch: int


@dataclass(frozen=True)
class FrequencyFeatureConfig:
    """Spectral FEATURE extraction. EXPLAINABILITY ONLY - produces no score.

    Distinct from the frequency detector above. This is the hand-written FFT
    pipeline of PRD2 FR-02 steps 1-7, kept to populate
    ActivationBundle.spectrum for M3. Its step 8 - a classifier - is what SPAI
    provides instead, because training one is out of scope.
    """

    crop_size: int
    radial_bins: int
    use_luminance: bool
    highpass: bool
    highpass_sigma: float
    scalar_features: int


@dataclass(frozen=True)
class FusionModelConfig:
    """Active fusion configuration: strategy, weight, tau, temperature."""

    model_id: int | None
    strategy: str
    weight: float
    tau: float
    temperature: float


@dataclass(frozen=True)
class ActiveModelSet:
    """The active configurations resolved together."""

    primary: DetectorConfig
    frequency_detector: SpectralDetectorConfig | None  # None when disabled
    spectral_features: FrequencyFeatureConfig
    fusion: FusionModelConfig


def active() -> ActiveModelSet:
    """Resolve the currently active detector and fusion configuration.

    Raises:
        ModelUnavailableError: once D3 exists, when any required model type has
            no active version. Never falls back to a single branch silently -
            a hybrid detector running on one branch is a different system
            (PRD2 11.1). Running on the primary alone is possible, but only as
            a deliberate configuration choice.
    """
    if config.FUSION_STRATEGY != "weighted_average":
        raise ModelUnavailableError(
            f"unsupported fusion strategy {config.FUSION_STRATEGY!r}: only "
            "'weighted_average' is available, because the alternative "
            "(a logistic meta-classifier) would have to be trained"
        )

    frequency_detector = None
    if config.DETECTOR_FREQUENCY_ENABLED:
        frequency_detector = SpectralDetectorConfig(
            model_id=None,
            name=config.DETECTOR_FREQUENCY_NAME,
            filename=config.DETECTOR_FREQUENCY_FILENAME,
            weights_digest=config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST,
            ai_is_positive=config.DETECTOR_FREQUENCY_AI_IS_POSITIVE,
            resize_to=config.DETECTOR_FREQUENCY_RESIZE_TO,
            feature_batch=config.DETECTOR_FREQUENCY_FEATURE_BATCH,
        )

    return ActiveModelSet(
        primary=DetectorConfig(
            model_id=None,
            checkpoint=config.DETECTOR_PRIMARY,
            role="primary",
        ),
        frequency_detector=frequency_detector,
        spectral_features=FrequencyFeatureConfig(
            crop_size=config.FREQ_CROP_SIZE,
            radial_bins=config.FREQ_RADIAL_BINS,
            use_luminance=config.FREQ_USE_LUMINANCE,
            highpass=config.FREQ_HIGHPASS,
            highpass_sigma=config.FREQ_HIGHPASS_SIGMA,
            scalar_features=config.FREQ_SCALAR_FEATURES,
        ),
        fusion=FusionModelConfig(
            model_id=None,
            strategy=config.FUSION_STRATEGY,
            weight=config.FUSION_WEIGHT,
            tau=config.FUSION_TAU,
            temperature=config.CALIBRATION_TEMPERATURE,
        ),
    )


# --------------------------------------------------------------------------
# D3 bookkeeping
# --------------------------------------------------------------------------

# model_type values, as M3 designed the D3 column.
TYPE_SEMANTIC = "semantic-classifier"
TYPE_FREQUENCY = "frequency-artifact-classifier"
TYPE_FUSION = "fusion-configuration"


@dataclass(frozen=True)
class RecordedModels:
    """D3 row ids of the artefacts that took part in one prediction."""

    semantic_id: int
    frequency_id: int | None
    fusion_id: int

    def branch_ids(self) -> dict[str, int | None]:
        """The D4 ``branch_model_ids`` value."""
        return {"semantic": self.semantic_id, "frequency": self.frequency_id}


def _canonical_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _upsert(
    db: Session,
    *,
    model_type: str,
    name: str,
    version: str,
    artifact_ref: str,
    artifact_sha256: str | None,
    hyperparameters: dict | None,
) -> int:
    """Ensure one D3 row exists and is the active row of its type.

    ``metrics`` is always left null: no benchmark of this system has been run,
    and upstream self-reported numbers are not ours to record as if they were.
    Flushes but does not commit - the caller commits with the D4 row.
    """
    from app.m2_analysis.models import ModelRegistry

    row = (
        db.query(ModelRegistry)
        .filter(ModelRegistry.model_name == name, ModelRegistry.model_version == version)
        .first()
    )
    if row is None:
        row = ModelRegistry(
            model_name=name,
            model_version=version,
            model_type=model_type,
            artifact_ref=artifact_ref,
            artifact_sha256=artifact_sha256,
            hyperparameters=hyperparameters,
            metrics=None,
            is_active=False,
        )
        db.add(row)
        db.flush()

    if not row.is_active:
        db.query(ModelRegistry).filter(
            ModelRegistry.model_type == model_type,
            ModelRegistry.model_id != row.model_id,
            ModelRegistry.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)
        row.is_active = True
        db.flush()

    return row.model_id


def record(db: Session, models: ActiveModelSet) -> RecordedModels:
    """Write (or find) the D3 rows describing ``models``; return their ids.

    Versions encode everything that changes a score, so a config change yields
    a new row rather than silently rewriting history under an old id.
    """
    semantic_id = _upsert(
        db,
        model_type=TYPE_SEMANTIC,
        name=models.primary.checkpoint,
        # from_pretrained() without a revision loads the hub's default branch,
        # and no digest of it is pinned in config - hence the null hash.
        version="main",
        artifact_ref=f"hf://{models.primary.checkpoint}",
        artifact_sha256=None,
        hyperparameters=None,
    )

    frequency_id = None
    spectral = models.frequency_detector
    if spectral is not None:
        resize = "native" if spectral.resize_to is None else f"resize{spectral.resize_to}"
        frequency_id = _upsert(
            db,
            model_type=TYPE_FREQUENCY,
            name=spectral.name,
            version=f"{config.DETECTOR_FREQUENCY_UPSTREAM_COMMIT[:7]}-{resize}",
            artifact_ref=spectral.filename,
            artifact_sha256=spectral.weights_digest,
            hyperparameters={
                "ai_is_positive": spectral.ai_is_positive,
                "resize_to": spectral.resize_to,
            },
        )

    fusion = models.fusion
    fusion_params = {
        "strategy": fusion.strategy,
        "weight_semantic": fusion.weight,
        "weight_frequency": 1.0 - fusion.weight,
        "tau": fusion.tau,
        "temperature": fusion.temperature,
    }
    fusion_id = _upsert(
        db,
        model_type=TYPE_FUSION,
        name=f"{fusion.strategy} fusion",
        version=f"w{fusion.weight}-tau{fusion.tau}-T{fusion.temperature}",
        artifact_ref="app/shared/config.py",
        artifact_sha256=_canonical_sha256(fusion_params),
        hyperparameters=fusion_params,
    )

    return RecordedModels(
        semantic_id=semantic_id, frequency_id=frequency_id, fusion_id=fusion_id
    )
