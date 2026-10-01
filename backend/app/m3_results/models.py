"""
SQLAlchemy ORM Models for TruePixels.rgb.
Owned by M3: D5 (Explainability) and D6 (Logs).
Referenced schemas: D1 (Users), D2 (Images), D3 (Models), D4 (Predictions).
Uses Integer primary keys for universal auto-increment compatibility across SQLite and Postgres.
"""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    Float,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
)
from sqlalchemy.orm import relationship
from app.shared.db import Base

# INTEGRATION: D1-D4 are no longer redefined here. Declaring a second "users" /
# "images" table on the shared Base fails at import ("Table 'users' is already
# defined"), so the owners' classes are imported instead and re-exported, and
# every existing `from app.m3_results.models import User, Image, ...` still
# works. See changes.md.
from app.m1_access.models import User, Image  # noqa: F401  D1, D2 (owned by M1)
from app.m2_analysis.models import ModelRegistry, Prediction  # noqa: F401  D3, D4 (owned by M2)


class Explainability(Base):
    """D5. Explainability (owned by M3 - Debanshu)"""
    __tablename__ = "explainability"

    explainability_id = Column(Integer, primary_key=True, autoincrement=True)
    prediction_id = Column(Integer, ForeignKey("predictions.prediction_id", ondelete="CASCADE"), nullable=False, index=True)
    branch = Column(String(12), nullable=False)  # 'semantic', 'frequency'
    technique = Column(String(40), nullable=False)  # 'attention-rollout', 'grad-attribution'
    visualization_reference = Column(Text, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    prediction = relationship("Prediction", back_populates="explainabilities")

    __table_args__ = (
        UniqueConstraint("prediction_id", "branch", name="uq_prediction_branch"),
    )


class LogEntry(Base):
    """D6. Logs (owned by M3 - Debanshu)"""
    __tablename__ = "logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(24), nullable=False)  # 'authentication', 'prediction-request', 'administrative-action', 'error'
    event_detail = Column(Text, nullable=False)
    severity = Column(String(8), nullable=False)  # 'info', 'warning', 'error'
    request_id = Column(String(36), nullable=True)
    log_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # One-directional (was back_populates="logs"): User is M1's model and does
    # not declare the reverse side, and nothing reads it.
    user = relationship("User")

    __table_args__ = (
        Index("idx_logs_time", log_timestamp.desc()),
        Index("idx_logs_type_time", "event_type", log_timestamp.desc()),
        Index("idx_logs_sev_time", "severity", log_timestamp.desc()),
    )
