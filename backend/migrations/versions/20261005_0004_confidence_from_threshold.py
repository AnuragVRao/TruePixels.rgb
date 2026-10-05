"""Recompute stored confidence_score from the decision threshold (changes.md 6.21).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05

confidence_score is confidence in the PREDICTED class. It used to be
``fusion`` / ``1 - fusion``, which assumes tau = 0.5: at the operating point
tau = 0.7558 a "Real" verdict could carry a confidence below 0.5. It is now
measured from tau (app/m2_analysis/fusion.py, confidence_in_prediction):

    AI Generated:  0.5 + 0.5 * (fusion - tau) / (1 - tau)
    Real:          0.5 + 0.5 * (tau - fusion) / tau

Every stored D4 row is recomputed from its own fusion_score, its own
predicted_class and the tau of the fusion configuration that produced it
(predictions.model_id -> models.hyperparameters). The class and every score
are untouched. Rows whose configuration has no tau are left as they are.
The formula is inlined here so the migration never changes with app code.
Downgrade restores the original rule exactly.
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rows(conn):
    return conn.execute(sa.text(
        "SELECT p.prediction_id, p.fusion_score, p.predicted_class, m.hyperparameters "
        "FROM predictions p JOIN models m ON m.model_id = p.model_id")).fetchall()


def _tau(hyper):
    if isinstance(hyper, str):
        hyper = json.loads(hyper)
    tau = (hyper or {}).get("tau")
    return float(tau) if tau is not None and 0.0 < float(tau) < 1.0 else None


def upgrade() -> None:
    conn = op.get_bind()
    for prediction_id, fusion, predicted, hyper in _rows(conn):
        tau = _tau(hyper)
        if tau is None or fusion is None:
            continue
        if predicted == "AI Generated":
            margin = (fusion - tau) / (1.0 - tau)
        else:
            margin = (tau - fusion) / tau
        confidence = min(1.0, max(0.5, 0.5 + 0.5 * margin))
        conn.execute(sa.text("UPDATE predictions SET confidence_score = :c WHERE prediction_id = :i"),
                     {"c": confidence, "i": prediction_id})


def downgrade() -> None:
    conn = op.get_bind()
    for prediction_id, fusion, predicted, hyper in _rows(conn):
        if _tau(hyper) is None or fusion is None:
            continue
        confidence = fusion if predicted == "AI Generated" else 1.0 - fusion
        conn.execute(sa.text("UPDATE predictions SET confidence_score = :c WHERE prediction_id = :i"),
                     {"c": confidence, "i": prediction_id})
