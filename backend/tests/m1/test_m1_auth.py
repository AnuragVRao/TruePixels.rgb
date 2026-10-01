"""Unit and integration tests for Authentication and Access Control (SRS F.1 - F.4, F.17)."""
import time
import pytest
from app.m1_access.models import User
from app.m1_access.security import (
    hash_password,
    verify_password,
    validate_password_strength,
)


def test_password_policy():
    """AC3: Enforce password length, complexity, and common password restrictions."""
    # Too short
    with pytest.raises(ValueError, match="at least 10 characters"):
        validate_password_strength("Short1")

    # No digits
    with pytest.raises(ValueError, match="at least one digit"):
        validate_password_strength("NoDigitsHere")

    # No letters
    with pytest.raises(ValueError, match="at least one letter"):
        validate_password_strength("1234567890123")

    # Blacklisted common password
    with pytest.raises(ValueError, match="too common"):
        validate_password_strength("1234567890")

    # Valid password
    validate_password_strength("SuperSecret999!")


def test_hash_roundtrip():
    """Hash round-trip verification."""
    raw = "MyStrongPassword123"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword123", hashed) is False


def test_user_registration_success(client):
    """US-1.1 AC1: Successful user registration creates User record with role 'User'."""
    res = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test User",
            "email": "user@example.com",
            "password": "ValidPassword123!",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert "user_id" in data
    assert data["message"] == "Account created successfully."


def test_user_registration_duplicate_email(client, sample_user):
    """US-1.1 AC2: Case-insensitive email uniqueness check returns AUTH_EMAIL_TAKEN (409)."""
    res = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Duplicate User",
            "email": "AMOGH@nitk.edu.in",  # Different casing
            "password": "ValidPassword123!",
        },
    )
    assert res.status_code == 409
    data = res.json()
    assert data["error"]["code"] == "AUTH_EMAIL_TAKEN"


def test_login_success(client, sample_user):
    """US-1.2 AC1: Login with valid credentials returns session token."""
    res = client.post(
        "/api/v1/auth/login",
        json={
            "email": "amogh@nitk.edu.in",
            "password": "SecretPassword123",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["role"] == "User"
    assert data["user_id"] == sample_user.user_id


def test_login_invalid_credentials_identical_response(client, sample_user):
    """US-1.2 AC2: Wrong password vs Non-existent email return identical error code & message."""
    # Case 1: Wrong password for existing user
    res1 = client.post(
        "/api/v1/auth/login",
        json={
            "email": "amogh@nitk.edu.in",
            "password": "WrongPassword999",
        },
    )
    assert res1.status_code == 401
    err1 = res1.json()["error"]
    assert err1["code"] == "AUTH_INVALID_CREDENTIALS"

    # Case 2: Non-existent email
    res2 = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@nitk.edu.in",
            "password": "WrongPassword999",
        },
    )
    assert res2.status_code == 401
    err2 = res2.json()["error"]
    assert err2["code"] == "AUTH_INVALID_CREDENTIALS"
    assert err1["message"] == err2["message"]


def test_admin_login_with_user_credentials_forbidden(client, sample_user):
    """US-1.3 AC2: Non-admin trying admin login returns 403 AUTH_FORBIDDEN."""
    res = client.post(
        "/api/v1/auth/admin/login",
        json={
            "email": "amogh@nitk.edu.in",
            "password": "SecretPassword123",
        },
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AUTH_FORBIDDEN"


def test_admin_login_success(client, sample_admin):
    """US-1.3 AC1: Admin login returns elevated admin session."""
    res = client.post(
        "/api/v1/auth/admin/login",
        json={
            "email": "admin@truepixels.rgb",
            "password": "AdminSecurePassword123",
        },
    )
    assert res.status_code == 200
    assert res.json()["role"] == "Admin"


def test_auth_me_endpoint(client, user_auth_headers, sample_user):
    """Contract C3: /api/v1/auth/me returns SessionContext."""
    res = client.get("/api/v1/auth/me", headers=user_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == sample_user.user_id
    assert data["email"] == sample_user.email
    assert data["role"] == "User"


def test_admin_update_user_status(client, admin_auth_headers, sample_user):
    """US-3.5 / F.17 write half: Admin updates user status."""
    res = client.patch(
        f"/api/v1/users/{sample_user.user_id}/status",
        headers=admin_auth_headers,
        json={"action": "disable"},
    )
    assert res.status_code == 200
    assert res.json()["account_status"] == "disabled"

    # User should now be blocked from logging in
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": sample_user.email, "password": "SecretPassword123"},
    )
    assert login_res.status_code == 403
    assert login_res.json()["error"]["code"] == "AUTH_ACCOUNT_DISABLED"


def test_admin_cannot_alter_own_status(client, admin_auth_headers, sample_admin):
    """PRD §5.1.5: Self-modification guard prevents admin disabling their own account."""
    res = client.patch(
        f"/api/v1/users/{sample_admin.user_id}/status",
        headers=admin_auth_headers,
        json={"action": "disable"},
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ADM_ACTION_NOT_PERMITTED"


def test_otp_send_and_verify_flow(client, sample_user, db_session):
    """2FA Enhancement: Send OTP and verify code."""
    # 1. Request OTP
    send_res = client.post("/api/v1/auth/otp/send", json={"email": sample_user.email})
    assert send_res.status_code == 200

    # Retrieve active user from DB to simulate reading delivered email OTP
    user_in_db = db_session.query(User).filter(User.email == sample_user.email).first()
    assert user_in_db.otp_hash is not None

    # Test invalid OTP
    bad_res = client.post("/api/v1/auth/otp/verify", json={"email": sample_user.email, "otp": "000000"})
    assert bad_res.status_code == 401
    assert bad_res.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"

    # For valid OTP, let's verify with matching OTP
    from app.m1_access.security import create_otp_hash
    test_otp = "123456"
    user_in_db.otp_hash = create_otp_hash(test_otp)
    db_session.commit()

    good_res = client.post("/api/v1/auth/otp/verify", json={"email": sample_user.email, "otp": test_otp})
    assert good_res.status_code == 200
    assert "token" in good_res.json()
    assert good_res.json()["user_id"] == sample_user.user_id

