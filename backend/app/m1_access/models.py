"""SQLAlchemy models for D1.Users and D2.Images.

Conforms to PRD Section 6.2 and Module Interface Contract Section 2.2 / 9.1.
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
    Boolean,
    func,
)
from sqlalchemy.orm import relationship
from app.shared.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    """Data Store D1: Users."""
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    full_name = Column(String(120), nullable=False)
    # Unique case-insensitively: see uq_users_email_lower below. (Was
    # unique=True on the raw column, which "A@x" and "a@x" both satisfied.)
    email = Column(String(255), nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(10), nullable=False, default="User")
    account_status = Column(String(10), nullable=False, default="active")
    registered_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # 2FA / OTP Enhancement fields
    otp_hash = Column(String(255), nullable=True)
    otp_expires_at = Column(DateTime(timezone=True), nullable=True)
    # INTEGRATION (Phase 6-pre, changes.md 6.15): what the pending code may be
    # redeemed for - 'login' (issued after a correct password) or 'register'
    # (issued by registration). NULL = no redeemable challenge.
    otp_purpose = Column(String(16), nullable=True)
    is_email_verified = Column(Boolean, default=False, nullable=False)

    # Relationships
    images = relationship("Image", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("role IN ('User', 'Admin')", name="chk_user_role"),
        CheckConstraint("account_status IN ('active', 'disabled', 'removed')", name="chk_user_status"),
        CheckConstraint("otp_purpose IS NULL OR otp_purpose IN ('login', 'register')",
                        name="chk_user_otp_purpose"),
        # INTEGRATION (Phase 2): case-insensitive uniqueness, enforced by the
        # database. Lookups filter on func.lower(User.email), so this index is
        # also the one they use.
        Index("uq_users_email_lower", func.lower(email), unique=True),
    )

    def __repr__(self) -> str:
        return f"<User(user_id={self.user_id}, email='{self.email}', role='{self.role}', status='{self.account_status}')>"


class Image(Base):
    """Data Store D2: Images."""
    __tablename__ = "images"

    image_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False)
    file_reference = Column(Text, nullable=False)
    content_sha256 = Column(String(64), nullable=False)  # indexed by idx_images_sha below
    file_format = Column(String(5), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    upload_timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    validation_status = Column(String(10), nullable=False, default="pending")
    rejection_reason = Column(String(32), nullable=True)

    # Relationships
    user = relationship("User", back_populates="images")

    __table_args__ = (
        CheckConstraint("file_format IN ('JPG', 'JPEG', 'PNG')", name="chk_image_format"),
        CheckConstraint("validation_status IN ('pending', 'valid', 'invalid')", name="chk_validation_status"),
        CheckConstraint(
            "rejection_reason IS NULL OR rejection_reason IN ('unsupported-format', 'file-too-large', 'corrupted-file')",
            name="chk_rejection_reason",
        ),
        Index("idx_images_user_time", "user_id", "upload_timestamp"),
        Index("idx_images_sha", "content_sha256"),
    )

    def __repr__(self) -> str:
        return f"<Image(image_id={self.image_id}, sha='{self.content_sha256[:8]}...', status='{self.validation_status}')>"
