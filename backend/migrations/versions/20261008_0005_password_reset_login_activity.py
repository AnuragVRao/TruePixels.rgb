"""Password reset, session invalidation and login activity.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

* users.token_version: every session token carries it ("ver" claim); a
  password change or reset increments it, so every older token is refused.
* users.password_changed_at: when the password last changed (NULL = never).
* password_resets: at most one pending forgot-password code per user, stored
  only as an Argon2id hash. Kept apart from users.otp_* so a reset request
  never replaces a pending sign-in or registration code, and so a reset code
  can never be redeemed at /auth/otp/verify.
* login_events: one row per sign-in attempt and password change, with the
  client address and browser - read by the user (own rows) and admins (all).

SQLite: plain ADD/DROP COLUMN, never a batch rebuild of ``users`` (it would
lose the expression index uq_users_email_lower - see 0003).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PORTALS = "portal IN ('user', 'admin')"
OUTCOMES = ("outcome IN ('success', 'otp_sent', 'wrong_password', 'unknown_account', 'account_disabled', "
            "'not_admin', 'otp_failed', 'password_reset', 'password_changed')")


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "password_resets",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "login_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("portal", sa.String(length=8), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(PORTALS, name="chk_login_event_portal"),
        sa.CheckConstraint(OUTCOMES, name="chk_login_event_outcome"),
    )
    op.create_index("ix_login_events_user_created", "login_events", ["user_id", "created_at"])
    op.create_index("ix_login_events_created", "login_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_login_events_created", table_name="login_events")
    op.drop_index("ix_login_events_user_created", table_name="login_events")
    op.drop_table("login_events")
    op.drop_table("password_resets")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ALTER TABLE users DROP COLUMN password_changed_at")
        op.execute("ALTER TABLE users DROP COLUMN token_version")
    else:
        op.drop_column("users", "password_changed_at")
        op.drop_column("users", "token_version")
