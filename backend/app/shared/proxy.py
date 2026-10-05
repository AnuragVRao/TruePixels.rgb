"""Which client address and scheme a request really came from (Phase 6).

Behind Caddy, every request reaches uvicorn from 127.0.0.1: Docker Desktop
relays the container's connection through the host loopback (measured
2026-10-05: uvicorn logged ``127.0.0.1`` for a request from a container via
host.docker.internal). Trusting X-Forwarded-For "from the proxy address"
would therefore trust ANY local process, which could then forge its client
IP and walk around the per-IP sign-in throttle.

So uvicorn runs with ``--no-proxy-headers`` (it trusts no address), and this
middleware trusts the forwarded headers only when the request carries the
proxy's shared secret, ``PROXY_SHARED_SECRET`` from backend/.env, which only
Caddy knows (it sets the header on every proxied request and overwrites any
client-supplied copy). Compared in constant time. Without a matching secret:

* X-Forwarded-For / X-Forwarded-Proto / X-Forwarded-Host are REMOVED, so
  nothing downstream can read a forged value;
* the client address stays the real TCP peer.

With it, the client address becomes the one Caddy recorded (Caddy replaces
any incoming X-Forwarded-For with the real peer, since it trusts no proxy in
front of it) and the scheme becomes the forwarded one. The secret header
itself is always removed before the app sees the request.
"""

from __future__ import annotations

import hmac
import ipaddress
import os

SECRET_HEADER = b"x-truepixels-proxy"
FORWARDED = (b"x-forwarded-for", b"x-forwarded-proto", b"x-forwarded-host")


class TrustedProxyMiddleware:
    def __init__(self, app, secret: str | None = None):
        self.app = app
        value = secret if secret is not None else os.getenv("PROXY_SHARED_SECRET", "")
        self.secret = value.strip().encode() if value and value.strip() else None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        presented = next((v for k, v in headers if k == SECRET_HEADER), None)
        trusted = (self.secret is not None and presented is not None
                   and hmac.compare_digest(presented.strip(), self.secret))
        scope = dict(scope)
        if trusted:
            values = {k.decode("latin-1"): v.decode("latin-1") for k, v in headers if k in FORWARDED}
            client = values.get("x-forwarded-for", "").split(",")[-1].strip()
            if client:
                try:
                    ipaddress.ip_address(client)
                    scope["client"] = (client, 0)
                except ValueError:
                    pass  # not an address: keep the TCP peer
            proto = values.get("x-forwarded-proto", "").strip().lower()
            if proto in ("http", "https"):
                scope["scheme"] = "https" if proto == "https" else "http"
        scope["headers"] = [(k, v) for k, v in headers
                            if k != SECRET_HEADER and (trusted or k not in FORWARDED)]
        return await self.app(scope, receive, send)
