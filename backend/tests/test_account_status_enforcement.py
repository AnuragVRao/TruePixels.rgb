"""Disabling or removing an account takes effect on the very next request.

Tokens come from the real login endpoint (not minted in the test). The
session dependency re-reads account_status from D1 on every request
(m1_access.security.verify_session_token), so an already-issued token stops
working as soon as an admin changes the status - not at its 8 h expiry.

Also: re-registering the email of a removed (or disabled) account answers
exactly like any other taken email, so registration does not reveal that a
removed account exists.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from app.main import app
from conftest import make_image, png_bytes
from test_admin_policy import make_user

client = TestClient(app)
_n = itertools.count()
PASSWORD = "StatusTest12345"


def register_and_login() -> tuple[int, str, dict[str, str]]:
    email = f"status-{next(_n)}@example.com"
    r = client.post("/api/v1/auth/register", json={"full_name": "Status Test", "email": email, "password": PASSWORD})
    assert r.status_code in (200, 201), r.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200 and not login.json()["requires_otp"], login.text
    return r.json()["user_id"], email, {"Authorization": f"Bearer {login.json()['token']}"}


def requests_with(headers):
    upload = {"files": {"file": ("x.png", png_bytes(make_image(seed=3)), "image/png")}}
    return [
        client.get("/api/v1/auth/me", headers=headers),
        client.get("/api/v1/history", headers=headers),
        client.post("/api/v1/images", headers=headers, **upload),
    ]


@pytest.mark.parametrize("action,status", [("disable", "disabled"), ("remove", "removed")])
@pytest.mark.parametrize("endpoint", ["/api/v1/admin/users/{id}/status", "/api/v1/users/{id}/status"])
def test_status_change_invalidates_an_existing_token_immediately(action, status, endpoint):
    _, admin = make_user("Admin")
    user_id, email, headers = register_and_login()
    assert [r.status_code for r in requests_with(headers)] == [200, 200, 201]

    r = client.patch(endpoint.format(id=user_id), headers=admin, json={"action": action})
    assert r.status_code == 200 and r.json()["account_status"] == status

    for response in requests_with(headers):  # the SAME token, next request
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "AUTH_ACCOUNT_DISABLED"
    relogin = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert relogin.status_code == 403 and relogin.json()["error"]["code"] == "AUTH_ACCOUNT_DISABLED"

    client.patch(endpoint.format(id=user_id), headers=admin, json={"action": "enable"})
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200  # restored, nothing lost


@pytest.mark.parametrize("action", [None, "disable", "remove"])
def test_reregistering_a_taken_email_does_not_reveal_the_account_status(action):
    _, admin = make_user("Admin")
    user_id, email, _ = register_and_login()
    if action:
        client.patch(f"/api/v1/admin/users/{user_id}/status", headers=admin, json={"action": action})
    r = client.post("/api/v1/auth/register",
                    json={"full_name": "Someone Else", "email": email.upper(), "password": "Another12345"})
    assert r.status_code == 409, r.text
    error = r.json()["error"]
    # Identical for active, disabled and removed accounts.
    assert error["code"] == "AUTH_EMAIL_TAKEN"
    assert error["message"] == "An account with this email address already exists."
    assert "removed" not in r.text.lower() and "disabled" not in r.text.lower()
