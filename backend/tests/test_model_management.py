"""F.19 model management end to end (Phase 4). Real models; slow.

Needs the gate's reference cache (backend/scripts/build_reference_set.py).
Head uploads are validated ONLY with perturbed copies of the published heads -
this project never trains (CLAUDE.md section 0); fusion-configuration swapping
is the end-to-end demonstrated feature.
"""

from __future__ import annotations

import io
import itertools
import json
import subprocess
import sys
import threading

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient
from PIL import Image
from safetensors.torch import save as save_safetensors
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.m1_access.models import User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis import detectors, frequency_detector, gate, heads, registry
from app.m2_analysis.models import ModelActivation, ModelRegistry, Prediction
from app.m3_results.models import LogEntry
from app.main import app
from app.shared import config
from app.shared.db import SessionLocal, engine
from conftest import make_image, png_bytes

pytestmark = pytest.mark.slow
client = TestClient(app)
_n = itertools.count()
REPO = config.REPO_ROOT


@pytest.fixture(autouse=True)
def _requirements():
    if not frequency_detector.frequency.present_on_disk:
        pytest.skip("SPAI weights not present; see CLAUDE.md section 4")
    if gate.load_reference() is None:
        pytest.skip(f"gate reference cache missing: run backend/scripts/build_reference_set.py")
    heads.clear()
    yield
    heads.clear()


def _user(role: str = "User") -> tuple[int, dict[str, str]]:
    db = SessionLocal()
    try:
        user = User(full_name=role, email=f"mm-{next(_n)}@example.com",
                    password_hash=hash_password("ModelMgmt12345"), role=role,
                    account_status="active", is_email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.user_id, {"Authorization": f"Bearer {create_session_token(user)[0]}"}
    finally:
        db.close()


def _active_id(model_type: str) -> int:
    db = SessionLocal()
    try:
        registry.active(db)
        return db.query(ModelRegistry).filter(ModelRegistry.model_type == model_type,
                                              ModelRegistry.is_active.is_(True)).one().model_id
    finally:
        db.close()


def _register(admin, model_type, name, version, data: bytes, **form):
    files = {"file": ("artefact", data, "application/octet-stream")}
    fields = {"model_type": model_type, "name": name, "version": version,
              "training_reference": form.pop("training_reference", "test artefact"), **form}
    return client.post("/api/v1/models", headers=admin, data=fields, files=files)


def _fusion(tau: float, w: float = config.FUSION_WEIGHT, t: float = 1.0) -> bytes:
    return json.dumps({"strategy": "weighted_average", "weight_semantic": w, "tau": tau,
                       "temperature": t}).encode()


def _activate(admin, model_id, **body):
    return client.post(f"/api/v1/models/{model_id}/activate", headers=admin, json=body)


def _flip_image() -> bytes:
    """A validation-split image whose fused score lies between tau 0.60 and the
    baseline tau, so moving tau to 0.60 must change its label."""
    ref = gate.load_reference()
    names = [item[0] for item in json.loads(gate.reference_path().with_suffix(".json").read_text())["images"]]
    fused = config.FUSION_WEIGHT * ref["semantic_scores"] + (1 - config.FUSION_WEIGHT) * ref["frequency_scores"]
    candidates = [i for i, f in enumerate(fused) if 0.62 <= f < config.FUSION_TAU - 0.01]
    assert candidates, "no reference image between the two thresholds"
    with Image.open(REPO / names[candidates[0]]) as handle:
        buffer = io.BytesIO()
        handle.convert("RGB").save(buffer, format="PNG")  # lossless; M1 accepts PNG/JPEG only
    return buffer.getvalue()


def _predict(headers, payload: bytes) -> dict:
    image = client.post("/api/v1/images", headers=headers, files={"file": ("x.png", payload, "image/png")})
    assert image.status_code == 201, image.text
    r = client.post("/api/v1/predictions", headers=headers, json={"image_id": image.json()["image_id"]})
    assert r.status_code == 201, r.text
    return r.json()


def _prediction_row(prediction_id: int) -> Prediction:
    db = SessionLocal()
    try:
        return db.get(Prediction, prediction_id)
    finally:
        db.close()


# --------------------------------------------------------------------------
# Bootstrap, pinning, offline load
# --------------------------------------------------------------------------

def test_empty_d3_bootstraps_the_pinned_baseline():
    db = SessionLocal()
    try:
        models = registry.active(db)
        rows = {r.model_type: r for r in db.query(ModelRegistry).filter(ModelRegistry.is_active.is_(True))}
        boots = db.query(ModelActivation).filter(ModelActivation.action == "bootstrap").count()
    finally:
        db.close()
    sem = rows[registry.TYPE_SEMANTIC]
    assert sem.hyperparameters["revision"] == config.DETECTOR_PRIMARY_REVISION
    assert sem.model_version == f"rev-{config.DETECTOR_PRIMARY_REVISION[:12]}" and sem.artifact_sha256
    assert rows[registry.TYPE_FREQUENCY].artifact_sha256 == config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST
    assert models.fusion.tau == config.FUSION_TAU and boots == 3
    assert all(r.training_reference for r in rows.values())


def test_pinned_revision_loads_with_the_network_switched_off():
    code = ("import sys; sys.path.insert(0, 'backend'); "
            "from app.m2_analysis import detectors; detectors.primary.load(); "
            "print('ai_index', detectors.primary.ai_index)")
    env = {**__import__("os").environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "ai_index 1" in done.stdout


# --------------------------------------------------------------------------
# Fusion swap: the end-to-end demonstrated feature
# --------------------------------------------------------------------------

def test_moderate_fusion_change_passes_the_gate_and_changes_what_runs():
    _, admin = _user("Admin")
    _, user = _user()
    payload = _flip_image()
    before = _predict(user, payload)
    baseline_fusion = _active_id(registry.TYPE_FUSION)
    assert before["model_id"] == baseline_fusion and before["predicted_class"] == "Real"

    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "tau0.60", _fusion(0.60),
                    training_reference="test: tau 0.60 on the same branch models; evaluated on the "
                                       "sbr_val gate reference only")
    assert reg.status_code == 201, reg.text
    act = _activate(admin, reg.json()["model_id"])
    assert act.status_code == 200, act.text
    g = act.json()["gate"]
    assert g["passed"] and g["available"] and g["labels_changed"] > 0, g
    assert g["candidate"]["fpr"] <= gate.MAX_FPR

    after = _predict(user, payload)
    assert after["model_id"] == reg.json()["model_id"] != before["model_id"]
    assert after["fusion_score"] == before["fusion_score"]  # same branches, same fused score
    assert after["predicted_class"] == "AI Generated"       # different threshold, different label
    assert _prediction_row(after["prediction_id"]).model_id == reg.json()["model_id"]


def test_extreme_fusion_change_is_refused_by_the_gate():
    admin_id, admin = _user("Admin")
    baseline_fusion = _active_id(registry.TYPE_FUSION)
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "tau0.05", _fusion(0.05))
    assert reg.status_code == 201
    act = _activate(admin, reg.json()["model_id"])
    assert act.status_code == 409 and act.json()["error"]["code"] == "MDL_GATE_REFUSED"
    assert any("false-positive rate" in r for r in act.json()["gate"]["reasons"])
    assert _active_id(registry.TYPE_FUSION) == baseline_fusion  # nothing changed

    no_reason = _activate(admin, reg.json()["model_id"], force=True)
    assert no_reason.status_code == 422 and no_reason.json()["error"]["code"] == "MDL_FORCE_NEEDS_REASON"

    forced = _activate(admin, reg.json()["model_id"], force=True, reason="test: deliberate override")
    assert forced.status_code == 200 and forced.json()["forced"] is True
    db = SessionLocal()
    try:
        record = db.query(ModelActivation).order_by(ModelActivation.activation_id.desc()).first()
        logs = [l.event_detail for l in db.query(LogEntry).filter(LogEntry.user_id == admin_id)]
    finally:
        db.close()
    assert record.forced and record.reason == "test: deliberate override" and record.gate["passed"] is False
    assert any("FORCED" in l for l in logs) and any("refused (MDL_GATE_REFUSED)" in l for l in logs)


def test_rollback_restores_the_previous_model_in_one_call():
    _, admin = _user("Admin")
    baseline_fusion = _active_id(registry.TYPE_FUSION)
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "tau0.65", _fusion(0.65))
    assert _activate(admin, reg.json()["model_id"]).status_code == 200
    assert _active_id(registry.TYPE_FUSION) == reg.json()["model_id"]
    rb = client.post("/api/v1/models/rollback", headers=admin, json={"model_type": registry.TYPE_FUSION})
    assert rb.status_code == 200, rb.text
    assert rb.json()["action"] == "rollback" and _active_id(registry.TYPE_FUSION) == baseline_fusion
    # The gate is advisory for a rollback: recorded, not enforced. (Here the
    # baseline scores LOWER than tau 0.65 on the reference sample, which a
    # blocking gate would have refused - the case that motivated this rule.)
    assert rb.json()["gate"]["advisory"] is True and rb.json()["forced"] is False


def test_m3_admin_activate_now_delegates_to_the_registry():
    _, admin = _user("Admin")
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "tau0.05-m3", _fusion(0.05))
    r = client.post(f"/api/v1/admin/models/{reg.json()['model_id']}/activate", headers=admin)
    assert r.status_code == 409 and r.json()["error"]["code"] == "MDL_GATE_REFUSED"


# --------------------------------------------------------------------------
# Heads: perturbed copies of the published heads only (no training)
# --------------------------------------------------------------------------

def _perturbed(state: dict, prefix: str, scale: float = 1e-3) -> bytes:
    generator = torch.Generator().manual_seed(0)
    return save_safetensors({prefix + k: (v.float().cpu() + scale * torch.randn(v.shape, generator=generator))
                             .contiguous() for k, v in state.items()})


def test_perturbed_semantic_head_registers_activates_and_is_used():
    _, admin = _user("Admin")
    _, user = _user()
    data = _perturbed(detectors.primary.classifier_state(), heads.SEMANTIC_PREFIX)
    reg = _register(admin, registry.TYPE_SEMANTIC, config.DETECTOR_PRIMARY, "test-perturbed-head",
                    data, id2label=json.dumps({"0": "Real", "1": "AI"}))
    assert reg.status_code == 201, reg.text
    sha = reg.json()["artifact_sha256"]
    assert (config.MODELS_DIR / "uploads" / f"{sha}.safetensors").is_file()
    before = _predict(user, png_bytes(make_image(seed=41)))
    act = _activate(admin, reg.json()["model_id"])
    assert act.status_code == 200, act.text
    after = _predict(user, png_bytes(make_image(seed=41)))
    row = _prediction_row(after["prediction_id"])
    assert row.semantic_model_id == reg.json()["model_id"]
    assert after["semantic_score"] != before["semantic_score"]           # the uploaded head ran
    assert after["semantic_score"] == pytest.approx(before["semantic_score"], abs=0.05)  # ...a tiny perturbation
    # Cached by row id, the same immutable object every time.
    spec = _head_spec(reg.json()["model_id"])
    cached = heads.semantic_head(reg.json()["model_id"], spec)
    assert cached is heads.semantic_head(reg.json()["model_id"], spec)
    assert not any(p.requires_grad for p in cached.module.parameters())


def _head_spec(model_id: int) -> dict:
    db = SessionLocal()
    try:
        return db.get(ModelRegistry, model_id).hyperparameters["head"]
    finally:
        db.close()


def test_perturbed_spai_head_registers_and_passes_the_canary():
    _, admin = _user("Admin")
    data = _perturbed(frequency_detector.frequency.cls_head_state(), heads.FREQUENCY_PREFIX)
    reg = _register(admin, registry.TYPE_FREQUENCY, "SPAI", "test-perturbed-head", data, ai_is_positive="true")
    assert reg.status_code == 201, reg.text
    db = SessionLocal()
    try:
        row = db.get(ModelRegistry, reg.json()["model_id"])
        result = registry.canary(row)
    finally:
        db.close()
    assert result["ok"] and 0.0 <= result["score"] <= 1.0


# --------------------------------------------------------------------------
# Refused artefacts and access
# --------------------------------------------------------------------------

def test_bad_artefacts_are_refused_and_nothing_is_registered():
    _, admin = _user("Admin")
    state = detectors.primary.classifier_state()
    pickle_bytes = io.BytesIO()
    torch.save({k: v.cpu() for k, v in state.items()}, pickle_bytes)
    wrong_shape = save_safetensors({"classifier.weight": torch.zeros(3, 768), "classifier.bias": torch.zeros(3)})
    nan = save_safetensors({"classifier.weight": torch.full((2, 768), float("nan")),
                            "classifier.bias": torch.zeros(2)})
    extra = save_safetensors({**{"classifier." + k: v.cpu().contiguous() for k, v in state.items()},
                              "evil": torch.zeros(1)})
    label = json.dumps({"0": "Real", "1": "AI"})
    cases = [
        (registry.TYPE_SEMANTIC, pickle_bytes.getvalue(), {"id2label": label}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_SEMANTIC, wrong_shape, {"id2label": label}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_SEMANTIC, nan, {"id2label": label}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_SEMANTIC, extra, {"id2label": label}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_SEMANTIC, _perturbed(state, heads.SEMANTIC_PREFIX),
         {"id2label": json.dumps({"0": "cat", "1": "dog"})}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_SEMANTIC, b"\0" * (2 * 1024 * 1024), {"id2label": label}, "MDL_TOO_LARGE"),
        (registry.TYPE_FUSION, b'{"strategy": "weighted_average", "weight_semantic": NaN, "tau": 0.5, '
                               b'"temperature": 1}', {}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_FUSION, b'{"strategy": "weighted_average", "weight_semantic": 0.5, "tau": 0.5, '
                               b'"temperature": 1, "exec": "import os"}', {}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_FUSION, b'{"strategy": "logistic", "weight_semantic": 0.5, "tau": 0.5, '
                               b'"temperature": 1}', {}, "MDL_INVALID_ARTIFACT"),
        (registry.TYPE_FUSION, b" " * (17 * 1024), {}, "MDL_TOO_LARGE"),
    ]
    db = SessionLocal()
    before = db.query(ModelRegistry).count()
    db.close()
    for n, (model_type, data, form, code) in enumerate(cases):
        r = _register(admin, model_type, "bad", f"bad-{n}", data, **form)
        assert r.status_code in (413, 422) and r.json()["error"]["code"] == code, (n, r.text)
    db = SessionLocal()
    try:
        assert db.query(ModelRegistry).count() == before
    finally:
        db.close()


def test_only_admins_reach_model_management():
    _, user = _user()
    assert client.get("/api/v1/models", headers=user).status_code == 403
    assert _register(user, registry.TYPE_FUSION, "x", "y", _fusion(0.6)).status_code == 403
    assert client.get("/api/v1/models").status_code == 401


def test_no_route_serves_model_files():
    from starlette.routing import Mount

    _, admin = _user("Admin")
    data = _perturbed(detectors.primary.classifier_state(), heads.SEMANTIC_PREFIX, scale=2e-3)
    reg = _register(admin, registry.TYPE_SEMANTIC, config.DETECTOR_PRIMARY, "test-not-served",
                    data, id2label=json.dumps({"0": "Real", "1": "AI"}))
    sha, model_id = reg.json()["artifact_sha256"], reg.json()["model_id"]
    assert not [r for r in app.routes if isinstance(r, Mount)]  # no static mounts at all
    for url in (f"/static/models/uploads/{sha}.safetensors", f"/storage/models/uploads/{sha}.safetensors",
                f"/models/uploads/{sha}.safetensors", "/static/models/spai.safetensors",
                f"/api/v1/models/{model_id}/file", f"/api/v1/models/{model_id}/artifact",
                f"/api/v1/models/uploads/{sha}.safetensors"):
        r = client.get(url, headers=admin)
        assert r.status_code in (404, 405), url
        assert not r.content.startswith(data[:16])
    listing = client.get("/api/v1/models", headers=admin).text
    assert "uploads/" in listing or sha in listing  # metadata only; never the bytes
    assert data[8:40].hex() not in listing


# --------------------------------------------------------------------------
# Immutability and concurrency
# --------------------------------------------------------------------------

def test_d3_rows_are_immutable_and_used_rows_undeletable():
    _, user = _user()
    pred = _predict(user, png_bytes(make_image(seed=51)))
    with pytest.raises((DBAPIError, IntegrityError)):
        with engine.begin() as c:
            c.execute(text("UPDATE models SET model_version = 'tampered' WHERE model_id = :i"),
                      {"i": pred["model_id"]})
    with pytest.raises((DBAPIError, IntegrityError)):
        with engine.begin() as c:
            c.execute(text("DELETE FROM models WHERE model_id = :i"), {"i": pred["model_id"]})
    with engine.begin() as c:  # is_active alone may change
        c.execute(text("UPDATE models SET is_active = is_active WHERE model_id = :i"), {"i": pred["model_id"]})


def test_concurrent_activations_leave_exactly_one_active_row():
    if engine.dialect.name != "postgresql":
        pytest.skip("row locking and true concurrency: PostgreSQL")
    _, admin = _user("Admin")
    ids = [_register(admin, registry.TYPE_FUSION, "weighted_average fusion", f"race-{t}",
                     _fusion(t)).json()["model_id"] for t in (0.66, 0.70)]
    barrier, outcomes = threading.Barrier(2), {}

    def worker(model_id):
        db = SessionLocal()
        try:
            barrier.wait()
            outcomes[model_id] = registry.activate(db, model_id, actor_id=None).model_id
        except registry.RegistryError as exc:
            outcomes[model_id] = exc.code
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    db = SessionLocal()
    try:
        active = db.query(ModelRegistry).filter(ModelRegistry.model_type == registry.TYPE_FUSION,
                                                ModelRegistry.is_active.is_(True)).all()
        chain = (db.query(ModelActivation).filter(ModelActivation.model_type == registry.TYPE_FUSION)
                 .order_by(ModelActivation.activation_id).all())
    finally:
        db.close()
    assert len(active) == 1 and active[0].model_id in ids, outcomes
    # The history is a consistent chain: each switch names the row that was active before it.
    for prev, nxt in zip(chain, chain[1:]):
        assert nxt.previous_model_id == prev.model_id


# --------------------------------------------------------------------------
# Phase 4 review follow-ups
# --------------------------------------------------------------------------

def test_baseline_anchor_stops_a_ratchet_of_small_steps():
    """Each step is within 0.05 of the last, but the third drifts more than
    0.08 below the published baseline: refused by the anchor alone."""
    _, admin = _user("Admin")
    for tau in (0.85, 0.88):
        reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", f"ratchet-{tau}", _fusion(tau))
        act = _activate(admin, reg.json()["model_id"])
        assert act.status_code == 200, act.text
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "ratchet-0.94", _fusion(0.94))
    act = _activate(admin, reg.json()["model_id"])
    assert act.status_code == 409, act.text
    reasons = act.json()["gate"]["reasons"]
    assert reasons and all("published baseline" in r for r in reasons), reasons  # per-step alone passed


def test_rollback_path_refuses_a_never_activated_row():
    _, admin = _user("Admin")
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "never-active", _fusion(0.7))
    db = SessionLocal()
    try:
        with pytest.raises(registry.RegistryError) as raised:
            registry.activate(db, reg.json()["model_id"], actor_id=None, action="rollback")
        assert raised.value.code == "MDL_ROLLBACK_NOT_PREVIOUS"
    finally:
        db.close()


def test_rollback_canary_stays_blocking(monkeypatch):
    _, admin = _user("Admin")
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "rb-canary", _fusion(0.65))
    assert _activate(admin, reg.json()["model_id"]).status_code == 200
    current = _active_id(registry.TYPE_FUSION)

    def failing(_row):
        raise registry.RegistryError("MDL_CANARY_FAILED", "canary failed (test)", 422)

    monkeypatch.setattr(registry, "canary", failing)
    rb = client.post("/api/v1/models/rollback", headers=admin, json={"model_type": registry.TYPE_FUSION})
    assert rb.status_code == 422 and rb.json()["error"]["code"] == "MDL_CANARY_FAILED"
    assert _active_id(registry.TYPE_FUSION) == current  # nothing changed


def test_rollback_is_audited_as_rollback_with_metrics():
    admin_id, admin = _user("Admin")
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "rb-audit", _fusion(0.65))
    assert _activate(admin, reg.json()["model_id"]).status_code == 200
    assert client.post("/api/v1/models/rollback", headers=admin,
                       json={"model_type": registry.TYPE_FUSION}).status_code == 200
    db = SessionLocal()
    try:
        logs = [entry.event_detail for entry in db.query(LogEntry).filter(LogEntry.user_id == admin_id)]
    finally:
        db.close()
    entry = [line for line in logs if line.startswith("Model ROLLBACK (gate advisory)")]
    assert entry and "candidate={" in entry[0] and "baseline={" in entry[0], logs


def test_startup_warns_when_config_differs_from_the_active_rows(monkeypatch, caplog):
    import logging

    db = SessionLocal()
    try:
        registry.active(db)
        assert registry.config_drift(db) == []
        monkeypatch.setattr(config, "FUSION_TAU", 0.5)  # edit config after the fact
        drift = registry.config_drift(db)
    finally:
        db.close()
    assert len(drift) == 1 and drift[0].startswith(registry.TYPE_FUSION)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        with TestClient(app):  # runs the lifespan: warm-up off in tests, registry check on
            pass
    assert any("config.py is NOT what runs" in r.getMessage() for r in caplog.records)


def test_an_in_flight_request_keeps_the_model_set_it_started_with(monkeypatch):
    """Activation lands while a prediction is mid-inference: that prediction
    runs and records the set it resolved at its start; the next one uses the new set."""
    _, admin = _user("Admin")
    _, user = _user()
    payload = _flip_image()  # fused score between 0.62 and the baseline tau
    before_fusion = _active_id(registry.TYPE_FUSION)
    reg = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", "midflight-0.60", _fusion(0.60))
    new_fusion = reg.json()["model_id"]

    real_score = detectors.primary.score
    fired = {}

    def score_and_activate(*args, **kwargs):
        result = real_score(*args, **kwargs)
        if not fired:
            fired["done"] = True
            db = SessionLocal()
            try:
                registry.activate(db, new_fusion, actor_id=None)
            finally:
                db.close()
        return result

    monkeypatch.setattr(detectors.primary, "score", score_and_activate)
    in_flight = _predict(user, payload)
    assert fired and _active_id(registry.TYPE_FUSION) == new_fusion
    assert in_flight["model_id"] == before_fusion and in_flight["predicted_class"] == "Real"
    monkeypatch.setattr(detectors.primary, "score", real_score)
    after = _predict(user, payload)
    assert after["model_id"] == new_fusion and after["predicted_class"] == "AI Generated"


def test_gate_refuses_a_stale_or_unkeyed_reference_cache(monkeypatch):
    """Changing anything the cached features depend on - here the SPAI
    preprocessing (resize_to) - makes the cache stale, and the gate refuses."""
    ref = gate.load_reference()
    assert gate.stale_reason(ref) is None  # the real cache matches the current setup
    monkeypatch.setattr(config, "DETECTOR_FREQUENCY_RESIZE_TO", 1024)
    reason = gate.stale_reason(ref)
    assert reason and "stale" in reason
    unkeyed = {k: v for k, v in ref.items() if k != "cache_key"}
    assert "no content key" in gate.stale_reason(unkeyed)


def test_gate_preview_reports_the_verdict_without_switching():
    """Phase 5b: the admin screen shows a candidate's gate metrics before any
    decision. The preview must agree with activation and change nothing."""
    _, admin = _user("Admin")
    _, user = _user("User")
    baseline_fusion = _active_id(registry.TYPE_FUSION)
    bad = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", f"prev{next(_n)}", _fusion(0.05))
    good = _register(admin, registry.TYPE_FUSION, "weighted_average fusion", f"prev{next(_n)}", _fusion(0.74))
    assert bad.status_code == 201 and good.status_code == 201
    db = SessionLocal()
    try:
        activations_before = db.query(ModelActivation).count()
    finally:
        db.close()

    refused = client.post(f"/api/v1/models/{bad.json()['model_id']}/gate-preview", headers=admin)
    assert refused.status_code == 200, refused.text
    body = refused.json()
    assert body["gate"]["available"] and body["gate"]["passed"] is False
    assert {"accuracy", "fpr", "auc", "recall"} <= set(body["gate"]["candidate"])
    assert body["canary"]
    passed = client.post(f"/api/v1/models/{good.json()['model_id']}/gate-preview", headers=admin).json()
    assert passed["gate"]["passed"] is True

    assert client.post(f"/api/v1/models/{bad.json()['model_id']}/gate-preview", headers=user).status_code == 403
    missing = client.post("/api/v1/models/987654/gate-preview", headers=admin)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "MDL_NOT_FOUND"

    assert _active_id(registry.TYPE_FUSION) == baseline_fusion
    db = SessionLocal()
    try:
        assert db.query(ModelActivation).count() == activations_before
    finally:
        db.close()
    # And activation reaches the same verdict the preview showed.
    assert _activate(admin, bad.json()["model_id"]).json()["error"]["code"] == "MDL_GATE_REFUSED"
