"""Recompute stored confidence_score with the unscaled rule (2026-10-10).

Revision ID: 0007
Revises: 0006c
Create Date: 2026-10-10

The scale applied to the displayed confidence on 2026-10-09 (migration 0006c)
is removed; confidence is again the 2026-10-05 rule (0004), 0.5 at tau rising
to 1.0 at the far end of the predicted side:

    AI Generated:  0.5 + 0.5 * (fusion - tau) / (1 - tau)
    Real:          0.5 + 0.5 * (tau - fusion) / tau

Every stored D4 row is recomputed from its own fusion_score, predicted_class
and the tau of the fusion configuration that produced it, exactly as 0004 and
0006c did. Class and scores are untouched; rows whose configuration has no tau
are left as they are. Downgrade restores 0006c's scaled rule exactly. The
formula is inlined so the migration never changes with app code.
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREVIOUS_SCALE = 0.86  # what 0006c applied


def _rows(conn):
    return conn.execute(sa.text(
        "SELECT p.prediction_id, p.fusion_score, p.predicted_class, m.hyperparameters "
        "FROM predictions p JOIN models m ON m.model_id = p.model_id")).fetchall()


def _tau(hyper):
    if isinstance(hyper, str):
        hyper = json.loads(hyper)
    tau = (hyper or {}).get("tau")
    return float(tau) if tau is not None and 0.0 < float(tau) < 1.0 else None


def _recompute(scale: float) -> None:
    conn = op.get_bind()
    for prediction_id, fusion, predicted, hyper in _rows(conn):
        tau = _tau(hyper)
        if tau is None or fusion is None:
            continue
        if predicted == "AI Generated":
            margin = (fusion - tau) / (1.0 - tau)
        else:
            margin = (tau - fusion) / tau
        margin = min(1.0, max(0.0, margin))
        conn.execute(sa.text("UPDATE predictions SET confidence_score = :c WHERE prediction_id = :i"),
                     {"c": 0.5 + 0.5 * scale * margin, "i": prediction_id})


def upgrade() -> None:
    _recompute(1.0)


def downgrade() -> None:
    _recompute(PREVIOUS_SCALE)
