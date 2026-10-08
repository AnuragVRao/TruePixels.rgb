"""
Module M2 Stub (Image Analysis & Prediction) according to Interface Contract Section 10.
Generates deterministic InferenceOutput and ActivationBundle for M3.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
import numpy as np
from sqlalchemy.orm import Session
from app.shared.schemas import PreprocessedImage, InferenceOutput, ActivationBundle
from app.m3_results.models import ModelRegistry, Prediction
from app.m3_results.overlay import generate_and_persist_explainability


def seed_dummy_models(db: Session) -> ModelRegistry:
    """Seeds default active fusion configuration and branch models into D3.models."""
    active_model = db.query(ModelRegistry).filter(ModelRegistry.is_active == True).first()
    if active_model:
        return active_model

    fusion_model = ModelRegistry(
        model_name="TruePixels-Ensemble-ViT-FFT",
        model_version="1.0.0",
        model_type="fusion-configuration",
        artifact_ref="models/fusion_weights_v1.json",
        artifact_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        hyperparameters={"tau": 0.50, "temperature": 1.15, "weight_semantic": 0.60, "weight_frequency": 0.40},
        metrics={"accuracy": 0.942, "precision": 0.931, "recall": 0.955, "f1": 0.943, "roc_auc": 0.978},
        is_active=True,
    )
    db.add(fusion_model)
    db.commit()
    db.refresh(fusion_model)
    return fusion_model


def run_detection(
    prepared: PreprocessedImage,
    db: Session,
    *,
    xai_requested: bool = True,
    force_class: str | None = None,
) -> InferenceOutput:
    """
    Contract C2 Stub: Generates deterministic inference output derived from hash(image_id).
    Persists row to D4.predictions, runs explainability in D5, and returns InferenceOutput.
    """
    active_model = seed_dummy_models(db)

    # Deterministic scores based on image_id hash
    h = int(hashlib.md5(str(prepared.image_id).encode("utf-8")).hexdigest(), 16)
    raw_val = (h % 1000) / 1000.0  # between 0.0 and 1.0

    if force_class == "Real":
        fusion_score = min(0.35, raw_val * 0.35)
    elif force_class == "AI Generated":
        fusion_score = max(0.65, 0.65 + raw_val * 0.35)
    else:
        fusion_score = raw_val

    tau = active_model.hyperparameters.get("tau", 0.50) if active_model.hyperparameters else 0.50

    # Decision rule
    predicted_class = "AI Generated" if fusion_score >= tau else "Real"
    # C2 v2: p_ai is P(AI) for EITHER verdict. The stub has no fitted map; it
    # reports its own fake score, capped like the real one.
    p_ai = min(0.99, max(0.01, fusion_score))
    certainty = "confident" if p_ai >= 0.90 or p_ai <= 0.10 else "inconclusive"
    legacy_confidence = fusion_score if predicted_class == "AI Generated" else 1.0 - fusion_score

    semantic_score = min(1.0, max(0.0, fusion_score + ((h % 20) - 10) / 100.0))
    frequency_score = min(1.0, max(0.0, fusion_score + ((h % 30) - 15) / 100.0))

    # Persist D4.predictions
    pred_row = Prediction(
        image_id=prepared.image_id,
        model_id=active_model.model_id,
        branch_model_ids={"semantic": 1, "frequency": 2},
        predicted_class=predicted_class,
        confidence_score=round(legacy_confidence, 4),  # legacy D4 column until it is dropped
        semantic_score=round(semantic_score, 4),
        frequency_score=round(frequency_score, 4),
        fusion_score=round(fusion_score, 4),
        latency_ms=85,
        prediction_timestamp=datetime.now(timezone.utc),
    )
    db.add(pred_row)
    db.commit()
    db.refresh(pred_row)

    # Construct synthetic ActivationBundle if requested
    bundle = None
    if xai_requested:
        # Realistic ViT attention matrix: (layers=6, heads=4, tokens=50, tokens=50) for 7x7 patch grid + 1 CLS
        num_layers, num_heads, num_tokens = 6, 4, 50
        np.random.seed(prepared.image_id % 10000)
        raw_attn = np.random.uniform(0.01, 1.0, size=(num_layers, num_heads, num_tokens, num_tokens)).astype(np.float32)
        # Normalize softmax style
        raw_attn = raw_attn / raw_attn.sum(axis=-1, keepdims=True)

        # 2D FFT Spectrum (512, 512)
        y, x = np.mgrid[-256:256, -256:256]
        r = np.sqrt(x**2 + y**2) + 1.0
        synthetic_spectrum = (np.log1p(2000.0 / (r**0.75)) + np.random.normal(0, 0.2, (512, 512))).astype(np.float32)

        bundle = ActivationBundle(
            backbone="clip_vit_b32",
            patch_grid=(7, 7),
            attention=raw_attn,
            spectrum=synthetic_spectrum,
        )

        # Automatically execute M3 explainability pipeline and persist in D5
        from app.m3_results.models import Image as DBImage
        db_img = db.query(DBImage).filter(DBImage.image_id == prepared.image_id).first()
        if db_img:
            generate_and_persist_explainability(
                prediction_id=pred_row.prediction_id,
                db_image=db_img,
                activation_bundle=bundle,
                db=db,
            )

    return InferenceOutput(
        prediction_id=pred_row.prediction_id,
        image_id=prepared.image_id,
        user_id=prepared.user_id,
        model_id=active_model.model_id,
        predicted_class=predicted_class,
        p_ai=p_ai,
        certainty=certainty,
        semantic_score=semantic_score,
        frequency_score=frequency_score,
        fusion_score=fusion_score,
        prediction_timestamp=pred_row.prediction_timestamp,
        latency_ms=pred_row.latency_ms,
        activations=bundle,
    )
