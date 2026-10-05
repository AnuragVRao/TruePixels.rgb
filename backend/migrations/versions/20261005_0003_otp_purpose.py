"""OTP challenges carry a purpose (Phase 6-pre, changes.md 6.15).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05

users.otp_purpose: 'login' (created only after a correct password) or
'register' (created only by registration, role User). A code is redeemable
only for the purpose it was issued for. Challenges pending at upgrade time
have no purpose and are therefore refused - their owners request a new one
by signing in again.

SQLite: plain ALTER TABLE ADD/DROP COLUMN, deliberately NOT batch mode - a
batch rebuild of ``users`` silently loses the expression index
uq_users_email_lower (SQLAlchemy cannot reflect it).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK = "otp_purpose IS NULL OR otp_purpose IN ('login', 'register')"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ALTER TABLE users ADD COLUMN otp_purpose VARCHAR(16) "
                   f"CONSTRAINT chk_user_otp_purpose CHECK ({CHECK})")
    else:
        op.add_column("users", sa.Column("otp_purpose", sa.String(length=16), nullable=True))
        op.create_check_constraint("chk_user_otp_purpose", "users", CHECK)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ALTER TABLE users DROP COLUMN otp_purpose")
    else:
        op.drop_constraint("chk_user_otp_purpose", "users", type_="check")
        op.drop_column("users", "otp_purpose")
