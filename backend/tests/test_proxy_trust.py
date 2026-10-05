"""Forwarded headers are trusted only with the proxy's shared secret (Phase 6).

Behind Docker Desktop every proxied request reaches uvicorn from 127.0.0.1,
so trusting X-Forwarded-For by peer address would trust any local process.
"""

from __future__ import annotations

import asyncio

import pytest

from app.shared.proxy import TrustedProxyMiddleware


def run(secret, headers, client=("127.0.0.1", 5), scheme="http"):
    seen = {}

    async def inner(scope, receive, send):
        seen.update(client=scope["client"], scheme=scope["scheme"], headers=dict(scope["headers"]))

    scope = {"type": "http", "client": client, "scheme": scheme, "headers": headers}
    asyncio.run(TrustedProxyMiddleware(inner, secret=secret)(scope, None, None))
    return seen


XFF = (b"x-forwarded-for", b"198.18.0.9")
PROTO = (b"x-forwarded-proto", b"https")


def test_with_the_secret_the_forwarded_client_and_scheme_are_used():
    seen = run("s3cret", [XFF, PROTO, (b"x-truepixels-proxy", b"s3cret")])
    assert seen["client"] == ("198.18.0.9", 0) and seen["scheme"] == "https"
    assert b"x-truepixels-proxy" not in seen["headers"]  # never reaches the app


@pytest.mark.parametrize("presented", [None, b"wrong", b"s3cre", b"s3cret2", b""])
def test_without_the_right_secret_forwarded_headers_are_stripped(presented):
    headers = [XFF, PROTO, (b"x-forwarded-host", b"evil.example")]
    if presented is not None:
        headers.append((b"x-truepixels-proxy", presented))
    seen = run("s3cret", headers)
    assert seen["client"] == ("127.0.0.1", 5) and seen["scheme"] == "http"
    assert not {b"x-forwarded-for", b"x-forwarded-proto", b"x-forwarded-host", b"x-truepixels-proxy"} & set(seen["headers"])


@pytest.mark.parametrize("secret", [None, "", "   "])
def test_no_configured_secret_means_never_trusted(secret, monkeypatch):
    monkeypatch.delenv("PROXY_SHARED_SECRET", raising=False)
    seen = run(secret, [XFF, (b"x-truepixels-proxy", b"")])
    assert seen["client"] == ("127.0.0.1", 5)


def test_a_non_address_forwarded_value_keeps_the_peer():
    seen = run("s3cret", [(b"x-forwarded-for", b"not-an-ip"), (b"x-truepixels-proxy", b"s3cret")])
    assert seen["client"] == ("127.0.0.1", 5)


def test_the_last_hop_is_used_when_several_are_listed():
    seen = run("s3cret", [(b"x-forwarded-for", b"203.0.113.1, 198.18.0.10"), (b"x-truepixels-proxy", b"s3cret")])
    assert seen["client"] == ("198.18.0.10", 0)
