"""Registering uploaded model artefacts (Phase 4, F.19). Never executes anything.

Accepted, per model type - and nothing else:

    fusion-configuration           JSON  {"strategy": "weighted_average",
                                          "weight_semantic": w, "tau": t,
                                          "temperature": T}            <= 16 KB
    semantic-classifier            safetensors with exactly the published
                                   classifier's tensors ("classifier.weight"
                                   [2, 768], "classifier.bias" [2]) + id2label  <= 1 MB
    frequency-artifact-classifier  safetensors with exactly SPAI's cls_head
                                   tensors ("cls_head.head.{0,3,6}.*") + the
                                   sign convention                      <= 64 MB

Backbones are never replaced (out of scope): only the final head, or the
fusion configuration.

Security:
- Heads are parsed with ``safetensors.torch.load`` from bytes - a JSON header
  plus raw tensor data, no code. A pickle (.pt/.pth/.pkl) is not valid
  safetensors and is refused; ``torch.load`` and pickle appear nowhere.
- Keys, shapes and dtype must equal the live head's EXACTLY; every value must
  be finite. JSON is parsed with NaN/Infinity rejected and a strict schema.
- Files are stored as storage/models/uploads/<sha256>.safetensors - the name
  is the content hash, never the client's filename - and the SHA-256 is
  recorded in the D3 row and the audit log. storage/models is not served by
  any route.
- Registration only adds an INACTIVE row; activation (canary + quality gate)
  is a separate, audited step.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile

import torch
from sqlalchemy.orm import Session

from app.m2_analysis import registry
from app.m2_analysis.registry import RegistryError
from app.shared import config

MAX_BYTES = {
    registry.TYPE_FUSION: 16 * 1024,
    registry.TYPE_SEMANTIC: 1 * 1024 * 1024,
    registry.TYPE_FREQUENCY: 64 * 1024 * 1024,
}
UPLOADS = "uploads"


def _refuse(message: str, status: int = 422, code: str = "MDL_INVALID_ARTIFACT"):
    raise RegistryError(code, message, status)


def _reject_constant(name):
    _refuse(f"non-finite number {name} in fusion configuration")


def parse_fusion(data: bytes) -> dict:
    try:
        payload = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse(f"fusion configuration is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        _refuse("fusion configuration must be a JSON object")
    allowed = {"strategy", "weight_semantic", "tau", "temperature"}
    extra = set(payload) - allowed
    if extra or set(payload) != allowed:
        _refuse(f"fusion configuration must have exactly {sorted(allowed)}; got {sorted(payload)}")
    if payload["strategy"] != "weighted_average":
        _refuse("only strategy 'weighted_average' exists (a meta-classifier would need training)")
    try:
        w, tau, t = (float(payload[k]) for k in ("weight_semantic", "tau", "temperature"))
    except (TypeError, ValueError):
        _refuse("weight_semantic, tau and temperature must be numbers")
    if isinstance(payload["weight_semantic"], bool) or not all(math.isfinite(v) for v in (w, tau, t)):
        _refuse("weight_semantic, tau and temperature must be finite numbers")
    if not 0.0 <= w <= 1.0:
        _refuse("weight_semantic must be in [0, 1]")
    if not 0.0 < tau < 1.0:
        _refuse("tau must be in (0, 1)")
    if not 0.0 < t <= 100.0:
        _refuse("temperature must be in (0, 100]")
    return {"strategy": "weighted_average", "weight_semantic": w, "weight_frequency": 1.0 - w,
            "tau": tau, "temperature": t}


def _expected_head(model_type: str) -> dict[str, torch.Tensor]:
    from app.m2_analysis import detectors, frequency_detector, heads

    if model_type == registry.TYPE_SEMANTIC:
        # Semantic head uploads target SigLIP 2's classifier (Community
        # Forensics rows carry no uploaded head - registry._valid_semantic).
        return {heads.SEMANTIC_PREFIX + k: v
                for k, v in detectors.semantic(config.SEMANTIC_SIGLIP).classifier_state().items()}
    return {heads.FREQUENCY_PREFIX + k: v for k, v in frequency_detector.frequency.cls_head_state().items()}


def parse_head(model_type: str, data: bytes) -> dict[str, torch.Tensor]:
    from safetensors.torch import load as load_safetensors

    try:
        tensors = load_safetensors(data)  # tensors only; no code, no pickle
    except Exception as exc:  # noqa: BLE001 - any parse failure is a refusal
        _refuse(f"not a valid safetensors file (pickled checkpoints are refused): {type(exc).__name__}")
    expected = _expected_head(model_type)
    if set(tensors) != set(expected):
        missing, extra = sorted(set(expected) - set(tensors)), sorted(set(tensors) - set(expected))
        _refuse(f"head tensors do not match the live head: missing {missing}, unexpected {extra}")
    for key, value in tensors.items():
        ref = expected[key]
        if tuple(value.shape) != tuple(ref.shape):
            _refuse(f"{key}: shape {tuple(value.shape)} != live {tuple(ref.shape)}")
        if value.dtype != torch.float32:
            _refuse(f"{key}: dtype {value.dtype} != torch.float32")
        if not torch.isfinite(value).all():
            _refuse(f"{key}: contains NaN or infinite values")
    return tensors


def _store(data: bytes, sha: str) -> str:
    """Write under the content hash, atomically. Returns the path relative to MODELS_DIR."""
    folder = config.MODELS_DIR / UPLOADS
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{sha}.safetensors"
    if not target.exists():
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, target)
    return f"{UPLOADS}/{sha}.safetensors"


def register(db: Session, *, model_type: str, name: str, version: str, training_reference: str,
             data: bytes, actor_id: int | None, id2label: dict | None = None,
             ai_is_positive: bool | None = None):
    """Validate an artefact and add it to D3 as an INACTIVE row."""
    from app.m2_analysis.detectors import resolve_ai_index
    from app.m2_analysis.models import ModelRegistry
    from app.shared.logging import emit

    if model_type not in MAX_BYTES:
        _refuse(f"model_type must be one of {sorted(MAX_BYTES)}")
    if model_type == registry.TYPE_FREQUENCY and not config.DETECTOR_FREQUENCY_ENABLED:
        _refuse("the frequency branch is disabled")
    if not (name or "").strip() or len(name) > 120 or not (version or "").strip() or len(version) > 40:
        _refuse("name (1-120 chars) and version (1-40 chars) are required")
    if not (training_reference or "").strip():
        _refuse("training_reference is required: what the artefact was trained / evaluated on")
    if len(data) == 0 or len(data) > MAX_BYTES[model_type]:
        _refuse(f"artefact size {len(data)} bytes is outside (0, {MAX_BYTES[model_type]}] for {model_type}",
                413, "MDL_TOO_LARGE")
    sha = hashlib.sha256(data).hexdigest()

    if model_type == registry.TYPE_FUSION:
        hyper = parse_fusion(data)
        artifact_ref = "upload: fusion configuration (canonical JSON in hyperparameters)"
        sha = registry.canonical_sha256(hyper)
    else:
        parse_head(model_type, data)
        head = {"file": None, "sha256": sha}
        if model_type == registry.TYPE_SEMANTIC:
            if not isinstance(id2label, dict) or len(id2label) != 2:
                _refuse("a semantic head needs id2label with exactly two labels, e.g. {\"0\": \"Real\", \"1\": \"AI\"}")
            try:
                labels = {int(k): str(v) for k, v in id2label.items()}
                resolve_ai_index(labels)
            except Exception as exc:  # noqa: BLE001
                _refuse(f"id2label cannot be resolved to an AI class: {exc}")
            head["id2label"] = {str(k): v for k, v in labels.items()}
        elif not isinstance(ai_is_positive, bool):
            _refuse("a frequency head needs ai_is_positive (true/false): which sign of the logit means AI")
        head["file"] = _store(data, sha)
        base = (registry.semantic_row_spec(config.SEMANTIC_SIGLIP)["hyperparameters"]
                if model_type == registry.TYPE_SEMANTIC
                else registry.baseline_rows()[model_type]["hyperparameters"])
        hyper = {**base, "head": head}
        if model_type == registry.TYPE_FREQUENCY:
            hyper["ai_is_positive"] = ai_is_positive
        artifact_ref = head["file"]

    if db.query(ModelRegistry).filter(ModelRegistry.model_name == name.strip(),
                                      ModelRegistry.model_version == version.strip()).first():
        _refuse(f"{name} {version} is already registered", 409, "MDL_EXISTS")
    row = ModelRegistry(model_name=name.strip(), model_version=version.strip(), model_type=model_type,
                        artifact_ref=artifact_ref, artifact_sha256=sha, hyperparameters=hyper,
                        metrics=None, is_active=False, training_reference=training_reference.strip(),
                        registered_by=actor_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    emit("administrative-action", f"Model registered: #{row.model_id} {row.model_type} "
         f"{row.model_name} {row.model_version} sha256={sha}", severity="info", user_id=actor_id)
    return row
