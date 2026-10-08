"""FR-06 / FR-07 - the model registry. D3 is the authority (Phase 4, F.19).

What runs is decided by the ACTIVE rows of D3, one per model type:

    semantic-classifier            the SigLIP 2 backbone (pinned revision) + head
    frequency-artifact-classifier  SPAI (pinned weights digest) + head + sign convention
    fusion-configuration           weight, tau, temperature

``active(db)`` reads them once per request; the pipeline runs exactly that
configuration and writes those row ids into D4. Nothing is upserted during a
prediction any more - the old ``record()`` keyed rows on (name, version) and
never updated them, so a change outside the version string linked new
predictions to stale rows (reproduced in tests/test_provenance.py before this
rewrite). Config now only supplies the published BASELINE, registered once by
``ensure_registry`` when a type has no valid active row.

Changing what runs = registering a row (``app.m2_analysis.model_artifacts``)
and activating it here. Activation runs a canary forward pass and the quality
gate (``app.m2_analysis.gate``) first, then switches the active row inside one
transaction with the rows of that type locked; the partial unique index
``uq_models_one_active_per_type`` makes two concurrent activations unable to
leave two active rows. Every switch is recorded in ``model_activations`` -
the audit trail and the basis of one-call ``rollback``.

The backbones themselves are never swapped (out of scope): a row must name
the same checkpoint + revision (semantic) or weights digest (SPAI) as the
resident model. Uploads replace only the final head, or the fusion
configuration.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared import config
from app.shared.contracts.errors import InferenceError, ModelUnavailableError

# model_type values, as M3 designed the D3 column.
TYPE_SEMANTIC = "semantic-classifier"
TYPE_FREQUENCY = "frequency-artifact-classifier"
TYPE_FUSION = "fusion-configuration"
TYPES = (TYPE_SEMANTIC, TYPE_FREQUENCY, TYPE_FUSION)


@dataclass(frozen=True)
class DetectorConfig:
    model_id: int | None
    checkpoint: str
    role: str  # "primary"
    revision: str | None = None
    head: dict | None = None  # uploaded head spec; None = the checkpoint's own
    artifact_sha256: str | None = None  # the D3 row's; keys the P(AI) map (calibration.py)


@dataclass(frozen=True)
class SpectralDetectorConfig:
    model_id: int | None
    name: str
    filename: str
    weights_digest: str
    ai_is_positive: bool
    resize_to: int | None
    feature_batch: int
    head: dict | None = None
    artifact_sha256: str | None = None  # the D3 row's; keys the P(AI) map (calibration.py)


@dataclass(frozen=True)
class FrequencyFeatureConfig:
    """Spectral FEATURE extraction (frequency.py). EXPLAINABILITY ONLY - no score."""

    crop_size: int
    radial_bins: int
    use_luminance: bool
    highpass: bool
    highpass_sigma: float
    scalar_features: int


@dataclass(frozen=True)
class FusionModelConfig:
    model_id: int | None
    strategy: str
    weight: float
    tau: float
    temperature: float


@dataclass(frozen=True)
class ActiveModelSet:
    primary: DetectorConfig
    frequency_detector: SpectralDetectorConfig | None  # None when disabled
    spectral_features: FrequencyFeatureConfig
    fusion: FusionModelConfig


class RegistryError(Exception):
    """A registry operation was refused. ``code`` maps to the API error."""

    def __init__(self, code: str, message: str, status: int = 409, detail: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.detail = code, message, status, detail or {}


# --------------------------------------------------------------------------
# The published baseline (from config) - registered once, never used directly
# --------------------------------------------------------------------------

def _spectral_features() -> FrequencyFeatureConfig:
    return FrequencyFeatureConfig(
        crop_size=config.FREQ_CROP_SIZE, radial_bins=config.FREQ_RADIAL_BINS,
        use_luminance=config.FREQ_USE_LUMINANCE, highpass=config.FREQ_HIGHPASS,
        highpass_sigma=config.FREQ_HIGHPASS_SIGMA, scalar_features=config.FREQ_SCALAR_FEATURES,
    )


def baseline() -> ActiveModelSet:
    """The published configuration from config.py, without the database.

    For offline evaluation scripts (ml/evaluation/evaluate.py). The served
    application never uses this directly - it reads D3 (``active``).
    """
    if config.FUSION_STRATEGY != "weighted_average":
        raise ModelUnavailableError(
            f"unsupported fusion strategy {config.FUSION_STRATEGY!r}: only 'weighted_average' is "
            "available, because the alternative (a logistic meta-classifier) would have to be trained"
        )
    frequency = None
    if config.DETECTOR_FREQUENCY_ENABLED:
        frequency = SpectralDetectorConfig(
            model_id=None, name=config.DETECTOR_FREQUENCY_NAME,
            filename=config.DETECTOR_FREQUENCY_FILENAME,
            weights_digest=config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST,
            ai_is_positive=config.DETECTOR_FREQUENCY_AI_IS_POSITIVE,
            resize_to=config.DETECTOR_FREQUENCY_RESIZE_TO,
            feature_batch=config.DETECTOR_FREQUENCY_FEATURE_BATCH,
            artifact_sha256=config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST,
        )
    return ActiveModelSet(
        primary=DetectorConfig(model_id=None, checkpoint=config.DETECTOR_PRIMARY, role="primary",
                               revision=config.DETECTOR_PRIMARY_REVISION,
                               artifact_sha256=semantic_weights_digest()),
        frequency_detector=frequency,
        spectral_features=_spectral_features(),
        fusion=FusionModelConfig(model_id=None, strategy=config.FUSION_STRATEGY,
                                 weight=config.FUSION_WEIGHT, tau=config.FUSION_TAU,
                                 temperature=config.CALIBRATION_TEMPERATURE),
    )


def canonical_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


_semantic_weights_digest: dict[str, str | None] = {}


def semantic_weights_digest() -> str | None:
    """SHA-256 of the cached model.safetensors at the pinned revision (memoised)."""
    key = config.DETECTOR_PRIMARY_REVISION
    if key not in _semantic_weights_digest:
        digest = None
        try:
            from huggingface_hub import try_to_load_from_cache

            from app.m2_analysis.heads import file_sha256

            path = try_to_load_from_cache(config.DETECTOR_PRIMARY, "model.safetensors", revision=key)
            if isinstance(path, str):
                digest = file_sha256(path)
        except Exception:  # noqa: BLE001 - no cache yet: recorded as unknown, never invented
            digest = None
        _semantic_weights_digest[key] = digest
    return _semantic_weights_digest[key]


BASELINE_REFERENCE = (
    "Published checkpoint, unmodified (no training). Evaluated in this project only as part of "
    "the full system: ml/evaluation/RESULTS.md, 2026-10-01 held-out test, at fusion w=0.25, "
    "tau=0.7558 - metrics quoted there describe that model + fusion configuration together."
)


def baseline_rows() -> dict[str, dict]:
    """The D3 rows that describe the published baseline, one per type."""
    rev = config.DETECTOR_PRIMARY_REVISION
    digest = config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST
    resize = "native" if config.DETECTOR_FREQUENCY_RESIZE_TO is None else f"resize{config.DETECTOR_FREQUENCY_RESIZE_TO}"
    sign = "pos" if config.DETECTOR_FREQUENCY_AI_IS_POSITIVE else "neg"
    fusion = {
        "strategy": config.FUSION_STRATEGY, "weight_semantic": config.FUSION_WEIGHT,
        "weight_frequency": 1.0 - config.FUSION_WEIGHT, "tau": config.FUSION_TAU,
        "temperature": config.CALIBRATION_TEMPERATURE,
    }
    rows = {
        TYPE_SEMANTIC: dict(
            model_name=config.DETECTOR_PRIMARY, model_version=f"rev-{rev[:12]}",
            artifact_ref=f"hf://{config.DETECTOR_PRIMARY}@{rev}",
            artifact_sha256=semantic_weights_digest(),
            hyperparameters={"checkpoint": config.DETECTOR_PRIMARY, "revision": rev, "head": None},
            training_reference=BASELINE_REFERENCE),
        TYPE_FUSION: dict(
            model_name=f"{config.FUSION_STRATEGY} fusion",
            model_version=f"w{config.FUSION_WEIGHT}-tau{config.FUSION_TAU}-T{config.CALIBRATION_TEMPERATURE}",
            artifact_ref="app/shared/config.py (baseline)", artifact_sha256=canonical_sha256(fusion),
            hyperparameters=fusion,
            training_reference="Operating point selected on the validation split (scenes 99-296), "
                               "ml/evaluation/RESULTS.md 2026-10-01; no model weights changed."),
    }
    if config.DETECTOR_FREQUENCY_ENABLED:
        rows[TYPE_FREQUENCY] = dict(
            model_name=config.DETECTOR_FREQUENCY_NAME,
            model_version=f"{config.DETECTOR_FREQUENCY_UPSTREAM_COMMIT[:7]}-{digest[:12]}-{resize}-{sign}",
            artifact_ref=config.DETECTOR_FREQUENCY_FILENAME, artifact_sha256=digest,
            hyperparameters={"weights_file": config.DETECTOR_FREQUENCY_FILENAME, "weights_digest": digest,
                             "ai_is_positive": config.DETECTOR_FREQUENCY_AI_IS_POSITIVE,
                             "resize_to": config.DETECTOR_FREQUENCY_RESIZE_TO, "head": None},
            training_reference=BASELINE_REFERENCE)
    return rows


# --------------------------------------------------------------------------
# Rows -> runtime configuration
# --------------------------------------------------------------------------

def _valid_semantic(h: dict | None) -> bool:
    return bool(h) and h.get("checkpoint") == config.DETECTOR_PRIMARY \
        and h.get("revision") == config.DETECTOR_PRIMARY_REVISION and "head" in h


def _valid_frequency(h: dict | None) -> bool:
    return bool(h) and h.get("weights_digest") == config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST \
        and isinstance(h.get("ai_is_positive"), bool) and "head" in h


def _valid_fusion(h: dict | None) -> bool:
    try:
        return h["strategy"] == "weighted_average" and 0.0 <= float(h["weight_semantic"]) <= 1.0 \
            and 0.0 < float(h["tau"]) < 1.0 and float(h["temperature"]) > 0.0
    except (KeyError, TypeError, ValueError):
        return False


VALIDATORS = {TYPE_SEMANTIC: _valid_semantic, TYPE_FREQUENCY: _valid_frequency, TYPE_FUSION: _valid_fusion}


def _set_from_rows(rows: dict) -> ActiveModelSet:
    sem = rows[TYPE_SEMANTIC]
    fus = rows[TYPE_FUSION]
    h = fus.hyperparameters
    frequency = None
    if config.DETECTOR_FREQUENCY_ENABLED:
        fr = rows[TYPE_FREQUENCY]
        fh = fr.hyperparameters
        frequency = SpectralDetectorConfig(
            model_id=fr.model_id, name=fr.model_name, filename=fh["weights_file"],
            weights_digest=fh["weights_digest"], ai_is_positive=fh["ai_is_positive"],
            resize_to=fh.get("resize_to"), feature_batch=config.DETECTOR_FREQUENCY_FEATURE_BATCH,
            head=fh.get("head"), artifact_sha256=fr.artifact_sha256)
    return ActiveModelSet(
        primary=DetectorConfig(model_id=sem.model_id, checkpoint=sem.hyperparameters["checkpoint"],
                               role="primary", revision=sem.hyperparameters["revision"],
                               head=sem.hyperparameters.get("head"), artifact_sha256=sem.artifact_sha256),
        frequency_detector=frequency,
        spectral_features=_spectral_features(),
        fusion=FusionModelConfig(model_id=fus.model_id, strategy=h["strategy"],
                                 weight=float(h["weight_semantic"]), tau=float(h["tau"]),
                                 temperature=float(h["temperature"])),
    )


def _needed_types() -> tuple[str, ...]:
    return TYPES if config.DETECTOR_FREQUENCY_ENABLED else (TYPE_SEMANTIC, TYPE_FUSION)


def _active_rows(db: Session) -> dict:
    from app.m2_analysis.models import ModelRegistry

    rows = db.query(ModelRegistry).filter(ModelRegistry.is_active.is_(True)).all()
    return {r.model_type: r for r in rows}


def active(db: Session) -> ActiveModelSet:
    """The configuration to run NOW, read from D3 (bootstrapping it if empty)."""
    rows = _active_rows(db)
    if any(t not in rows or not VALIDATORS[t](rows[t].hyperparameters) for t in _needed_types()):
        ensure_registry(db)
        rows = _active_rows(db)
    missing = [t for t in _needed_types() if t not in rows or not VALIDATORS[t](rows[t].hyperparameters)]
    if missing:
        raise ModelUnavailableError(f"no valid active model for {missing}")
    return _set_from_rows(rows)


def ensure_registry(db: Session) -> None:
    """Register + activate the published baseline for any type without a VALID
    active row (fresh database, or legacy rows from before Phase 4). Legacy
    rows are kept - predictions reference them - just no longer active."""
    from app.m2_analysis.models import ModelActivation, ModelRegistry

    for attempt in range(2):  # a concurrent first request may win the insert race
        try:
            current = _active_rows(db)
            for model_type, spec in baseline_rows().items():
                row = current.get(model_type)
                if row is not None and VALIDATORS[model_type](row.hyperparameters):
                    continue
                target = (db.query(ModelRegistry)
                          .filter(ModelRegistry.model_name == spec["model_name"],
                                  ModelRegistry.model_version == spec["model_version"]).first())
                if target is None:
                    target = ModelRegistry(model_type=model_type, metrics=None, is_active=False, **spec)
                    db.add(target)
                    db.flush()
                previous = row.model_id if row is not None else None
                if row is not None:
                    row.is_active = False
                    db.flush()
                target.is_active = True
                db.add(ModelActivation(model_type=model_type, model_id=target.model_id,
                                       previous_model_id=previous, action="bootstrap", forced=False,
                                       reason="published baseline registered from config"))
                db.flush()
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            if attempt:
                raise


# --------------------------------------------------------------------------
# Activation, canary, rollback
# --------------------------------------------------------------------------

def canary(row) -> dict:
    """A forward pass with the candidate on a fixed synthetic image.

    Must produce a finite probability in [0, 1] (and, for a semantic head, a
    resolvable AI index). Fusion configurations are exercised on fixed score
    pairs. Raises RegistryError MDL_CANARY_FAILED otherwise.
    """
    import tempfile
    from pathlib import Path

    import numpy as np
    from PIL import Image

    from app.m2_analysis import detectors, frequency_detector, fusion, heads

    try:
        if row.model_type == TYPE_FUSION:
            cfg = _fusion_config(row)
            outputs = [fusion.combine(s, f, cfg) for s, f in ((0.1, 0.2), (0.9, 0.8), (0.5, None))]
            if not all(math.isfinite(o[0]) and o[1] in ("Real", "AI Generated") for o in outputs):
                raise ValueError(f"fusion outputs not finite/valid: {outputs}")
            return {"ok": True, "fused": [round(o[0], 6) for o in outputs]}
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "canary.png"
            Image.fromarray(np.random.default_rng(1234).integers(0, 256, (448, 448, 3), dtype=np.uint8)).save(path)
            h = row.hyperparameters
            if row.model_type == TYPE_SEMANTIC:
                head = heads.semantic_head(row.model_id, h.get("head"))
                score = detectors.primary.score(str(path), head=head).score
            else:
                head = heads.frequency_head(row.model_id, h.get("head"))
                score = frequency_detector.frequency.score(
                    str(path), head=head, ai_is_positive=h["ai_is_positive"]).score
        if not (math.isfinite(score) and 0.0 <= score <= 1.0):
            raise ValueError(f"score {score!r} is not a finite probability")
        return {"ok": True, "score": round(score, 6)}
    except RegistryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RegistryError("MDL_CANARY_FAILED", f"canary forward pass failed: {exc}", 422) from exc


def _fusion_config(row) -> FusionModelConfig:
    h = row.hyperparameters
    return FusionModelConfig(model_id=row.model_id, strategy=h["strategy"], weight=float(h["weight_semantic"]),
                             tau=float(h["tau"]), temperature=float(h["temperature"]))


@dataclass
class ActivationResult:
    model_id: int
    model_type: str
    previous_model_id: int | None
    action: str
    forced: bool
    canary: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)


def activate(db: Session, model_id: int, *, actor_id: int | None, force: bool = False,
             reason: str | None = None, action: str = "activate") -> ActivationResult:
    """Canary -> quality gate -> atomic switch. Refusals raise RegistryError.

    ``force`` skips a REFUSING gate verdict only; it requires a reason and is
    recorded (model_activations.forced, D6 warning). The canary is never
    skippable: a model that cannot produce a finite probability never runs.
    """
    from app.m2_analysis import gate
    from app.m2_analysis.models import ModelActivation, ModelRegistry

    target = db.get(ModelRegistry, model_id)
    if target is None:
        raise RegistryError("MDL_NOT_FOUND", f"model #{model_id} does not exist", 404)
    if target.model_type not in _needed_types():
        raise RegistryError("MDL_INVALID", f"model type {target.model_type!r} is not in use", 422)
    if not VALIDATORS[target.model_type](target.hyperparameters):
        raise RegistryError("MDL_INVALID", f"model #{model_id} does not describe the resident "
                            "backbone or has an invalid configuration", 422)
    if force and not (reason and reason.strip()):
        raise RegistryError("MDL_FORCE_NEEDS_REASON", "a forced activation must give a reason", 422)
    if action == "rollback" and db.query(ModelActivation).filter(
            ModelActivation.model_id == model_id).first() is None:
        # The advisory gate is only for returning to a model that already ran
        # in production; a never-activated row must take the gated path.
        raise RegistryError("MDL_ROLLBACK_NOT_PREVIOUS", f"model #{model_id} was never active; "
                            "rollback can only return to a previously active model", 409)

    canary_result = canary(target)
    current_set = active(db)
    gate_result = gate.evaluate(current_set, target)
    # A rollback returns to a model that was previously ACTIVE (it passed its
    # own gate, or is the bootstrapped published baseline). Gating that return
    # against whatever is active now would block the emergency exit the
    # rollback exists for, so for rollbacks the gate is ADVISORY: computed,
    # recorded in model_activations and the audit log, but not blocking. The
    # canary still is.
    if action == "rollback":
        gate_result = {**gate_result, "advisory": True}
    elif not gate_result["passed"] and not force:
        raise RegistryError("MDL_GATE_REFUSED", "the quality gate refused this model: "
                            + "; ".join(gate_result["reasons"]), 409, {"gate": gate_result})

    # The switch: rows of this type locked (PostgreSQL FOR UPDATE; SQLite
    # serialises writers), then deactivate -> activate -> record, one commit.
    # The partial unique index rejects any interleaving that would leave two
    # active rows of a type.
    rows = (db.query(ModelRegistry).filter(ModelRegistry.model_type == target.model_type)
            .with_for_update().all())
    current = next((r for r in rows if r.is_active), None)
    previous = current.model_id if current else None
    if current is not None and current.model_id != target.model_id:
        current.is_active = False
        db.flush()
    target = next(r for r in rows if r.model_id == model_id)
    target.is_active = True
    db.add(ModelActivation(model_type=target.model_type, model_id=target.model_id,
                           previous_model_id=previous, activated_by=actor_id, action=action,
                           forced=bool(force and not gate_result["passed"] and action != "rollback"),
                           reason=reason, gate=gate_result, activated_at=datetime.now(timezone.utc)))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RegistryError("MDL_CONFLICT", "another activation of this model type committed "
                            "first; nothing was changed - retry", 409) from exc
    return ActivationResult(model_id=target.model_id, model_type=target.model_type,
                            previous_model_id=previous, action=action,
                            forced=bool(force and not gate_result["passed"] and action != "rollback"),
                            canary=canary_result, gate=gate_result)


def config_drift(db: Session) -> list[str]:
    """Where config's baseline differs from what is ACTIVE in D3.

    Config is only a seed since Phase 4: editing it changes nothing until a
    row is registered and activated. Reported at startup so an operator who
    edited config.py is not misled into thinking the edit took effect.
    """
    current = _active_rows(db)
    drift = []
    for model_type, spec in baseline_rows().items():
        row = current.get(model_type)
        if row is None:
            continue
        if (row.model_name, row.model_version) != (spec["model_name"], spec["model_version"]):
            drift.append(f"{model_type}: ACTIVE is #{row.model_id} {row.model_name} {row.model_version}; "
                         f"config.py describes {spec['model_name']} {spec['model_version']}")
    return drift


def preview(db: Session, model_id: int) -> dict:
    """The canary and quality-gate verdict activation WOULD reach - nothing
    switches, nothing is written (Phase 5b: the admin screen shows these
    metrics per candidate before anyone decides). Same refusals as activate()
    for a missing or invalid row.

    Strictly read-only: no D3/D4/D6 row, no head-cache entry. The only file
    touched is the canary's synthetic image, inside a TemporaryDirectory that
    is deleted on exit; the gate's reference cache is only read.
    """
    from app.m2_analysis import gate, heads
    from app.m2_analysis.models import ModelRegistry

    target = db.get(ModelRegistry, model_id)
    if target is None:
        raise RegistryError("MDL_NOT_FOUND", f"model #{model_id} does not exist", 404)
    if target.model_type not in _needed_types():
        raise RegistryError("MDL_INVALID", f"model type {target.model_type!r} is not in use", 422)
    if not VALIDATORS[target.model_type](target.hyperparameters):
        raise RegistryError("MDL_INVALID", f"model #{model_id} does not describe the resident "
                            "backbone or has an invalid configuration", 422)
    # Strictly read-only: never bootstrap or repair D3 here (active() would),
    # and never add the candidate's head to the process-wide head cache.
    rows = _active_rows(db)
    missing = [t for t in _needed_types() if t not in rows or not VALIDATORS[t](rows[t].hyperparameters)]
    if missing:
        raise RegistryError("MDL_NO_ACTIVE_CONFIGURATION", f"no valid active model for {missing}; "
                            "a preview never bootstraps the registry - run one prediction first", 409)
    with heads.no_store():
        canary_result = canary(target)
        gate_result = gate.evaluate(_set_from_rows(rows), target)
    return {"model_id": model_id, "model_type": target.model_type, "is_active": target.is_active,
            "canary": canary_result, "gate": gate_result}


def rollback(db: Session, model_type: str, *, actor_id: int | None, force: bool = False,
             reason: str | None = None) -> ActivationResult:
    """Re-activate the model that was active before the latest change of this type.

    One call. Runs the canary; the quality gate is advisory here (see
    ``activate``) - its verdict is recorded, not enforced.
    """
    from app.m2_analysis.models import ModelActivation

    last = (db.query(ModelActivation).filter(ModelActivation.model_type == model_type)
            .order_by(ModelActivation.activation_id.desc()).first())
    if last is None or last.previous_model_id is None:
        raise RegistryError("MDL_NOTHING_TO_ROLL_BACK", f"no previous {model_type} to return to", 409)
    return activate(db, last.previous_model_id, actor_id=actor_id, force=force,
                    reason=reason or f"rollback of activation #{last.activation_id}", action="rollback")
