"""
Contract Verification Tests (Contracts C1, C2, C3, C4, C5).
Asserts boundaries, schemas, and the C2 v2 p_ai / certainty rule (2026-10-08; C2 v1.0 section 5.2's
confidence inversion is superseded - see app/shared/contracts/c2.py, revision 4).
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


def test_contract_c2_p_ai_is_shown_for_either_verdict(db_session):
    """
    C2 v2: p_ai is P(AI) for EITHER verdict (not confidence in the predicted class),
    within the [0.01, 0.99] cap, and certainty follows the 0.90 band.
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
    assert out_real.p_ai < 0.50
    assert abs(out_real.p_ai - max(0.01, out_real.fusion_score)) < 1e-4
    assert not hasattr(out_real, "confidence_score")

    # Force "AI Generated" class (high fusion score)
    out_ai = run_detection(prep, db_session, force_class="AI Generated")
    assert out_ai.predicted_class == "AI Generated"
    assert out_ai.p_ai >= 0.50
    assert abs(out_ai.p_ai - min(0.99, out_ai.fusion_score)) < 1e-4
    for out in (out_real, out_ai):
        assert 0.01 <= out.p_ai <= 0.99
        assert out.certainty == ("confident" if out.p_ai >= 0.90 or out.p_ai <= 0.10 else "inconclusive")


def test_contract_c5_logging_emission(db_session):
    """Validates Contract C5 logging entry structure and secret scrubbing."""
    detail = "User authenticated with bearer token test-token-12345678"
    sanitized = redact_secrets(detail)
    # INTEGRATION (Phase 2): the user the log row points at must exist - the
    # D6 -> D1 foreign key is enforced now (PostgreSQL always; SQLite since
    # PRAGMA foreign_keys=ON). Previously user_id=1 referred to nobody.
    create_dummy_user(db_session, email="c5-log@nitk.edu.in", role="User")
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
