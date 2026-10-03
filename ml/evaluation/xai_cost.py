"""What explainability costs: latency and peak VRAM, xai off vs on. MEASUREMENT ONLY.

    python ml/evaluation/xai_cost.py [--repeats 3]

For each image, warm (models loaded before timing starts), through the real
HTTP path against a scratch SQLite database, alternating xai=false and
xai=true, ``--repeats`` times each:

- latency_ms          inference only (both branches + fusion), from the response
- wall_ms             whole request, from X-Process-Time-Ms
- xai_ms              X-XAI-Time-Ms: attention recomputation + SPAI-patch
                      spectrum + panel rendering + D5 write
- peak_vram_mb        torch.cuda.max_memory_allocated during that request
                      (reset before each request)

plus a per-image component split measured directly: attention recomputation,
spectrum, and rendering. Medians are reported. Writes
ml/outputs/xai_cost_<stamp>.json (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATASETS = REPO / "ml" / "datasets"
IMAGES = [
    "synthbuster_raise/1_fake/dalle2/r000da54ft.png",            # 1024 x 1024
    "synthbuster_raise/1_fake/firefly/r01058910t.png",           # 1792 x 2304
    "synthbuster_raise__jpeg90/0_real/r000da54ft.jpg",           # 4288 x 2848 (12 MP)
    "synthbuster_raise__jpeg90/0_real/r001d260dt.jpg",           # 3264 x 4928 (16 MP)
    "synthbuster_raise__jpeg90/0_real/r002fc3e2t.jpg",           # 3264 x 4928 (16 MP)
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="truepixels-xaicost-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{(scratch / 'cost.db').as_posix()}"
    os.environ["STORAGE_DIR"] = str(scratch / "storage")
    os.environ["REQUIRE_2FA"] = "False"
    sys.path.insert(0, str(REPO / "backend"))

    import torch
    from fastapi.testclient import TestClient
    from PIL import Image

    from app.m1_access.models import Image as DBImage
    from app.m1_access.models import User
    from app.m1_access.security import create_session_token, hash_password
    from app.m2_analysis import detectors, xai
    from app.m3_results.explain import build_relevance_map
    from app.m3_results.overlay import generate_frequency_spectrum_panel, generate_semantic_overlay
    from app.main import app
    from app.shared import config, db as database
    from app.shared.schemas import ActivationBundle

    database.migrate_to_head()
    session = database.SessionLocal()
    user = User(full_name="Cost", email="cost@example.com", password_hash=hash_password("XaiCost123456"),
                role="User", account_status="active", is_email_verified=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    headers = {"Authorization": f"Bearer {create_session_token(user)[0]}"}
    session.close()
    cuda = torch.cuda.is_available()

    rows = []
    with TestClient(app) as client:  # lifespan: warm-up loads both models first
        for rel in IMAGES:
            path = DATASETS / rel
            if not path.is_file():
                print(f"  missing {rel}; skipped")
                continue
            with Image.open(path) as handle:
                size = handle.size
            mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            up = client.post("/api/v1/images", headers=headers,
                             files={"file": (path.name, path.read_bytes(), mime)})
            assert up.status_code == 201, up.text
            image_id = up.json()["image_id"]
            runs = {False: [], True: []}
            for _ in range(args.repeats):
                for flag in (False, True):
                    if cuda:
                        torch.cuda.synchronize()
                        torch.cuda.reset_peak_memory_stats()
                    r = client.post("/api/v1/predictions", headers=headers,
                                    json={"image_id": image_id, "xai": flag})
                    assert r.status_code == 201, r.text
                    runs[flag].append({
                        "latency_ms": r.json()["latency_ms"],
                        "wall_ms": float(r.headers["x-process-time-ms"]),
                        "xai_ms": float(r.headers.get("x-xai-time-ms", 0.0)),
                        "xai_status": r.json()["xai_status"],
                        "peak_vram_mb": (torch.cuda.max_memory_allocated() / 2**20) if cuda else None,
                    })

            # Component split, measured directly on the same image.
            t = time.perf_counter()
            captured = detectors.primary.score(str(path), capture=True)
            t_score = time.perf_counter() - t
            t = time.perf_counter()
            maps = detectors.primary.attention_maps(captured.activations)
            t_attention = time.perf_counter() - t
            t = time.perf_counter()
            spectrum, meta = xai.spai_patch_spectrum(str(path), resize_to=config.DETECTOR_FREQUENCY_RESIZE_TO)
            t_spectrum = time.perf_counter() - t
            t = time.perf_counter()
            grid, _ = build_relevance_map(ActivationBundle(
                backbone=maps["backbone"], patch_grid=maps["patch_grid"],
                attention=maps["attention"], pooling=maps["pooling"]))
            generate_semantic_overlay(str(path), grid, size[0], size[1], str(scratch / "o.png"))
            t_overlay = time.perf_counter() - t
            t = time.perf_counter()
            generate_frequency_spectrum_panel(spectrum, str(scratch / "s.png"), meta=meta)
            t_panel = time.perf_counter() - t

            def med(flag, key):
                values = [r[key] for r in runs[flag] if r[key] is not None]
                return round(statistics.median(values), 1) if values else None

            row = {
                "image": rel, "size": list(size), "megapixels": round(size[0] * size[1] / 1e6, 1),
                "spai_patches": meta["patches"], "xai_status": runs[True][0]["xai_status"],
                "off": {k: med(False, k) for k in ("latency_ms", "wall_ms", "peak_vram_mb")},
                "on": {k: med(True, k) for k in ("latency_ms", "wall_ms", "xai_ms", "peak_vram_mb")},
                "components_ms": {"semantic_score_with_capture": round(t_score * 1000, 1),
                                  "attention_recompute": round(t_attention * 1000, 1),
                                  "spai_patch_spectrum": round(t_spectrum * 1000, 1),
                                  "rollout_and_overlay": round(t_overlay * 1000, 1),
                                  "spectrum_panel": round(t_panel * 1000, 1)},
                "runs": {"off": runs[False], "on": runs[True]},
            }
            rows.append(row)
            print(f"  {row['megapixels']:>5} MP  wall off {row['off']['wall_ms']:>7} ms  on "
                  f"{row['on']['wall_ms']:>7} ms  xai {row['on']['xai_ms']:>6} ms  "
                  f"VRAM off {row['off']['peak_vram_mb']} MB  on {row['on']['peak_vram_mb']} MB  {rel}")

    out = REPO / "ml" / "outputs" / f"xai_cost_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"device": str(config.DEVICE), "repeats": args.repeats,
                               "gpu": torch.cuda.get_device_name(0) if cuda else None,
                               "rows": rows}, indent=2) + "\n")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
