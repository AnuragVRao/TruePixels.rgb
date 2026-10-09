# HTTPS with Caddy (Phase 6)

```
browser ──HTTPS──▶ Caddy (container) ──HTTP──▶ uvicorn on the HOST, 127.0.0.1:8000
                    │  serves frontend/dist        (not containerised: it needs the GPU)
                    └─ sets CSP + security headers
```

- **The API is not containerised.** It runs on the host, bound to
  `127.0.0.1`, so nothing on the network can reach it directly.
- **Caddy runs in Docker** and reaches the API through
  `host.docker.internal`. This was measured on 2026-10-05: a container got
  `200 OK` from uvicorn bound to `127.0.0.1`, so the fallback (running Caddy
  natively on Windows) is not needed.
- **PostgreSQL** stays on `127.0.0.1:5433`.

## Why the API does not trust forwarded headers by IP

Docker Desktop relays the container's connection through the host loopback,
so uvicorn sees **every** proxied request as coming from `127.0.0.1`
(measured). Trusting `X-Forwarded-For` "from the proxy address" would
therefore trust **any local process**, which could then forge its client IP
and dodge the per-IP sign-in throttle.

Instead:

- **uvicorn runs with `--no-proxy-headers`**, so it trusts no address.
- **Caddy sends a shared secret** on every proxied request, in the
  `X-TruePixels-Proxy` header, overwriting any copy a client sent. It also
  *replaces* `X-Forwarded-For` with the real peer address, which is its
  default.
- **The API trusts the forwarded headers only with that secret.**
  `app/shared/proxy.py` checks `X-TruePixels-Proxy` against
  `PROXY_SHARED_SECRET` in constant time.
  - On a match, it uses the forwarded client and scheme.
  - Otherwise it **strips** every `X-Forwarded-*` header.
  - The secret header itself never reaches the app.

**Tested.** Unit tests in `backend/tests/test_proxy_trust.py`, and live
checks in `infra/check_https.py`:
- a spoofed `X-Forwarded-For` sent directly to uvicorn is ignored;
- so is a forged secret;
- a client's own `X-Forwarded-For` sent through Caddy is replaced;
- positive control: with the real secret, the forwarded address *is* used.

`PROXY_SHARED_SECRET` lives in `backend/.env` (gitignored) and is passed to
the Caddy container. Anyone who can run `docker inspect` on that container
can read it. Anyone who has it can only forge a client IP, and only from
this machine, since uvicorn listens on `127.0.0.1` alone.

## Run the API

From `backend/`:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --workers 1
```

- **One worker, on purpose.** Each worker would load its own copy of both
  models (about 3.4 GB of VRAM), and the sign-in throttle state is
  per-process.
- **`ENVIRONMENT` defaults to production.** Only an explicit
  `ENVIRONMENT=development` enables:
  - `/docs`, `/redoc` and `/openapi.json`;
  - console delivery of OTP codes;
  - the plain-HTTP CORS defaults.

## Profiles

Every `docker compose` command takes `--env-file backend/.env`.

| | `https-dev` | `https-prod` |
|---|---|---|
| Start | `docker compose --env-file backend/.env --profile https-dev up -d caddy-dev` | `docker compose --env-file backend/.env --profile https-prod up -d caddy-prod` |
| Site | `https://localhost` | `TP_SITE_ADDRESS` (default `localhost`) |
| Certificate | Caddy's local CA (`tls internal`) | `TP_TLS`: `internal`, or an e-mail address for ACME |
| Listens on | `127.0.0.1:80` and `:443` only | all interfaces, 80 and 443 |
| HSTS | **no** (it would pin every local project on `localhost` to HTTPS) | `max-age=31536000; includeSubDomains` |
| API | `ENVIRONMENT=development` | `ENVIRONMENT=production` (the default) |

Run one profile at a time: both use ports 80 and 443.

- **Busy ports.** If 80/443 are taken, set `TP_HTTP_PORT=8080` and
  `TP_HTTPS_PORT=8443`. Caddy then binds and redirects to those ports
  (`http_port`/`https_port`). On 2026-10-05, 80, 443, 8080 and 8443 were all
  free.
- **Another API port.** `TP_UPSTREAM=host.docker.internal:8001` points Caddy
  at an API on a different port; the Phase 6 checks used this.

**What Caddy does** (`infra/caddy/common.caddy`):

- redirects HTTP to HTTPS;
- serves the React build from `frontend/dist`, with SPA fallback, immutable
  caching for `/assets/*` and `no-cache` for `index.html`;
- proxies `/api/*`, `/health` and `/ready`;
- caps request bodies at **12 MB**, or **70 MB** under `/api/v1/models`. The
  app's own caps are 10 MB for images and 64 MB for SPAI heads, and the app
  still enforces its exact limits;
- allows 180 s to read, write and wait for the response header (at least
  60 s was required);
- sends these headers on every response:
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; media-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `X-Frame-Options: DENY`
  - `Permissions-Policy` with camera, microphone, geolocation, payment and USB off
  - `Cross-Origin-Opener-Policy: same-origin`
  - and no `Server` header.

**Why the CSP looks the way it does:**

- **Scripts:** never `unsafe-inline` or `unsafe-eval`.
- **Styles:** `style-src-attr 'unsafe-inline'` allows inline style
  *attributes* only, which recharts and React's `style={...}` need. Inline
  `<style>` elements are not allowed.
- **Fonts:** bundled with `@fontsource`, not loaded from Google Fonts.
  `vite.config.ts` sets `assetsInlineLimit: 0` because Vite otherwise
  inlines small font files as `data:` URIs, which `font-src 'self'` blocks.
  The first HTTPS browser run caught exactly that.
- **Images:** `blob:` because results, thumbnails, panels and PDFs are
  fetched with the Authorization header and shown as blob URLs.

**In production `/docs` is off.** (M3's legacy static dashboard, once served
in development at `/` and `/api-tester`, was removed on 2026-10-10.)

**CORS.** The React app is same-origin, both behind Caddy and behind Vite's
dev proxy, so it needs none.
- In production the default allow-list is **empty**.
- Set `TRUEPIXELS_CORS_ORIGINS=https://your.host` only for a genuine
  cross-origin caller.
- A foreign origin gets no `Access-Control-Allow-Origin` header (tested).

## Trusting the local CA, on this machine only

`tls internal` makes Caddy create its own certificate authority. The root
certificate is public; its **private key** is in
`infra/caddy/data/<profile>/caddy/pki/authorities/local/`. That directory is
**gitignored**: never commit it, copy it or share it. Anyone holding that key
can issue certificates your browser would trust.

To stop the browser warning, trust the root in the **current user's** store.
This needs no admin rights, and Windows shows a confirmation dialog:

```powershell
certutil -user -addstore Root infra\caddy\data\dev\caddy\pki\authorities\local\root.crt
```

- **Remove the trust:**

  ```powershell
  certutil -user -delstore Root "Caddy Local Authority - 2026 ECC Root"
  ```

  The exact name is in `certutil -user -store Root | findstr Caddy`.
- **Never** add it to the machine-wide store, and never on another machine.
- Deleting `infra/caddy/data/dev` makes Caddy create a **new** CA. Trust the
  new one and remove the old one.
- **Windows `curl`** (schannel) also needs `--ssl-no-revoke` for a local CA:
  it cannot check revocation for it.

## Real certificate (ACME)

1. A DNS name that resolves to this machine, with ports 80 and 443
   reachable from the internet. Port 80 is needed for the HTTP-01
   challenge.
2. In `backend/.env`, or the shell, set:
   - `TP_SITE_ADDRESS=truepixels.example.com`
   - `TP_TLS=you@example.com` (an e-mail address switches Caddy from its
     local CA to Let's Encrypt)
   - `TRUEPIXELS_CORS_ORIGINS`, only if needed.
3. Start the API with `ENVIRONMENT=production`, then
   `docker compose --env-file backend/.env --profile https-prod up -d caddy-prod`.

Certificates and account keys are kept in `infra/caddy/data/prod`
(gitignored).

## Verifying

```powershell
python infra/check_https.py --profile dev --api http://127.0.0.1:8000
```

- **TLS is verified** against Caddy's own root certificate; nothing in this
  script ignores certificate errors.
- **The body-size checks** read a session token for a *scratch* user from
  `TP_TEST_TOKEN`.

The Playwright suites run through HTTPS with `TP_BASE=https://localhost`.
They **ignore certificate errors**, because the browser does not trust the
local CA, and they **fail on any CSP or mixed-content console message**
(`frontend/e2e/csp_guard.py`).
