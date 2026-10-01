"""End-to-end API integration tests for Module M1 (SRS F.5, F.6, F.7)."""
import io
import pytest
from app.m1_access.models import User
from app.m1_access.security import hash_password, create_session_token


def test_image_upload_and_preprocess_success(client, user_auth_headers, sample_jpeg_bytes):
    """F.5, F.6, F.7: Uploading a valid JPEG succeeds, records in D2, and preprocesses tensor."""
    files = {"file": ("test_sample.jpg", sample_jpeg_bytes, "image/jpeg")}
    res = client.post("/api/v1/images", headers=user_auth_headers, files=files)

    assert res.status_code == 201
    data = res.json()
    assert data["validation_status"] == "valid"
    assert "image_id" in data
    assert data["width"] == 256
    assert data["height"] == 256
    assert data["file_format"] == "JPEG"

    # Fetch metadata
    image_id = data["image_id"]
    meta_res = client.get(f"/api/v1/images/{image_id}", headers=user_auth_headers)
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert meta["image_id"] == image_id
    assert meta["content_sha256"] == data["content_sha256"]


def test_image_upload_unauthorized(client, sample_jpeg_bytes):
    """Protected endpoints reject requests without a valid token (401 AUTH_TOKEN_INVALID)."""
    files = {"file": ("test_sample.jpg", sample_jpeg_bytes, "image/jpeg")}
    res = client.post("/api/v1/images", files=files)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_image_access_isolation_other_user(client, user_auth_headers, sample_jpeg_bytes, db_session):
    """PRD §6.3: Fetching another user's image returns 404 IMG_NOT_FOUND (not 403) to prevent enumeration."""
    # User 1 uploads an image
    files = {"file": ("user1.jpg", sample_jpeg_bytes, "image/jpeg")}
    res = client.post("/api/v1/images", headers=user_auth_headers, files=files)
    image_id = res.json()["image_id"]

    # User 2 logs in
    user2 = User(
        full_name="User Two",
        email="user2@nitk.edu.in",
        password_hash=hash_password("Pass123456789!"),
        role="User",
        account_status="active",
        is_email_verified=True,
    )
    db_session.add(user2)
    db_session.commit()
    token2, _, _ = create_session_token(user2)
    user2_headers = {"Authorization": f"Bearer {token2}"}

    # User 2 tries to fetch User 1's image
    get_res = client.get(f"/api/v1/images/{image_id}", headers=user2_headers)
    assert get_res.status_code == 404
    assert get_res.json()["error"]["code"] == "IMG_NOT_FOUND"


def test_invalid_upload_returns_error_envelope(client, user_auth_headers):
    """Corrupted / non-image upload returns standard error envelope (PRD §3.4)."""
    bad_bytes = b"NotAnImageContent12345"
    files = {"file": ("fake.png", bad_bytes, "image/png")}
    res = client.post("/api/v1/images", headers=user_auth_headers, files=files)

    assert res.status_code == 415
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "IMG_FORMAT_UNSUPPORTED"
    assert "request_id" in data["error"]
