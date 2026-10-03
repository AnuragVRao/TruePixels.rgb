"""NF.5 regression check: are predictions bit-identical to a recorded baseline?

    python ml/evaluation/regression_check.py --record [--out NAME]
    python ml/evaluation/regression_check.py --compare [--against NAME]
    python ml/evaluation/regression_check.py --make-list      # once; list is committed

Each image takes the full production path through HTTP - M1 upload
(validation, storage, C1), POST /api/v1/predictions (M2: both branches,
fusion, D4 commit) - against a scratch database and storage tree, so a change
anywhere in that path that moves a score is caught, not only a change to the
detectors themselves.

Scores are stored as ``float.hex``: exact, not rounded. JSON numbers from the
API are Python's shortest round-trip repr, so parsing them back recovers the
same float64 bit for bit. ``latency_ms`` and ids are deliberately not compared.

The image list (``regression_images.json``, committed) names files under
``ml/datasets/`` - which are gitignored and re-created by the fetch scripts -
plus seeded synthetic images generated here, including one below SPAI's
224 px minimum so the semantic-only passthrough is covered. Results go to
``ml/outputs/regression/`` (gitignored).

Identical results are only expected on the same device and software stack:
GPU and CPU differ in the last bits (CLAUDE.md section 4 measured 0.0006).
The device is recorded with each baseline and a mismatch is reported.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
DATASETS = REPO_ROOT / "ml" / "datasets"
LIST_FILE = Path(__file__).with_name("regression_images.json")
OUTPUT_DIR = REPO_ROOT / "ml" / "outputs" / "regression"
FIELDS = ("predicted_class", "confidence_score", "semantic_score", "frequency_score", "fusion_score")

# Synthetic images: (name, width, height, seed). 128 px is below one SPAI
# patch, so it exercises the semantic-only path (frequency_score null).
SYNTHETIC = [
    ("synthetic-128x128-s1", 128, 128, 1),
    ("synthetic-256x256-s7", 256, 256, 7),
    ("synthetic-1500x1000-s3", 1500, 1000, 3),
]


def make_list() -> None:
    """Pick a fixed, uploadable subset of the local evaluation sets.

    One generated image per Synthbuster generator at native resolution (PNG),
    camera originals as lossless 1024 crops (PNG - RAISE's TIFFs are not an
    accepted upload format), and a few JPEG q90 variants of both classes so
    the JPEG decode path is covered too. First files in sorted order, so the
    choice is reproducible from the fetch scripts.
    """
    items: list[str] = []
    native_fake = DATASETS / "synthbuster_raise" / "1_fake"
    for generator in sorted(p for p in native_fake.iterdir() if p.is_dir()):
        items.append(sorted(generator.iterdir())[0].relative_to(DATASETS).as_posix())
    crop_real = sorted((DATASETS / "synthbuster_raise__crop1024" / "0_real").iterdir())
    items += [p.relative_to(DATASETS).as_posix() for p in crop_real[:6]]
    jpeg = DATASETS / "synthbuster_raise__jpeg90"
    items += [p.relative_to(DATASETS).as_posix() for p in sorted((jpeg / "0_real").iterdir())[:3]]
    jpeg_fake = sorted(p for p in (jpeg / "1_fake").rglob("*") if p.is_file())
    items += [p.relative_to(DATASETS).as_posix() for p in jpeg_fake[:3]]
    LIST_FILE.write_text(json.dumps({"datasets_root": "ml/datasets", "images": items}, indent=2) + "\n")
    print(f"wrote {len(items)} entries to {LIST_FILE}")


def synthetic_png(width: int, height: int, seed: int) -> bytes:
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def payloads() -> list[tuple[str, bytes, str]]:
    listed = json.loads(LIST_FILE.read_text())["images"]
    out: list[tuple[str, bytes, str]] = []
    missing = []
    for rel in listed:
        path = DATASETS / rel
        if not path.is_file():
            missing.append(rel)
            continue
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        out.append((rel, path.read_bytes(), mime))
    if missing:
        raise SystemExit(
            f"{len(missing)} listed images are missing under {DATASETS} (first: {missing[0]}); "
            "re-create them with ml/datasets/fetch_*.py and make_variants.py"
        )
    for name, width, height, seed in SYNTHETIC:
        out.append((name, synthetic_png(width, height, seed), "image/png"))
    return out


def run(database_url: str | None = None) -> dict:
    """Score every payload through the HTTP path; return {name: {field: value}}.

    ``database_url``: run against this database instead of a scratch SQLite
    file - e.g. PostgreSQL, to check the scores survive the whole path through
    it. Its schema is dropped and rebuilt with the migrations, so the name
    must end in ``_test`` or ``_regression``.
    """
    scratch = Path(tempfile.mkdtemp(prefix="truepixels-regression-"))
    if database_url is None:
        database_url = f"sqlite:///{(scratch / 'regression.db').as_posix()}"
    elif not database_url.rsplit("/", 1)[-1].split("?")[0].endswith(("_test", "_regression")):
        raise SystemExit("--database-url must name a scratch database ending in _test or "
                         "_regression: its schema is dropped and rebuilt")
    os.environ["DATABASE_URL"] = database_url
    os.environ["STORAGE_DIR"] = str(scratch / "storage")
    os.environ.setdefault("EMAIL_BACKEND", "console")
    os.environ["REQUIRE_2FA"] = "False"
    # WARMUP_ON_STARTUP is left at its default (on): the check runs the app the
    # way production does, so a warm-up that changed a score would be caught.
    sys.path.insert(0, str(BACKEND_ROOT))

    from fastapi.testclient import TestClient

    from app.m1_access.models import User
    from app.m1_access.security import create_session_token, hash_password
    from app.main import app
    from app.shared import config
    from sqlalchemy import inspect, text

    from app.shared import db as database
    from app.shared.db import SessionLocal

    database.import_all_models()
    with database.engine.begin() as connection:
        database.Base.metadata.drop_all(bind=connection)
        if inspect(connection).has_table("alembic_version"):
            connection.execute(text("DROP TABLE alembic_version"))
    database.migrate_to_head()
    db = SessionLocal()
    user = User(full_name="Regression", email="regression@example.com",
                password_hash=hash_password("Regression12345"), role="User",
                account_status="active", is_email_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    token, _, _ = create_session_token(user)
    db.close()
    headers = {"Authorization": f"Bearer {token}"}

    results: dict[str, dict] = {}
    with TestClient(app) as client:
        for name, data, mime in payloads():
            up = client.post("/api/v1/images", headers=headers,
                             files={"file": (Path(name).name, data, mime)})
            if up.status_code != 201:
                raise SystemExit(f"upload failed for {name}: {up.status_code} {up.text}")
            pred = client.post("/api/v1/predictions", headers=headers,
                               json={"image_id": up.json()["image_id"], "xai": False})
            if pred.status_code not in (200, 201):
                raise SystemExit(f"prediction failed for {name}: {pred.status_code} {pred.text}")
            body = pred.json()
            results[name] = {
                f: (float(body[f]).hex() if isinstance(body[f], (int, float)) else body[f])
                for f in FIELDS
            }
            print(f"  {body['predicted_class']:<13} fusion={body['fusion_score']:.6f}  {name}")
    return {"device": str(config.DEVICE), "database": database.engine.dialect.name,
            "results": results}


def latest() -> Path:
    files = sorted(OUTPUT_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"no baseline in {OUTPUT_DIR}; run with --record first")
    return files[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--make-list", action="store_true")
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--compare", action="store_true")
    parser.add_argument("--out", help="baseline name for --record (default: timestamp)")
    parser.add_argument("--against", help="baseline file name for --compare (default: newest)")
    parser.add_argument("--database-url", help="run through this database (scratch, *_test or "
                        "*_regression) instead of a temporary SQLite file")
    args = parser.parse_args()

    if args.make_list:
        make_list()
        return 0

    current = run(args.database_url)
    if args.record:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = OUTPUT_DIR / f"{args.out or 'baseline'}_{stamp}.json"
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"recorded {len(current['results'])} images -> {path}")
        return 0

    path = OUTPUT_DIR / args.against if args.against else latest()
    baseline = json.loads(path.read_text())
    if baseline["device"] != current["device"]:
        print(f"WARNING: baseline device {baseline['device']} != current {current['device']}; "
              "last-bit differences are expected across devices")
    diffs = []
    for name in sorted(set(baseline["results"]) | set(current["results"])):
        old, new = baseline["results"].get(name), current["results"].get(name)
        if old != new:
            diffs.append((name, old, new))
    if diffs:
        print(f"MISMATCH against {path.name}: {len(diffs)} of {len(baseline['results'])} images differ")
        for name, old, new in diffs:
            print(f"  {name}\n    baseline {old}\n    current  {new}")
        return 1
    print(f"IDENTICAL: all {len(current['results'])} images bit-identical to {path.name} "
          f"({len(FIELDS)} fields each, device {current['device']}, "
          f"database {current.get('database', '?')}; baseline database "
          f"{baseline.get('database', 'sqlite')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
