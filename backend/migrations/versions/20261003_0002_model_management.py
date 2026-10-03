"""Model management (Phase 4, F.19): provenance keys, activations, immutable D3.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03

- models.training_reference, models.registered_by.
- predictions.semantic_model_id / frequency_model_id as real foreign keys
  (ON DELETE RESTRICT), backfilled from the branch_model_ids JSON. With the
  existing predictions.model_id (fusion), every D3 row a prediction used is
  now undeletable.
- model_activations: who activated what, when, forced or not, with the
  quality-gate result - the audit trail and the basis of one-call rollback.
- D3 rows are immutable once inserted: a trigger rejects any UPDATE that
  changes anything but is_active (PostgreSQL and SQLite).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every D3 column except is_active.
_IMMUTABLE = ["model_name", "model_version", "model_type", "artifact_ref", "artifact_sha256",
              "hyperparameters", "metrics", "registered_at", "training_reference", "registered_by"]


def upgrade() -> None:
    op.create_table(
        "model_activations",
        sa.Column("activation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("previous_model_id", sa.Integer(), nullable=True),
        sa.Column("activated_by", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("forced", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("gate", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["activated_by"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_id"], ["models.model_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_model_id"], ["models.model_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("activation_id"),
    )
    op.create_index("idx_model_activations_type_time", "model_activations",
                    ["model_type", sa.literal_column("activated_at DESC")], unique=False)

    with op.batch_alter_table("models") as batch:
        batch.add_column(sa.Column("training_reference", sa.Text(), nullable=True))
        batch.add_column(sa.Column("registered_by", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_models_registered_by", "users", ["registered_by"], ["user_id"],
                                 ondelete="SET NULL")

    with op.batch_alter_table("predictions") as batch:
        batch.add_column(sa.Column("semantic_model_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("frequency_model_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_predictions_semantic_model", "models", ["semantic_model_id"],
                                 ["model_id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_predictions_frequency_model", "models", ["frequency_model_id"],
                                 ["model_id"], ondelete="RESTRICT")

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("""
            UPDATE predictions SET
              semantic_model_id = NULLIF(branch_model_ids->>'semantic', '')::int,
              frequency_model_id = CASE WHEN frequency_score IS NULL THEN NULL
                                        ELSE NULLIF(branch_model_ids->>'frequency', '')::int END
            WHERE branch_model_ids IS NOT NULL
        """)
        changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" if c not in ("hyperparameters", "metrics")
                              else f"NEW.{c}::text IS DISTINCT FROM OLD.{c}::text" for c in _IMMUTABLE)
        op.execute(f"""
            CREATE OR REPLACE FUNCTION models_immutable() RETURNS trigger AS $$
            BEGIN
              IF {changed} THEN
                RAISE EXCEPTION 'models rows are immutable: only is_active may change (model_id %)', OLD.model_id;
              END IF;
              RETURN NEW;
            END $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_models_immutable BEFORE UPDATE ON models "
                   "FOR EACH ROW EXECUTE FUNCTION models_immutable()")
    else:
        op.execute("""
            UPDATE predictions SET
              semantic_model_id = CAST(json_extract(branch_model_ids, '$.semantic') AS INTEGER),
              frequency_model_id = CASE WHEN frequency_score IS NULL THEN NULL
                                        ELSE CAST(json_extract(branch_model_ids, '$.frequency') AS INTEGER) END
            WHERE branch_model_ids IS NOT NULL
        """)
        changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in _IMMUTABLE)
        op.execute(f"""
            CREATE TRIGGER trg_models_immutable BEFORE UPDATE ON models
            WHEN {changed}
            BEGIN SELECT RAISE(ABORT, 'models rows are immutable: only is_active may change'); END
        """)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.execute("DROP TRIGGER IF EXISTS trg_models_immutable" + (" ON models" if dialect == "postgresql" else ""))
    if dialect == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS models_immutable()")
    with op.batch_alter_table("predictions") as batch:
        batch.drop_constraint("fk_predictions_frequency_model", type_="foreignkey")
        batch.drop_constraint("fk_predictions_semantic_model", type_="foreignkey")
        batch.drop_column("frequency_model_id")
        batch.drop_column("semantic_model_id")
    with op.batch_alter_table("models") as batch:
        batch.drop_constraint("fk_models_registered_by", type_="foreignkey")
        batch.drop_column("registered_by")
        batch.drop_column("training_reference")
    op.drop_index("idx_model_activations_type_time", table_name="model_activations")
    op.drop_table("model_activations")
