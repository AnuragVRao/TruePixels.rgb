"""Quality gate for model activation (Phase 4, F.19).

Before a candidate becomes active it is compared with the CURRENT active
configuration on a fixed reference sample from the VALIDATION split
(``sbr_val``, scenes 99-296) - never the held-out test set. The sample is
cached once by ``backend/scripts/build_reference_set.py``: per image, the
label, the live branch scores, and the exact inputs of each branch's final
head (SigLIP's pooled 768-d features, SPAI's 1096-d features). A candidate
head or fusion configuration is then evaluated on those cached inputs in
milliseconds - no image is decoded or re-run through a backbone.

Thresholds, fixed on 2026-10-03 BEFORE any candidate was scored (recorded in
the phase plan). A candidate is REFUSED if, versus the current configuration:

    accuracy at its own tau drops by more than   MAX_ACCURACY_DROP = 0.05
    false-positive rate on real images exceeds   MAX_FPR           = 0.20
    ROC-AUC of the fused score drops by more than MAX_AUC_DROP      = 0.02

MAX_FPR is twice MM2.6's 0.10. A candidate must ALSO stay within wider
floors of the ORIGINAL published baseline (accuracy -0.08, AUC -0.04), so
small per-step drops cannot ratchet.

THIS IS A COARSE SAFETY NET. 100 images (50 per class) have a standard error
of about 0.04 on accuracy: the gate catches gross breakage - inverted labels,
a threshold that calls everything AI, a corrupted head - not subtle
degradation, and it cannot certify a candidate as good. An admin may force past a refusal only with a
reason; that is recorded and audit-logged by the registry.

Integrity check: before evaluating anything, the published heads applied to
the cached inputs must reproduce the cached live scores (|diff| < 1e-4). If
they do not - the cache was built for different weights - the gate is
"unavailable" and refuses.
"""

from __future__ import annotations

import numpy as np
import torch
from sklearn.metrics import roc_auc_score

from app.shared import config

MAX_ACCURACY_DROP = 0.05
MAX_FPR = 0.20
MAX_AUC_DROP = 0.02

# Anchored to the ORIGINAL published baseline (added after the Phase 4 review,
# fixed before scoring): the per-step check alone lets small drops ratchet -
# each step within 0.05 of the last - so a candidate must also stay within
# these wider floors of the baseline itself.
BASELINE_MAX_ACCURACY_DROP = 0.08
BASELINE_MAX_AUC_DROP = 0.04
REPRODUCTION_TOLERANCE = 1e-4


def key_inputs(images: list) -> dict:
    """Everything the cached features depend on. Any change => a different key.

    ``images`` is the manifest's list of [relative path, file SHA-256]: the
    files are not re-hashed at activation time (they may not even be present);
    their hashes were recorded when the cache was built.
    """
    from app.m2_analysis import detectors, xai

    detectors.primary.load()
    processor = detectors.primary._processor.to_dict()
    return {
        "semantic_checkpoint": config.DETECTOR_PRIMARY,
        "semantic_revision": config.DETECTOR_PRIMARY_REVISION,
        "semantic_processor": processor,
        "spai_weights_digest": config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST,
        "spai_preprocess": {"resize_to": config.DETECTOR_FREQUENCY_RESIZE_TO,
                            "patch_size": xai.PATCH_SIZE, "patch_stride": xai.PATCH_STRIDE,
                            "minimum_patches": xai.MINIMUM_PATCHES, "mask_radius": xai.MASK_RADIUS,
                            "input": "RGB [0,1], even-trimmed (frequency_detector.prepare_image)"},
        "images": [list(item) for item in images],
    }


def reference_key(images: list) -> str:
    import hashlib
    import json

    blob = json.dumps(key_inputs(images), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def reference_path():
    rev = config.DETECTOR_PRIMARY_REVISION[:12]
    digest = config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST[:12]
    return config.MODELS_DIR / "reference" / f"reference_sbr_val_{rev}_{digest}.npz"


def load_reference() -> dict | None:
    path = reference_path()
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def stale_reason(reference: dict) -> str | None:
    """Why the cache cannot be trusted for the CURRENT models/preprocessing, or None."""
    import json

    manifest_path = reference_path().with_suffix(".json")
    if "cache_key" not in reference or not manifest_path.is_file():
        return "reference cache has no content key (built before keying); rebuild it"
    manifest = json.loads(manifest_path.read_text())
    expected = reference_key(manifest.get("images", []))
    if str(reference["cache_key"]) != expected:
        return ("reference cache is stale: backbone revision, weights, preprocessing or the "
                "reference image list changed since it was built; rebuild it")
    return None


def _semantic_probs(features: np.ndarray, head_spec: dict | None, model_id: int | None) -> np.ndarray:
    from app.m2_analysis import detectors, heads

    detectors.primary.load()
    if head_spec:
        loaded = heads.semantic_head(model_id, head_spec)
        module, ai_index = loaded.module, loaded.ai_index
    else:
        module, ai_index = detectors.primary._model.classifier, detectors.primary.ai_index
    with torch.inference_mode():
        x = torch.from_numpy(features).to(config.DEVICE, dtype=next(module.parameters()).dtype)
        probs = torch.softmax(module(x), dim=-1)[:, ai_index]
    return probs.double().cpu().numpy()


def _frequency_probs(features: np.ndarray, head_spec: dict | None, model_id: int | None,
                     ai_is_positive: bool) -> np.ndarray:
    from app.m2_analysis import frequency_detector, heads

    module = (heads.frequency_head(model_id, head_spec).module if head_spec
              else frequency_detector.frequency.cls_head_module())
    with torch.inference_mode():
        x = torch.from_numpy(features).to(config.DEVICE, dtype=next(module.parameters()).dtype)
        p = torch.sigmoid(module(x).reshape(-1)).double().cpu().numpy()
    return p if ai_is_positive else 1.0 - p


def _metrics(semantic: np.ndarray, frequency: np.ndarray, fusion_cfg, labels: np.ndarray) -> dict:
    from app.m2_analysis import fusion

    fused, predicted = [], []
    for s, f in zip(semantic, frequency):
        score, cls, _ = fusion.combine(float(s), float(f), fusion_cfg)
        fused.append(score)
        predicted.append(1 if cls == "AI Generated" else 0)
    fused, predicted = np.array(fused), np.array(predicted)
    real, fake = labels == 0, labels == 1
    return {
        "accuracy": float((predicted == labels).mean()),
        "fpr": float(predicted[real].mean()),
        "recall": float(predicted[fake].mean()),
        "auc": float(roc_auc_score(labels, fused)),
        "predicted_ai": int(predicted.sum()),
        "_predicted": predicted,
    }


def _branch_probs(model_set, reference) -> tuple[np.ndarray, np.ndarray]:
    sem = _semantic_probs(reference["semantic_features"], model_set.primary.head, model_set.primary.model_id)
    fr = model_set.frequency_detector
    freq = _frequency_probs(reference["frequency_features"], fr.head, fr.model_id, fr.ai_is_positive)
    return sem, freq


def evaluate(current_set, candidate_row) -> dict:
    """Compare the candidate row (replacing its type) with the current set."""
    from dataclasses import replace

    from app.m2_analysis import registry

    reference = load_reference()
    if reference is None:
        return {"passed": False, "available": False,
                "reasons": [f"reference set not built ({reference_path().name}); run "
                            "backend/scripts/build_reference_set.py"]}
    stale = stale_reason(reference)
    if stale:
        return {"passed": False, "available": False, "reasons": [stale]}
    labels = reference["labels"].astype(int)

    # Integrity: published heads on cached inputs must reproduce the cached live scores.
    published = registry.baseline()
    sem_pub, freq_pub = _branch_probs(published, reference)
    drift = max(float(np.max(np.abs(sem_pub - reference["semantic_scores"]))),
                float(np.max(np.abs(freq_pub - reference["frequency_scores"]))))
    if drift > REPRODUCTION_TOLERANCE:
        return {"passed": False, "available": False,
                "reasons": [f"reference cache does not reproduce the live scores (max diff {drift:.2e}); rebuild it"]}

    h = candidate_row.hyperparameters
    candidate_set = current_set
    if candidate_row.model_type == registry.TYPE_SEMANTIC:
        candidate_set = replace(current_set, primary=replace(current_set.primary,
                                model_id=candidate_row.model_id, head=h.get("head")))
    elif candidate_row.model_type == registry.TYPE_FREQUENCY:
        candidate_set = replace(current_set, frequency_detector=replace(
            current_set.frequency_detector, model_id=candidate_row.model_id, head=h.get("head"),
            ai_is_positive=h["ai_is_positive"]))
    else:
        candidate_set = replace(current_set, fusion=registry._fusion_config(candidate_row))

    cur = _metrics(*_branch_probs(current_set, reference), current_set.fusion, labels)
    cand = _metrics(*_branch_probs(candidate_set, reference), candidate_set.fusion, labels)
    flipped = int((cur.pop("_predicted") != cand.pop("_predicted")).sum())

    base = _metrics(sem_pub, freq_pub, published.fusion, labels)
    base.pop("_predicted")

    reasons = []
    if cand["accuracy"] < cur["accuracy"] - MAX_ACCURACY_DROP:
        reasons.append(f"accuracy {cand['accuracy']:.3f} vs {cur['accuracy']:.3f} "
                       f"(drop > {MAX_ACCURACY_DROP})")
    if cand["fpr"] > MAX_FPR:
        reasons.append(f"false-positive rate {cand['fpr']:.3f} > {MAX_FPR}")
    if cand["auc"] < cur["auc"] - MAX_AUC_DROP:
        reasons.append(f"AUC {cand['auc']:.3f} vs {cur['auc']:.3f} (drop > {MAX_AUC_DROP})")
    if cand["accuracy"] < base["accuracy"] - BASELINE_MAX_ACCURACY_DROP:
        reasons.append(f"accuracy {cand['accuracy']:.3f} vs published baseline {base['accuracy']:.3f} "
                       f"(drop > {BASELINE_MAX_ACCURACY_DROP})")
    if cand["auc"] < base["auc"] - BASELINE_MAX_AUC_DROP:
        reasons.append(f"AUC {cand['auc']:.3f} vs published baseline {base['auc']:.3f} "
                       f"(drop > {BASELINE_MAX_AUC_DROP})")
    return {
        "passed": not reasons, "available": True, "reasons": reasons,
        "reference": {"file": reference_path().name, "images": int(len(labels)),
                      "real": int((labels == 0).sum()), "generated": int((labels == 1).sum()),
                      "split": "sbr_val (validation, scenes 99-296)"},
        "thresholds": {"max_accuracy_drop": MAX_ACCURACY_DROP, "max_fpr": MAX_FPR,
                       "max_auc_drop": MAX_AUC_DROP,
                       "baseline_max_accuracy_drop": BASELINE_MAX_ACCURACY_DROP,
                       "baseline_max_auc_drop": BASELINE_MAX_AUC_DROP},
        "baseline": {k: round(v, 4) if isinstance(v, float) else v for k, v in base.items()},
        "current": {k: round(v, 4) if isinstance(v, float) else v for k, v in cur.items()},
        "candidate": {k: round(v, 4) if isinstance(v, float) else v for k, v in cand.items()},
        "labels_changed": flipped,
    }
