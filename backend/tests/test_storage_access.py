"""Stored files are served only through owner-checked endpoints.

Regression tests for the unauthenticated ``/static`` mount, which served the
whole storage tree - every user's uploads, and the model weights - to anyone
who had the URL. Now:

* ``GET /api/v1/images/{id}/file`` (M1) serves an original to its owner
  only - not to Admins either (least privilege);
* ``GET /api/v1/explainability/{prediction_id}/{branch}`` (M3) serves a panel
  to the owner of the prediction only (M3's existing rule for results);
* everything else - another user, no session, a missing id, a reference
  outside the storage tree - gets the same not-found answer, and ``/static``
  no longer exists.

No model is needed: upload goes through M1 only, and predictions are D4 rows
written directly.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.m1_access.models import Image, User
from app.m1_access.security import create_session_token, hash_password
from app.m2_analysis.models import ModelRegistry, Prediction
from app.m3_results.models import Explainability
from app.main import app
from app.shared import config
from app.shared.db import SessionLocal
from conftest import make_image, png_bytes

client = TestClient(app)
_emails = itertools.count()
PNG_MAGIC = bytes([0x89]) + b"PNG"


# The shared test database (root conftest); emptied after each test.
_sessions = SessionLocal


def make_user(role: str = "User") -> tuple[int, dict[str, str]]:
    db = _sessions()
    try:
        user = User(
            full_name="Storage Test",
            email=f"storage-{next(_emails)}@example.com",
            password_hash=hash_password("StorageTest12345"),
            role=role,
            account_status="active",
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token, _, _ = create_session_token(user)
        return user.user_id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def upload(headers: dict[str, str], seed: int) -> tuple[int, bytes]:
    payload = png_bytes(make_image(seed=seed))
    response = client.post("/api/v1/images", headers=headers,
                           files={"file": ("x.png", payload, "image/png")})
    assert response.status_code == 201, response.text
    return response.json()["image_id"], payload


def add_prediction(image_id: int, panel_reference: str) -> int:
    """A D4 row plus one semantic D5 row pointing at ``panel_reference``."""
    db = _sessions()
    try:
        model = db.query(ModelRegistry).first()
        if model is None:
            model = ModelRegistry(model_name="test fusion", model_version="t",
                                  model_type="fusion-configuration", artifact_ref="test",
                                  is_active=True)
            db.add(model)
            db.flush()
        prediction = Prediction(image_id=image_id, model_id=model.model_id,
                                branch_model_ids={}, predicted_class="Real",
                                confidence_score=0.9, semantic_score=0.1,
                                frequency_score=0.1, fusion_score=0.1, latency_ms=1,
                                prediction_timestamp=datetime.now(timezone.utc))
        db.add(prediction)
        db.flush()
        db.add(Explainability(prediction_id=prediction.prediction_id, branch="semantic",
                              technique="attention-rollout",
                              visualization_reference=panel_reference,
                              generated_at=datetime.now(timezone.utc)))
        db.commit()
        return prediction.prediction_id
    finally:
        db.close()


def assert_not_found(response, code: str) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == code


# --------------------------------------------------------------------------
# /static is gone
# --------------------------------------------------------------------------

def test_static_mount_no_longer_serves_storage():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=11)
    db = _sessions()
    reference = db.get(Image, image_id).file_reference
    db.close()
    relative = config.UPLOADS_DIR.name + "/" + "/".join(reference.replace("\\", "/").split("/")[-3:])
    for url in (f"/static/{relative}", "/static/models/spai.safetensors", "/static/models/spai.pth"):
        response = client.get(url)
        assert response.status_code == 404, url
        assert not response.content.startswith(b"\x89PNG")


# --------------------------------------------------------------------------
# Originals: GET /api/v1/images/{id}/file
# --------------------------------------------------------------------------

def test_owner_downloads_their_original():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=12)
    response = client.get(f"/api/v1/images/{image_id}/file", headers=owner)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content.startswith(b"\x89PNG")


def test_other_user_gets_the_same_answer_as_a_missing_image():
    _, owner = make_user()
    _, stranger = make_user()
    image_id, _ = upload(owner, seed=13)
    not_yours = client.get(f"/api/v1/images/{image_id}/file", headers=stranger)
    missing = client.get("/api/v1/images/999999/file", headers=stranger)
    assert_not_found(not_yours, "IMG_NOT_FOUND")
    assert_not_found(missing, "IMG_NOT_FOUND")
    assert not_yours.json()["error"]["message"].replace(str(image_id), "N") == \
        missing.json()["error"]["message"].replace("999999", "N")


def test_no_session_is_rejected():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=14)
    assert client.get(f"/api/v1/images/{image_id}/file").status_code == 401


def test_admin_cannot_view_another_users_original():
    """Owner only (least privilege): an Admin gets the same 404 as anyone else."""
    _, owner = make_user()
    _, admin = make_user(role="Admin")
    image_id, _ = upload(owner, seed=15)
    assert_not_found(client.get(f"/api/v1/images/{image_id}/file", headers=admin), "IMG_NOT_FOUND")


def test_reference_outside_uploads_is_refused(tmp_path):
    """Defence in depth: a D2 row pointing outside the uploads tree serves nothing."""
    user_id, owner = make_user()
    image_id, _ = upload(owner, seed=16)
    outside = tmp_path / "secret.png"
    outside.write_bytes(png_bytes(make_image(seed=99)))
    db = _sessions()
    db.get(Image, image_id).file_reference = str(outside)
    db.commit()
    db.close()
    assert_not_found(client.get(f"/api/v1/images/{image_id}/file", headers=owner), "IMG_NOT_FOUND")


def test_results_and_history_link_to_the_authenticated_endpoint():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=17)
    prediction_id = add_prediction(image_id, "unused.png")
    result = client.get(f"/api/v1/results/{prediction_id}", headers=owner).json()
    assert result["original_image_url"] == f"/api/v1/images/{image_id}/file"
    assert result["visualizations"][0]["visualization_url"] == \
        f"/api/v1/explainability/{prediction_id}/semantic"
    history = client.get("/api/v1/history", headers=owner).json()["items"]
    assert history[0]["thumbnail_url"] == f"/api/v1/images/{image_id}/thumbnail"
    assert not any("/static" in str(v) for v in [result, history])


# --------------------------------------------------------------------------
# Explainability panels: GET /api/v1/explainability/{prediction_id}/{branch}
# --------------------------------------------------------------------------

@pytest.fixture
def panel() -> str:
    config.EXPLAINABILITY_DIR.mkdir(parents=True, exist_ok=True)
    path = config.EXPLAINABILITY_DIR / f"test_panel_{next(_emails)}.png"
    path.write_bytes(png_bytes(make_image(width=64, height=64, seed=5)))
    return str(path.resolve())


def test_owner_downloads_a_panel(panel):
    _, owner = make_user()
    image_id, _ = upload(owner, seed=21)
    prediction_id = add_prediction(image_id, panel)
    response = client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=owner)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_panel_not_yours_missing_branch_and_missing_prediction_look_alike(panel):
    _, owner = make_user()
    _, stranger = make_user()
    image_id, _ = upload(owner, seed=22)
    prediction_id = add_prediction(image_id, panel)
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=stranger),
                     "INF_PREDICTION_NOT_FOUND")
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/frequency", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")
    assert_not_found(client.get("/api/v1/explainability/999999/semantic", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")
    assert client.get(f"/api/v1/explainability/{prediction_id}/semantic").status_code == 401


def test_panel_reference_outside_explainability_dir_is_refused():
    """A D5 row that points at an upload (or anything else) serves nothing."""
    _, owner = make_user()
    image_id, _ = upload(owner, seed=23)
    db = _sessions()
    upload_path = db.get(Image, image_id).file_reference
    db.close()
    prediction_id = add_prediction(image_id, upload_path)
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")


# --------------------------------------------------------------------------
# Path traversal: references are checked after full resolution
# --------------------------------------------------------------------------

def _outside_png(directory) -> str:
    """A real PNG that exists but lies outside the directory being served."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"outside_{next(_emails)}.png"
    path.write_bytes(png_bytes(make_image(width=64, height=64, seed=77)))
    return str(path.resolve())


def _set_image_reference(image_id: int, reference: str) -> None:
    db = _sessions()
    db.get(Image, image_id).file_reference = reference
    db.commit()
    db.close()


def _traversal_references(served_root, target: str) -> list[str]:
    """Ways of naming ``target`` that start inside ``served_root``."""
    from pathlib import Path
    up = "/".join([".."] * len(served_root.resolve().parts))
    # Strip the anchor ("C:\" or "/") so the climb lands on the same drive.
    below_anchor = Path(target).relative_to(Path(target).anchor).as_posix()
    return [
        str(served_root / ".." / "escape" / target.split("\\")[-1].split("/")[-1]),  # absolute, with ../
        f"../escape/{target.split(chr(92))[-1].split('/')[-1]}",                       # relative, with ../
        f"{up}/{below_anchor}",                                                         # relative, climbs to root
    ]


@pytest.mark.parametrize("variant", [0, 1, 2])
def test_image_reference_with_dotdot_is_refused(variant):
    target = _outside_png(config.STORAGE_ROOT / "escape")  # a sibling of uploads/
    _, owner = make_user()
    image_id, _ = upload(owner, seed=40 + variant)
    reference = _traversal_references(config.UPLOADS_DIR, target)[variant]
    _set_image_reference(image_id, reference)
    assert_not_found(client.get(f"/api/v1/images/{image_id}/file", headers=owner), "IMG_NOT_FOUND")


@pytest.mark.parametrize("variant", [0, 1, 2])
def test_panel_reference_with_dotdot_is_refused(variant):
    target = _outside_png(config.STORAGE_ROOT / "escape")  # a sibling of explainability/
    _, owner = make_user()
    image_id, _ = upload(owner, seed=50 + variant)
    reference = _traversal_references(config.EXPLAINABILITY_DIR, target)[variant]
    prediction_id = add_prediction(image_id, reference)
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")


def _link_dir_or_skip(link, target_dir) -> str:
    """Make ``link`` a directory link to ``target_dir``; return its kind.

    A symlink where the OS allows it. Windows refuses symlinks to
    unprivileged processes (WinError 1314), but not NTFS junctions - the
    same escape (a reparse point inside the served tree pointing outside it),
    so the test still runs on the development machine.
    """
    try:
        link.symlink_to(target_dir, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(str(target_dir), str(link))
        return "junction"
    except (ImportError, OSError) as exc:
        pytest.skip(f"cannot create a symlink or junction here: {exc}")


def test_image_link_escaping_uploads_is_refused(tmp_path):
    target = _outside_png(tmp_path / "outside")
    _, owner = make_user()
    image_id, _ = upload(owner, seed=60)
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    link = config.UPLOADS_DIR / f"link_{next(_emails)}"
    _link_dir_or_skip(link, tmp_path / "outside")
    via_link = link / target.replace("\\", "/").split("/")[-1]
    assert via_link.read_bytes().startswith(PNG_MAGIC)  # the link really leads out
    _set_image_reference(image_id, str(via_link))
    assert_not_found(client.get(f"/api/v1/images/{image_id}/file", headers=owner), "IMG_NOT_FOUND")


def test_panel_link_escaping_explainability_dir_is_refused(tmp_path):
    target = _outside_png(tmp_path / "outside")
    _, owner = make_user()
    image_id, _ = upload(owner, seed=61)
    config.EXPLAINABILITY_DIR.mkdir(parents=True, exist_ok=True)
    link = config.EXPLAINABILITY_DIR / f"link_{next(_emails)}"
    _link_dir_or_skip(link, tmp_path / "outside")
    via_link = link / target.replace("\\", "/").split("/")[-1]
    assert via_link.read_bytes().startswith(PNG_MAGIC)
    prediction_id = add_prediction(image_id, str(via_link))
    assert_not_found(client.get(f"/api/v1/explainability/{prediction_id}/semantic", headers=owner),
                     "INF_PREDICTION_NOT_FOUND")


def test_traversal_guard_is_what_refuses(tmp_path):
    """Guard the guard: the same escaping reference IS readable on disk, so the
    404s above come from the resolved-path check, not from a missing file."""
    from pathlib import Path
    target = _outside_png(config.STORAGE_ROOT / "escape")
    for reference in _traversal_references(config.UPLOADS_DIR, target):
        path = Path(reference)
        if not path.is_absolute():
            path = config.UPLOADS_DIR / path
        assert path.resolve(strict=True).read_bytes().startswith(PNG_MAGIC), reference


# --------------------------------------------------------------------------
# Thumbnails: GET /api/v1/images/{id}/thumbnail
# --------------------------------------------------------------------------

def test_owner_gets_a_small_jpeg_thumbnail():
    import io

    from PIL import Image as PILImage

    _, owner = make_user()
    payload = png_bytes(make_image(width=900, height=600, seed=70))
    image_id = client.post("/api/v1/images", headers=owner,
                           files={"file": ("x.png", payload, "image/png")}).json()["image_id"]
    response = client.get(f"/api/v1/images/{image_id}/thumbnail", headers=owner)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    with PILImage.open(io.BytesIO(response.content)) as thumb:
        assert max(thumb.size) == 256 and thumb.size == (256, 171)


def test_thumbnail_follows_the_same_access_rules_as_the_original():
    _, owner = make_user()
    _, stranger = make_user()
    _, admin = make_user(role="Admin")
    image_id, _ = upload(owner, seed=71)
    url = f"/api/v1/images/{image_id}/thumbnail"
    assert_not_found(client.get(url, headers=stranger), "IMG_NOT_FOUND")
    assert_not_found(client.get(url, headers=admin), "IMG_NOT_FOUND")
    assert_not_found(client.get("/api/v1/images/999999/thumbnail", headers=owner), "IMG_NOT_FOUND")
    assert client.get(url).status_code == 401


@pytest.mark.parametrize("variant", [0, 1, 2])
def test_thumbnail_reference_with_dotdot_is_refused(variant):
    target = _outside_png(config.STORAGE_ROOT / "escape")
    _, owner = make_user()
    image_id, _ = upload(owner, seed=80 + variant)
    _set_image_reference(image_id, _traversal_references(config.UPLOADS_DIR, target)[variant])
    assert_not_found(client.get(f"/api/v1/images/{image_id}/thumbnail", headers=owner),
                     "IMG_NOT_FOUND")


def test_report_download_no_longer_accepts_a_query_token():
    """Phase 5a: a session token in a URL is refused; only the header works."""
    from app.m1_access.security import create_session_token

    user_id, owner = make_user()
    image_id, _ = upload(owner, seed=90)
    prediction_id = add_prediction(image_id, "unused.png")
    token = owner["Authorization"].split(" ", 1)[1]
    assert client.get(f"/api/v1/reports/{prediction_id}?token={token}").status_code == 401
    ok = client.get(f"/api/v1/reports/{prediction_id}", headers=owner)
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/pdf"


def test_results_name_the_models_that_produced_the_prediction():
    _, owner = make_user()
    image_id, _ = upload(owner, seed=91)
    prediction_id = add_prediction(image_id, "unused.png")
    models = client.get(f"/api/v1/results/{prediction_id}", headers=owner).json()["models"]
    assert models["fusion"]["model_name"] == "test fusion" and models["semantic"] is None


def test_every_file_endpoint_has_a_hard_size_bound(monkeypatch, panel):
    """Files are read fully into memory, so each endpoint refuses a stored file
    above its ceiling with a structured 413 instead of reading it."""
    from app.shared import files

    _, owner = make_user()
    image_id, _ = upload(owner, seed=95)
    prediction_id = add_prediction(image_id, panel)
    monkeypatch.setattr(files, "MAX_STORED_ORIGINAL_BYTES", 100)
    monkeypatch.setattr(files, "MAX_STORED_PANEL_BYTES", 100)
    for url in (f"/api/v1/images/{image_id}/file", f"/api/v1/images/{image_id}/thumbnail",
                f"/api/v1/explainability/{prediction_id}/semantic"):
        r = client.get(url, headers=owner)
        assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE", (url, r.text)
