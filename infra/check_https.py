"""Phase 6 acceptance checks against a RUNNING Caddy + API. Prints PASS/FAIL lines.

    python infra/check_https.py --profile dev  --api http://127.0.0.1:8000
    python infra/check_https.py --profile prod --api http://127.0.0.1:8000

TLS is VERIFIED against Caddy's own local root certificate
(infra/caddy/data/<profile>/caddy/pki/authorities/local/root.crt) - nothing
here ignores certificate errors. --api is the uvicorn address on the host, for
the direct-client (spoofing) checks. Reads PROXY_SHARED_SECRET from
backend/.env for the positive control and never prints it.

Checks: HTTP -> HTTPS redirect; CSP and security headers on HTML, assets, API
JSON and API errors; HSTS only in prod; CORS (foreign origin gets no allow
header); X-Forwarded-For spoofing (direct, through Caddy, forged secret
header); body-size limits; no http:// references in the built page; prod hides
/docs, /openapi.json and the legacy dashboard.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
SITE = "https://localhost"
EXPECTED_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; "
                "img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; media-src 'none'; "
                "object-src 'none'; frame-src 'none'; worker-src 'none'; base-uri 'self'; "
                "form-action 'self'; frame-ancestors 'none'")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def secret() -> str:
    from dotenv import dotenv_values

    return dotenv_values(REPO / "backend" / ".env").get("PROXY_SHARED_SECRET") or ""


def burn(client: httpx.Client, url: str, email: str, n: int, headers: dict | None = None) -> list[int]:
    return [client.post(url, json={"email": email, "password": "Wrong-password-1"}, headers=headers or {}).status_code
            for _ in range(n)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["dev", "prod"], required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--allowed-origin", default=None,
                        help="an origin TRUEPIXELS_CORS_ORIGINS allows (prod run), checked to get the header")
    args = parser.parse_args()
    root = REPO / "infra" / "caddy" / "data" / args.profile / "caddy" / "pki" / "authorities" / "local" / "root.crt"
    if not root.is_file():
        print(f"FAIL local root certificate not found: {root}")
        return 2
    tls = httpx.Client(verify=str(root), timeout=30, follow_redirects=False)
    plain = httpx.Client(timeout=30, follow_redirects=False)
    direct = httpx.Client(timeout=30)

    # --- redirect ----------------------------------------------------------------
    for path in ("/", "/history", "/api/v1/health?x=1"):
        r = plain.get(f"http://localhost{path}")
        check(f"HTTP->HTTPS redirect {path}", r.status_code in (301, 308)
              and r.headers.get("location") == f"https://localhost{path}", f"{r.status_code} {r.headers.get('location')}")

    # --- TLS + headers on live responses ----------------------------------------------
    index = tls.get(f"{SITE}/")
    check("TLS verified against Caddy's local root; index 200", index.status_code == 200)
    asset = re.search(r'src="(/assets/[^"]+\.js)"', index.text)
    responses = {"index.html": index,
                 "JS asset": tls.get(SITE + asset.group(1)) if asset else None,
                 "SPA route /history": tls.get(f"{SITE}/history"),
                 "API JSON /api/v1/health": tls.get(f"{SITE}/api/v1/health"),
                 "API error /api/v1/history (401)": tls.get(f"{SITE}/api/v1/history"),
                 "probe /ready": tls.get(f"{SITE}/ready")}
    for name, r in responses.items():
        if r is None:
            check(f"{name}: present", False)
            continue
        h = r.headers
        check(f"{name}: CSP exact", h.get("content-security-policy") == EXPECTED_CSP, h.get("content-security-policy", "")[:60])
        check(f"{name}: nosniff / no-referrer / DENY", h.get("x-content-type-options") == "nosniff"
              and h.get("referrer-policy") == "no-referrer" and h.get("x-frame-options") == "DENY")
        check(f"{name}: no Server header", "server" not in h, h.get("server", ""))
        hsts = h.get("strict-transport-security")
        if args.profile == "prod":
            check(f"{name}: HSTS present (prod)", hsts == "max-age=31536000; includeSubDomains", str(hsts))
        else:
            check(f"{name}: no HSTS (dev)", hsts is None, str(hsts))
    check("API error is the app's JSON envelope", responses["API error /api/v1/history (401)"].status_code == 401
          and responses["API error /api/v1/history (401)"].json()["error"]["code"] == "AUTH_TOKEN_INVALID")

    # --- no mixed content in the built page ----------------------------------------
    refs = re.findall(r'(?:src|href)="([^"]+)"', index.text)
    check("index.html references only same-origin/relative URLs", all(not re.match(r"^(https?:)?//", u) for u in refs), str(refs))

    # --- CORS -------------------------------------------------------------------------
    for origin in ("https://evil.example", "http://localhost", "null"):
        pre = tls.options(f"{SITE}/api/v1/history", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                                              "Access-Control-Request-Headers": "authorization"})
        get = tls.get(f"{SITE}/api/v1/health", headers={"Origin": origin})
        check(f"CORS: foreign origin {origin} gets no allow header",
              "access-control-allow-origin" not in pre.headers and "access-control-allow-origin" not in get.headers)
    if args.allowed_origin:
        pre = tls.options(f"{SITE}/api/v1/history", headers={"Origin": args.allowed_origin,
                                                              "Access-Control-Request-Method": "GET"})
        check(f"CORS: configured origin {args.allowed_origin} is allowed",
              pre.headers.get("access-control-allow-origin") == args.allowed_origin)

    # --- X-Forwarded-For spoofing --------------------------------------------------------
    # Black-box: the sign-in throttle keys on the client address. 3 failures are
    # free per (email, address); the 4th sets a wait. If a forged XFF were
    # believed, changing it would give a fresh key (401); if it is ignored, the
    # next attempt is throttled (429).
    login_direct = f"{args.api}/api/v1/auth/login"
    login_proxied = f"{SITE}/api/v1/auth/login"
    e1 = f"xff-direct-{uuid.uuid4().hex[:8]}@example.com"
    burn(direct, login_direct, e1, 4, {"X-Forwarded-For": "203.0.113.1"})
    r = direct.post(login_direct, json={"email": e1, "password": "x"}, headers={"X-Forwarded-For": "203.0.113.2"})
    check("spoofed X-Forwarded-For from a direct client is ignored (429, same key)", r.status_code == 429, str(r.status_code))
    e2 = f"xff-forged-secret-{uuid.uuid4().hex[:8]}@example.com"
    burn(direct, login_direct, e2, 4, {"X-Forwarded-For": "203.0.113.3", "X-TruePixels-Proxy": "guess"})
    r = direct.post(login_direct, json={"email": e2, "password": "x"},
                    headers={"X-Forwarded-For": "203.0.113.4", "X-TruePixels-Proxy": "guess"})
    check("direct client with a forged proxy secret is ignored (429)", r.status_code == 429, str(r.status_code))
    e3 = f"xff-via-caddy-{uuid.uuid4().hex[:8]}@example.com"
    burn(tls, login_proxied, e3, 4, {"X-Forwarded-For": "203.0.113.5", "X-TruePixels-Proxy": "guess"})
    r = tls.post(login_proxied, json={"email": e3, "password": "x"}, headers={"X-Forwarded-For": "203.0.113.6"})
    check("client X-Forwarded-For through Caddy is replaced by the real peer (429)", r.status_code == 429, str(r.status_code))
    shared = secret()
    e4 = f"xff-control-{uuid.uuid4().hex[:8]}@example.com"
    burn(direct, login_direct, e4, 4, {"X-Forwarded-For": "203.0.113.7", "X-TruePixels-Proxy": shared})
    r = direct.post(login_direct, json={"email": e4, "password": "x"},
                    headers={"X-Forwarded-For": "203.0.113.8", "X-TruePixels-Proxy": shared})
    check("control: WITH the real secret the forwarded address is used (fresh key, 401)",
          bool(shared) and r.status_code == 401, str(r.status_code))
    del shared

    # --- body limits ------------------------------------------------------------------------
    # Authenticated, so the app really reads the body (unauthenticated requests
    # are answered 401 before any body is read, and the limit never triggers).
    # TP_TEST_TOKEN: a session token for a scratch user, from the environment.
    import io
    import os

    token = os.environ.get("TP_TEST_TOKEN", "")
    auth = {"Authorization": f"Bearer {token}"} if token else {}
    check("test token supplied (TP_TEST_TOKEN)", bool(token))

    def upload(megabytes: float):
        body = io.BytesIO(b"PNG-not-really" + bytes(int(megabytes * 1024 * 1024)))
        try:
            return tls.post(f"{SITE}/api/v1/images", headers=auth, files={"file": ("big.png", body, "image/png")})
        except httpx.HTTPError as exc:
            return exc

    over = upload(13)
    over_ok = (isinstance(over, httpx.Response) and over.status_code == 413
               and "error" not in (over.text or "")) or isinstance(over, httpx.HTTPError)
    check("13 MB upload stopped by Caddy (413 or connection closed, never the app's JSON)", over_ok,
          type(over).__name__ if not isinstance(over, httpx.Response) else f"{over.status_code} {over.text[:80]}")
    under = upload(11)
    check("11 MB upload passes Caddy; the app refuses it (413 IMG_TOO_LARGE JSON)",
          isinstance(under, httpx.Response) and under.status_code == 413
          and under.json().get("error", {}).get("code") == "IMG_TOO_LARGE",
          f"{getattr(under, 'status_code', under)} {getattr(under, 'text', '')[:80]}")
    small = tls.get(f"{SITE}/api/v1/history", headers=auth)
    check("authenticated request through Caddy works (200)", small.status_code == 200, str(small.status_code))

    # --- production hides the dev surface ------------------------------------------------------
    for path in ("/docs", "/redoc", "/openapi.json", "/", "/api-tester"):
        r = direct.get(f"{args.api}{path}")
        if args.profile == "prod":
            check(f"prod API: {path} not served (404)", r.status_code == 404, str(r.status_code))
        else:
            check(f"dev API: {path} served (200)", r.status_code == 200, str(r.status_code))

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {'' if ok else detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"{len(results) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
