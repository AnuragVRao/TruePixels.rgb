"""D4 gains p_ai, certainty and calibration_ref (C2 v2, expand step).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08

EXPAND / CONTRACT. This migration only ADDS the three columns that Contract C2
v2 stores (app/shared/contracts/c2.py, revision 4) and backfills them. The
legacy ``confidence_score`` column stays, still NOT NULL and still written by
the pipeline (dual-write), until M3 and the UI read p_ai; a later migration
drops it.

    p_ai             P(AI) shown for EITHER verdict, in [0.01, 0.99], or NULL
    certainty        'confident' | 'inconclusive', NULL iff p_ai is NULL
    calibration_ref  which fitted map produced p_ai, NULL iff p_ai is NULL

BACKFILL. Every existing row is recomputed from its OWN stored scores and the
D3 rows it links to. The map's constants are INLINED below, exactly as fitted
on 2026-10-08 (ml/calibration/fit_calibration.py), so this migration never
changes with app code - the same convention as 0004. A row gets a p_ai only
when all of these hold; otherwise it stays NULL ("not calibrated"), never a
guess:

1. Self-check: the stored fusion_score must equal the recompute from the
   stored branch scores - w*semantic + (1-w)*frequency with w from the row's
   own fusion D3 row, or semantic alone when frequency_score is NULL - within
   1e-9. A row that fails was produced by something other than the plain
   weighted average (e.g. a temperature != 1), so the map does not apply.
2. Provenance, by the D3 rows' artifact_sha256 (never a "published" flag):
   fused rows need the semantic hash, the SPAI hash, w = 0.25 (+-1e-9), SPAI's
   sign convention ai_is_positive = true and resize_to = null; semantic-only
   rows need the semantic hash only. Rows without linked D3 rows (pre-Phase 4)
   have no provenance and stay NULL.

Semantic-only rows are always 'inconclusive' (the map's band edges lie outside
the validated semantic range 0.0032-0.9997).

SQLite: the columns are added with in-line CHECKs (ALTER TABLE ... ADD COLUMN,
no table rebuild - a rebuild would drop and recreate ``predictions`` under
foreign-key enforcement, which ``explainability`` references). PostgreSQL:
ADD COLUMN + named CHECK constraints. Downgrade drops exactly the three
columns, in dependency order.
"""
import json
import math
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---- the fitted map, frozen here (config.py CALIBRATION_* as of 2026-10-08) ----
EPS = 1e-6
P_MIN, P_MAX = 0.01, 0.99
BAND = 0.90
FUSED_A, FUSED_B, FUSED_REF = 0.9293583950623755, -0.22303485583043137, "platt-a26b43d86be6"
SEM_A, SEM_B, SEM_REF = 0.22919994124762147, 0.03200240755463338, "platt-23a4d25095bf"
FIT_WEIGHT = 0.25
FIT_SEMANTIC_SHA256 = "8560c44d0f9fbe9a939a3dbbff4c2d88047b073beeb1410e7afc2b567e6628f4"
FIT_FREQUENCY_SHA256 = "0151f7570b540c305fcbdae0221bccad9399998a6c3938c9c384c323e5dfb42e"
WEIGHT_TOLERANCE = 1e-9
RECOMPUTE_TOLERANCE = 1e-9

CHECK_P_AI = "p_ai IS NULL OR (p_ai >= 0.01 AND p_ai <= 0.99)"
CHECK_CERTAINTY = ("(certainty IS NULL) = (p_ai IS NULL) AND "
                   "(certainty IS NULL OR certainty IN ('confident', 'inconclusive'))")
CHECK_REF = "(calibration_ref IS NULL) = (p_ai IS NULL)"


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def p_ai(score: float, semantic_only: bool) -> float:
    """The frozen map: clip(sigmoid(a*logit(S) + b), 0.01, 0.99), prior 0.5."""
    a, b = (SEM_A, SEM_B) if semantic_only else (FUSED_A, FUSED_B)
    clamped = min(max(score, EPS), 1.0 - EPS)
    z = a * math.log(clamped / (1.0 - clamped)) + b
    return min(P_MAX, max(P_MIN, _sigmoid(z)))


def _hyper(value):
    if isinstance(value, str):
        value = json.loads(value)
    return value or {}


def backfill_values(row) -> tuple:
    """(p_ai, certainty, calibration_ref) for one prediction row, or (None, None, None).

    ``row`` has: fusion_score, semantic_score, frequency_score, fusion_hyper,
    semantic_sha, frequency_sha, frequency_hyper (None where no row is linked).
    """
    none = (None, None, None)
    semantic_only = row["frequency_score"] is None
    fusion_hyper = _hyper(row["fusion_hyper"])
    try:
        w = float(fusion_hyper["weight_semantic"])
    except (KeyError, TypeError, ValueError):
        return none
    if row["fusion_score"] is None or row["semantic_score"] is None:
        return none

    # 1. the stored fusion_score must be the plain weighted average of the stored branch scores
    expected = row["semantic_score"] if semantic_only else (
        w * row["semantic_score"] + (1.0 - w) * row["frequency_score"])
    if abs(expected - row["fusion_score"]) > RECOMPUTE_TOLERANCE:
        return none

    # 2. provenance by artifact hash
    if row["semantic_sha"] != FIT_SEMANTIC_SHA256:
        return none
    if not semantic_only:
        frequency_hyper = _hyper(row["frequency_hyper"])
        if (row["frequency_sha"] != FIT_FREQUENCY_SHA256
                or abs(w - FIT_WEIGHT) > WEIGHT_TOLERANCE
                or frequency_hyper.get("ai_is_positive") is not True
                or frequency_hyper.get("resize_to") is not None):
            return none

    p = p_ai(row["fusion_score"], semantic_only)
    if semantic_only:
        return p, "inconclusive", SEM_REF
    return p, ("confident" if p >= BAND or p <= 1.0 - BAND else "inconclusive"), FUSED_REF


def _rows(conn):
    return conn.execute(sa.text(
        "SELECT p.prediction_id, p.fusion_score, p.semantic_score, p.frequency_score, "
        "       f.hyperparameters AS fusion_hyper, s.artifact_sha256 AS semantic_sha, "
        "       q.artifact_sha256 AS frequency_sha, q.hyperparameters AS frequency_hyper "
        "FROM predictions p "
        "JOIN models f ON f.model_id = p.model_id "
        "LEFT JOIN models s ON s.model_id = p.semantic_model_id "
        "LEFT JOIN models q ON q.model_id = p.frequency_model_id")).mappings().fetchall()


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        # In-line CHECKs; order matters - certainty's and calibration_ref's
        # checks name p_ai, so p_ai must exist first.
        op.execute(f"ALTER TABLE predictions ADD COLUMN p_ai FLOAT "
                   f"CONSTRAINT chk_pred_p_ai_range CHECK ({CHECK_P_AI})")
        op.execute(f"ALTER TABLE predictions ADD COLUMN certainty VARCHAR(12) "
                   f"CONSTRAINT chk_pred_certainty CHECK ({CHECK_CERTAINTY})")
        op.execute(f"ALTER TABLE predictions ADD COLUMN calibration_ref VARCHAR(32) "
                   f"CONSTRAINT chk_pred_calibration_ref CHECK ({CHECK_REF})")
    else:
        op.add_column("predictions", sa.Column("p_ai", sa.Float(), nullable=True))
        op.add_column("predictions", sa.Column("certainty", sa.String(length=12), nullable=True))
        op.add_column("predictions", sa.Column("calibration_ref", sa.String(length=32), nullable=True))
        op.create_check_constraint("chk_pred_p_ai_range", "predictions", CHECK_P_AI)
        op.create_check_constraint("chk_pred_certainty", "predictions", CHECK_CERTAINTY)
        op.create_check_constraint("chk_pred_calibration_ref", "predictions", CHECK_REF)

    for row in _rows(conn):
        p, certainty, ref = backfill_values(row)
        if p is None:
            continue
        conn.execute(sa.text("UPDATE predictions SET p_ai = :p, certainty = :c, calibration_ref = :r "
                             "WHERE prediction_id = :i"),
                     {"p": p, "c": certainty, "r": ref, "i": row["prediction_id"]})


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        for name in ("chk_pred_calibration_ref", "chk_pred_certainty", "chk_pred_p_ai_range"):
            op.drop_constraint(name, "predictions", type_="check")
    # Dependency order: calibration_ref's and certainty's checks name p_ai.
    for column in ("calibration_ref", "certainty", "p_ai"):
        op.drop_column("predictions", column)
