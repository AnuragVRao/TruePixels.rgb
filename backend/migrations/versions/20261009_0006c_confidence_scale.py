"""Recompute stored confidence_score with the 0.86 scale (2026-10-09).

Revision ID: 0006c
Revises: 0005
Create Date: 2026-10-09

The displayed confidence (confidence in the PREDICTED class, a margin from
tau) gains a scale of 0.86, so a verdict reads between 50 % and 93 % and never
100 % (app/m2_analysis/fusion.py, confidence_in_prediction):

    AI Generated:  0.5 + 0.5 * 0.86 * (fusion - tau) / (1 - tau)
    Real:          0.5 + 0.5 * 0.86 * (tau - fusion) / tau

Every stored D4 row is recomputed from its own fusion_score, its own
predicted_class and the tau of the fusion configuration that produced it
(predictions.model_id -> models.hyperparameters), exactly as 0004 did. The
class and every score are untouched. Rows whose configuration has no tau are
left as they are. The formula is inlined so the migration never changes with
app code. Downgrade restores 0004's unscaled rule exactly.

The id is "0006c", not "0006": branch decision-map-1 has a different 0006
(p_ai / certainty columns). A database migrated there must be downgraded to
0005 on that branch before it can follow this one.
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006c"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCALE = 0.86


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
    _recompute(SCALE)


def downgrade() -> None:
    _recompute(1.0)  # 0004's rule
