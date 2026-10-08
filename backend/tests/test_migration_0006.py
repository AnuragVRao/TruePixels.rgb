"""Migration 0006: p_ai / certainty / calibration_ref - expand step of C2 v2.

Seeded at 0005 (raw SQL: the ORM model already has the new columns), then
upgraded, so the backfill runs exactly as it would on a real database. Runs on
SQLite by default and on PostgreSQL with TEST_DATABASE_URL.
"""

from __future__ import annotations

import importlib.util
import itertools
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.m1_access.models import Image, User
from app.m2_analysis import calibration, registry
from app.m2_analysis.models import ModelRegistry
from app.shared import config, db

MIGRATION = Path(db.BACKEND_DIR) / "migrations" / "versions" / "20261008_0006_p_ai_certainty.py"
_spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION)
m0006 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m0006)

_n = itertools.count()
NEW = ("p_ai", "certainty", "calibration_ref")


def _alembic(target: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(db.BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        (command.downgrade if target != "head" else command.upgrade)(cfg, target)


def _columns() -> set[str]:
    return {c["name"] for c in inspect(db.engine).get_columns("predictions")}


def _fitted_set():
    base = registry.baseline()
    return replace(base,
                   primary=replace(base.primary, artifact_sha256=config.CALIBRATION_FIT_SEMANTIC_SHA256),
                   frequency_detector=replace(base.frequency_detector,
                                              artifact_sha256=config.CALIBRATION_FIT_FREQUENCY_SHA256))


# --------------------------------------------------------------------------
# The inlined map is the app's map
# --------------------------------------------------------------------------

@pytest.mark.parametrize("semantic_only", [False, True])
def test_the_inlined_map_equals_calibration_p_ai(semantic_only):
    """The migration freezes the 2026-10-08 constants. If the map is ever refit,
    config changes and a NEW migration recomputes - this one must not change,
    and this test then documents which fit it froze."""
    for i in range(0, 1001):
        s = i / 1000
        assert m0006.p_ai(s, semantic_only) == calibration.p_ai(s, semantic_only=semantic_only)
    assert (m0006.FUSED_A, m0006.FUSED_B, m0006.FUSED_REF) == (
        config.CALIBRATION_FUSED_A, config.CALIBRATION_FUSED_B, config.CALIBRATION_FUSED_REF)
    assert (m0006.SEM_A, m0006.SEM_B, m0006.SEM_REF) == (
        config.CALIBRATION_SEMANTIC_ONLY_A, config.CALIBRATION_SEMANTIC_ONLY_B,
        config.CALIBRATION_SEMANTIC_ONLY_REF)


# --------------------------------------------------------------------------
# Backfill, seeded at 0005
# --------------------------------------------------------------------------

def _model(s, model_type, sha, hyper):
    row = ModelRegistry(model_name=f"mig0006-{model_type}-{next(_n)}", model_version="t", model_type=model_type,
                        artifact_ref="test", artifact_sha256=sha, is_active=False, hyperparameters=hyper)
    s.add(row)
    s.flush()
    return row.model_id


def _fusion_hyper(w):
    return {"strategy": "weighted_average", "weight_semantic": w, "weight_frequency": 1 - w,
            "tau": 0.7558, "temperature": 1.0}


FREQ_OK = {"weights_digest": config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST, "ai_is_positive": True,
           "resize_to": None, "head": None}


@pytest.fixture
def seeded_at_0005():
    """Downgrade to 0005, insert the cases, upgrade to head; yield {case: row}."""
    _alembic("0005")
    assert not set(NEW) & _columns()
    s = db.SessionLocal()
    try:
        user = User(full_name="Mig6", email=f"mig-0006-{next(_n)}@example.com", password_hash="x",
                    role="User", account_status="active", is_email_verified=True)
        s.add(user)
        s.flush()
        image = Image(user_id=user.user_id, file_reference="uploads/m6.png", content_sha256="6" * 64,
                      file_format="PNG", file_size=1, width=64, height=64, validation_status="valid")
        s.add(image)
        s.flush()
        sem_ok = _model(s, "semantic-classifier", config.CALIBRATION_FIT_SEMANTIC_SHA256, {"head": None})
        sem_other = _model(s, "semantic-classifier", "f" * 64, {"head": {"file": "x"}})
        freq_ok = _model(s, "frequency-artifact-classifier", config.CALIBRATION_FIT_FREQUENCY_SHA256, FREQ_OK)
        freq_other = _model(s, "frequency-artifact-classifier", "e" * 64, FREQ_OK)
        freq_neg = _model(s, "frequency-artifact-classifier", config.CALIBRATION_FIT_FREQUENCY_SHA256,
                          {**FREQ_OK, "ai_is_positive": False})
        fus_25 = _model(s, "fusion-configuration", "a" * 64, _fusion_hyper(0.25))
        fus_50 = _model(s, "fusion-configuration", "b" * 64, _fusion_hyper(0.5))
        s.commit()
        image_id = image.image_id
    finally:
        s.close()

    def fused(sv, fv, w):
        return w * sv + (1 - w) * fv

    cases = {
        # name: (fusion_model, semantic_model, frequency_model, semantic, frequency, fusion_score)
        "match": (fus_25, sem_ok, freq_ok, 0.6, 0.9, fused(0.6, 0.9, 0.25)),
        "match_confident": (fus_25, sem_ok, freq_ok, 0.99, 0.99999, fused(0.99, 0.99999, 0.25)),
        "match_low": (fus_25, sem_ok, freq_ok, 0.01, 1e-5, fused(0.01, 1e-5, 0.25)),
        "weight_mismatch": (fus_50, sem_ok, freq_ok, 0.6, 0.9, fused(0.6, 0.9, 0.5)),
        "semantic_hash_mismatch": (fus_25, sem_other, freq_ok, 0.6, 0.9, fused(0.6, 0.9, 0.25)),
        "frequency_hash_mismatch": (fus_25, sem_ok, freq_other, 0.6, 0.9, fused(0.6, 0.9, 0.25)),
        "sign_mismatch": (fus_25, sem_ok, freq_neg, 0.6, 0.9, fused(0.6, 0.9, 0.25)),
        "semantic_only": (fus_50, sem_ok, None, 0.97, None, 0.97),
        "semantic_only_other_hash": (fus_25, sem_other, None, 0.97, None, 0.97),
        "recompute_fails": (fus_25, sem_ok, freq_ok, 0.6, 0.9, fused(0.6, 0.9, 0.25) + 0.01),
        "no_linked_rows": (fus_25, None, None, 0.6, None, 0.6),
    }
    ids = {}
    with db.engine.begin() as c:
        for name, (fus, sem, freq, sv, fv, fs) in cases.items():
            pred = "AI Generated" if fs >= 0.7558 else "Real"
            c.execute(text(
                "INSERT INTO predictions (image_id, model_id, semantic_model_id, frequency_model_id, "
                "predicted_class, confidence_score, semantic_score, frequency_score, fusion_score, "
                "latency_ms, prediction_timestamp) VALUES (:i, :m, :sm, :fm, :pc, 0.5, :s, :f, :fs, 1, "
                "CURRENT_TIMESTAMP)"),
                {"i": image_id, "m": fus, "sm": sem, "fm": freq, "pc": pred, "s": sv, "f": fv, "fs": fs})
            ids[name] = c.execute(text("SELECT MAX(prediction_id) FROM predictions")).scalar()
    _alembic("head")
    with db.engine.connect() as c:
        rows = {r.prediction_id: r for r in c.execute(text(
            "SELECT prediction_id, p_ai, certainty, calibration_ref, confidence_score, fusion_score "
            "FROM predictions")).fetchall()}
    yield {name: rows[pid] for name, pid in ids.items()}


def test_matching_rows_get_exactly_what_calibration_calibrated_returns(seeded_at_0005):
    fitted = _fitted_set()
    for name in ("match", "match_confident", "match_low"):
        row = seeded_at_0005[name]
        expected = calibration.calibrated(fitted, row.fusion_score, semantic_only=False)
        assert expected.p_ai is not None
        assert (row.p_ai, row.certainty, row.calibration_ref) == (expected.p_ai, expected.certainty, expected.ref), name
    assert seeded_at_0005["match_confident"].certainty == "confident"
    assert seeded_at_0005["match_low"].certainty == "confident"
    assert seeded_at_0005["match"].certainty == "inconclusive"


@pytest.mark.parametrize("name", ["weight_mismatch", "semantic_hash_mismatch", "frequency_hash_mismatch",
                                  "sign_mismatch", "semantic_only_other_hash", "recompute_fails",
                                  "no_linked_rows"])
def test_rows_without_matching_provenance_or_failing_the_recompute_stay_null(seeded_at_0005, name):
    row = seeded_at_0005[name]
    assert (row.p_ai, row.certainty, row.calibration_ref) == (None, None, None)
    assert row.confidence_score == 0.5  # the legacy column is untouched


def test_semantic_only_row_checks_the_semantic_hash_only_and_is_inconclusive(seeded_at_0005):
    """Its fusion row has w = 0.5 - irrelevant to a semantic-only map."""
    row = seeded_at_0005["semantic_only"]
    expected = calibration.calibrated(_fitted_set(), row.fusion_score, semantic_only=True)
    assert (row.p_ai, row.certainty, row.calibration_ref) == (expected.p_ai, "inconclusive",
                                                              config.CALIBRATION_SEMANTIC_ONLY_REF)


# --------------------------------------------------------------------------
# Constraints at head
# --------------------------------------------------------------------------

@pytest.fixture
def prediction_id():
    s = db.SessionLocal()
    try:
        user = User(full_name="C", email=f"chk-0006-{next(_n)}@example.com", password_hash="x", role="User",
                    account_status="active", is_email_verified=True)
        s.add(user)
        s.flush()
        image = Image(user_id=user.user_id, file_reference="uploads/c.png", content_sha256="7" * 64,
                      file_format="PNG", file_size=1, width=64, height=64, validation_status="valid")
        s.add(image)
        s.flush()
        fus = _model(s, "fusion-configuration", "c" * 64, _fusion_hyper(0.25))
        s.commit()
        image_id = image.image_id
    finally:
        s.close()
    with db.engine.begin() as c:
        c.execute(text("INSERT INTO predictions (image_id, model_id, predicted_class, confidence_score, "
                       "semantic_score, fusion_score, prediction_timestamp) "
                       "VALUES (:i, :m, 'Real', 0.6, 0.3, 0.3, CURRENT_TIMESTAMP)"), {"i": image_id, "m": fus})
        return c.execute(text("SELECT MAX(prediction_id) FROM predictions")).scalar()


@pytest.mark.parametrize("values", [
    {"p_ai": 0.5, "certainty": "inconclusive", "calibration_ref": "r"},
    {"p_ai": 0.01, "certainty": "confident", "calibration_ref": "r"},
    {"p_ai": 0.99, "certainty": "confident", "calibration_ref": "r"},
    {"p_ai": None, "certainty": None, "calibration_ref": None},
])
def test_constraints_accept_consistent_rows(prediction_id, values):
    with db.engine.begin() as c:
        c.execute(text("UPDATE predictions SET p_ai = :p_ai, certainty = :certainty, "
                       "calibration_ref = :calibration_ref WHERE prediction_id = :i"), {**values, "i": prediction_id})


@pytest.mark.parametrize("values", [
    {"p_ai": 0.995, "certainty": "confident", "calibration_ref": "r"},   # above the cap
    {"p_ai": 0.005, "certainty": "confident", "calibration_ref": "r"},   # below the cap
    {"p_ai": 0.5, "certainty": "maybe", "calibration_ref": "r"},         # unknown label
    {"p_ai": 0.5, "certainty": None, "calibration_ref": "r"},            # certainty NULL, p_ai not
    {"p_ai": None, "certainty": "inconclusive", "calibration_ref": None},  # certainty without p_ai
    {"p_ai": 0.5, "certainty": "inconclusive", "calibration_ref": None},   # ref NULL, p_ai not
    {"p_ai": None, "certainty": None, "calibration_ref": "r"},             # ref without p_ai
])
def test_constraints_refuse_inconsistent_rows(prediction_id, values):
    with pytest.raises(IntegrityError):
        with db.engine.begin() as c:
            c.execute(text("UPDATE predictions SET p_ai = :p_ai, certainty = :certainty, "
                           "calibration_ref = :calibration_ref WHERE prediction_id = :i"),
                      {**values, "i": prediction_id})


# --------------------------------------------------------------------------
# Downgrade
# --------------------------------------------------------------------------

def test_downgrade_drops_only_the_three_new_columns(prediction_id):
    before = _columns()
    assert set(NEW) <= before
    _alembic("0005")
    try:
        after = _columns()
        assert after == before - set(NEW)
        assert "confidence_score" in after
        with db.engine.connect() as c:
            row = c.execute(text("SELECT confidence_score, fusion_score FROM predictions "
                                 "WHERE prediction_id = :i"), {"i": prediction_id}).one()
        assert (row.confidence_score, row.fusion_score) == (0.6, 0.3)
    finally:
        _alembic("head")
    assert _columns() == before
