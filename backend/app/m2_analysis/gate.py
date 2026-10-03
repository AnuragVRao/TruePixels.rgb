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

MAX_FPR is twice MM2.6's 0.10. An admin may force past a refusal only with a
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
REPRODUCTION_TOLERANCE = 1e-4


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

    reasons = []
    if cand["accuracy"] < cur["accuracy"] - MAX_ACCURACY_DROP:
        reasons.append(f"accuracy {cand['accuracy']:.3f} vs {cur['accuracy']:.3f} "
                       f"(drop > {MAX_ACCURACY_DROP})")
    if cand["fpr"] > MAX_FPR:
        reasons.append(f"false-positive rate {cand['fpr']:.3f} > {MAX_FPR}")
    if cand["auc"] < cur["auc"] - MAX_AUC_DROP:
        reasons.append(f"AUC {cand['auc']:.3f} vs {cur['auc']:.3f} (drop > {MAX_AUC_DROP})")
    return {
        "passed": not reasons, "available": True, "reasons": reasons,
        "reference": {"file": reference_path().name, "images": int(len(labels)),
                      "real": int((labels == 0).sum()), "generated": int((labels == 1).sum()),
                      "split": "sbr_val (validation, scenes 99-296)"},
        "thresholds": {"max_accuracy_drop": MAX_ACCURACY_DROP, "max_fpr": MAX_FPR,
                       "max_auc_drop": MAX_AUC_DROP},
        "current": {k: round(v, 4) if isinstance(v, float) else v for k, v in cur.items()},
        "candidate": {k: round(v, 4) if isinstance(v, float) else v for k, v in cand.items()},
        "labels_changed": flipped,
    }
