"""
Contract Verification Tests (Contracts C1, C2, C3, C4, C5).
Asserts boundaries, schemas, and confidence inversion rules from Interface Contract v1.0.
"""
from __future__ import annotations
from datetime import datetime, timezone
import pytest

from app.shared.schemas import (
    NormalizationParams,
    PreprocessedImage,
    InferenceOutput,
    ActivationBundle,
    SessionContext,
    ErrorEnvelope,
)
from app.stubs.m1_stub import create_dummy_user, create_dummy_image, prepare_model_input
from app.stubs.m2_stub import run_detection, seed_dummy_models
from app.m3_results.logging_service import redact_secrets
from app.m3_results.models import LogEntry


def test_contract_c1_preprocessed_image_schema(db_session):
    """Validates that PreprocessedImage matches Contract C1."""
    user = create_dummy_user(db_session)
    img = create_dummy_image(db_session, user_id=user.user_id, storage_dir="./uploads/test_images")
    session = SessionContext(
        user_id=user.user_id,
        email=user.email,
        role="User",
        account_status="active",
        session_token="test-tok",
        expires_at=datetime.now(timezone.utc),
    )

    prep = prepare_model_input(img.image_id, session, db_session, tensor_dir="./uploads/test_tensors")
    assert prep.shape == (3, 224, 224)
    assert prep.dtype == "float32"
    assert prep.normalization.scheme == "clip_openai"
    assert prep.source_reference == img.file_reference


def test_contract_c2_confidence_score_inversion_rule(db_session):
    """
    Validates Contract C2 §5.2: Confidence score is the confidence IN the predicted class,
    not raw fusion_score.
    """
    user = create_dummy_user(db_session)
    img = create_dummy_image(db_session, user_id=user.user_id, storage_dir="./uploads/test_images")
    session = SessionContext(
        user_id=user.user_id,
        email=user.email,
        role="User",
        account_status="active",
        session_token="test-tok",
        expires_at=datetime.now(timezone.utc),
    )

    prep = prepare_model_input(img.image_id, session, db_session, tensor_dir="./uploads/test_tensors")

    # Force "Real" class (low fusion score)
    out_real = run_detection(prep, db_session, force_class="Real")
    assert out_real.predicted_class == "Real"
    assert out_real.confidence_score > 0.50
    assert abs(out_real.confidence_score - (1.0 - out_real.fusion_score)) < 1e-4

    # Force "AI Generated" class (high fusion score)
    out_ai = run_detection(prep, db_session, force_class="AI Generated")
    assert out_ai.predicted_class == "AI Generated"
    assert out_ai.confidence_score >= 0.50
    assert abs(out_ai.confidence_score - out_ai.fusion_score) < 1e-4


def test_contract_c5_logging_emission(db_session):
    """Validates Contract C5 logging entry structure and secret scrubbing."""
    detail = "User authenticated with bearer token test-token-12345678"
    sanitized = redact_secrets(detail)
    entry = LogEntry(
        user_id=1,
        event_type="authentication",
        event_detail=sanitized,
        severity="info",
        log_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(entry)
    db_session.commit()

    saved = db_session.query(LogEntry).filter(LogEntry.user_id == 1).first()
    assert saved is not None
    assert "test-token" not in saved.event_detail
    assert saved.severity == "info"
    assert saved.event_type == "authentication"
