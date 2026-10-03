"""How long model registration and activation take (for the admin UI). MEASUREMENT ONLY.

    python ml/evaluation/activation_cost.py

Through the real HTTP API against a scratch SQLite database, models warm
(the lifespan warm-up runs first). Uses the gate's reference cache and
PERTURBED copies of the published heads (this project trains nothing).
Prints wall times per call; nothing is written.
"""

from __future__ import annotations

import io
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="truepixels-activation-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{(scratch / 'a.db').as_posix()}"
    os.environ["STORAGE_DIR"] = str(scratch / "storage")
    os.environ["REQUIRE_2FA"] = "False"
    sys.path.insert(0, str(REPO / "backend"))

    import torch
    from fastapi.testclient import TestClient
    from safetensors.torch import save as save_safetensors

    from app.m1_access.models import User
    from app.m1_access.security import create_session_token, hash_password
    from app.m2_analysis import detectors, frequency_detector, gate, heads
    from app.main import app
    from app.shared import db

    if gate.load_reference() is None:
        raise SystemExit("build the gate reference first: backend/scripts/build_reference_set.py")
    db.migrate_to_head()
    s = db.SessionLocal()
    u = User(full_name="A", email="act@example.com", password_hash=hash_password("Activation1234"),
             role="Admin", account_status="active", is_email_verified=True)
    s.add(u)
    s.commit()
    s.refresh(u)
    admin = {"Authorization": f"Bearer {create_session_token(u)[0]}"}
    s.close()

    def perturbed(state, prefix):
        g = torch.Generator().manual_seed(0)
        return save_safetensors({prefix + k: (v.float().cpu() + 1e-3 * torch.randn(v.shape, generator=g))
                                 .contiguous() for k, v in state.items()})

    def timed(call):
        t = time.perf_counter()
        r = call()
        return (time.perf_counter() - t) * 1000, r

    rows = []
    with TestClient(app) as c:
        def register(model_type, version, data, **form):
            fields = {"model_type": model_type, "name": f"cost-{model_type}", "version": version,
                      "training_reference": "timing only", **form}
            return c.post("/api/v1/models", headers=admin, data=fields,
                          files={"file": ("a", data, "application/octet-stream")})

        fusion_times = []
        for i, tau in enumerate((0.70, 0.72, 0.74)):
            r = register("fusion-configuration", f"t{i}", json.dumps(
                {"strategy": "weighted_average", "weight_semantic": 0.25, "tau": tau, "temperature": 1.0}).encode())
            ms, a = timed(lambda: c.post(f"/api/v1/models/{r.json()['model_id']}/activate", headers=admin, json={}))
            assert a.status_code == 200, a.text
            fusion_times.append(ms)
        rows.append(("activate fusion config (canary + gate + switch)", fusion_times))

        sem = perturbed(detectors.primary.classifier_state(), heads.SEMANTIC_PREFIX)
        ms_reg, r = timed(lambda: register("semantic-classifier", "h1", sem, id2label='{"0": "Real", "1": "AI"}'))
        ms_act, a = timed(lambda: c.post(f"/api/v1/models/{r.json()['model_id']}/activate", headers=admin, json={}))
        rows.append(("register SigLIP head (~6 KB)", [ms_reg]))
        rows.append((f"activate SigLIP head (status {a.status_code})", [ms_act]))

        spai = perturbed(frequency_detector.frequency.cls_head_state(), heads.FREQUENCY_PREFIX)
        ms_reg, r = timed(lambda: register("frequency-artifact-classifier", "h1", spai, ai_is_positive="true"))
        ms_act, a = timed(lambda: c.post(f"/api/v1/models/{r.json()['model_id']}/activate", headers=admin, json={}))
        rows.append((f"register SPAI head ({len(spai) / 2**20:.0f} MB)", [ms_reg]))
        rows.append((f"activate SPAI head (status {a.status_code})", [ms_act]))

        ms, rb = timed(lambda: c.post("/api/v1/models/rollback", headers=admin,
                                      json={"model_type": "fusion-configuration"}))
        rows.append((f"rollback fusion (status {rb.status_code})", [ms]))

    for label, values in rows:
        print(f"  {label:<52} median {statistics.median(values):7.0f} ms   runs {[round(v) for v in values]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
