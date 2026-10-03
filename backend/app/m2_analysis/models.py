"""SQLAlchemy models for D3 (models) and D4 (predictions) - owned by M2.

These two classes were written by M3 (``app/m3_results/models.py``) so that M3
could run before M2 persisted anything. They move here because M2 owns D3/D4
and is the only writer of D4 (PRD4 section 4.2.4). ``app.m3_results.models``
re-exports both, so every M3 import is unchanged. The columns are M3's,
unchanged, except where noted below. See changes.md.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.shared.db import Base


class ModelRegistry(Base):
    """D3. Models (owned by M2)

    One row per artefact that can take part in a prediction. Because this
    project never trains, a row records WHICH published checkpoint (or which
    fixed fusion configuration) was active - not an artefact we produced.
    """
    __tablename__ = "models"

    model_id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(120), nullable=False)
    model_version = Column(String(40), nullable=False)
    model_type = Column(String(32), nullable=False)  # 'semantic-classifier', 'frequency-artifact-classifier', 'fusion-configuration'
    artifact_ref = Column(Text, nullable=False)
    # Nullable (M3 had NOT NULL): the semantic checkpoint is fetched from the
    # Hugging Face hub by name and no digest of it is pinned in config. Null
    # is the honest value; a made-up hash would not be.
    artifact_sha256 = Column(String(64), nullable=True)
    hyperparameters = Column(JSON, nullable=True)
    # Null for every row M2 registers: no benchmark of this system has been
    # run, and upstream self-reported figures are not ours to record here.
    metrics = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    registered_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    predictions = relationship("Prediction", back_populates="model")

    __table_args__ = (
        UniqueConstraint("model_name", "model_version", name="uq_model_name_version"),
        # At most one active row per model type, enforced by the database
        # (FR-07's atomic activation relies on it). Partial unique index on
        # both backends.
        Index(
            "uq_models_one_active_per_type",
            "model_type",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )


class Prediction(Base):
    """D4. Predictions (owned by M2)"""
    __tablename__ = "predictions"

    prediction_id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(Integer, ForeignKey("images.image_id", ondelete="RESTRICT"), nullable=False, index=True)
    model_id = Column(Integer, ForeignKey("models.model_id", ondelete="RESTRICT"), nullable=False)
    branch_model_ids = Column(JSON, nullable=True)  # e.g. {"semantic": 1, "frequency": 2}
    predicted_class = Column(String(14), nullable=False)  # 'Real', 'AI Generated'
    confidence_score = Column(Float, nullable=False)
    semantic_score = Column(Float, nullable=False)
    # Nullable on purpose: the frequency branch legitimately produces no
    # score when it is switched off, or when the image is below SPAI's 224px
    # patch size. Contract C2 types this `float | None` for the same reason.
    # A stand-in value here would be a lie that survives into reports.
    frequency_score = Column(Float, nullable=True)
    fusion_score = Column(Float, nullable=False)
    # Inference time only (both branches + fusion); excludes model loading.
    latency_ms = Column(Integer, nullable=True)
    # True when a branch had to be loaded inside this request (warm-up off or
    # failed). Excluded from latency statistics: such a request also paid for
    # the load, even though latency_ms does not count it. Null on rows written
    # before Phase 2, when this was not recorded.
    cold_start = Column(Boolean, nullable=True)
    prediction_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # One-directional (M3 had back_populates="predictions"): Image is M1's
    # model and does not declare the reverse side, and nothing reads it.
    image = relationship("Image")
    model = relationship("ModelRegistry", back_populates="predictions")
    explainabilities = relationship("Explainability", back_populates="prediction", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_pred_time", prediction_timestamp.desc()),
    )
