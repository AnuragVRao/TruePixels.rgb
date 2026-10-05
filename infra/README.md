# Infrastructure

| Path | Contents |
|---|---|
| `caddy/common.caddy` | Shared by both profiles: proxy to the API on the host (with the shared secret), the CSP and security headers, body limits, timeouts, and serving the React build |
| `caddy/Caddyfile.dev` | `https://localhost` with Caddy's local CA, and no HSTS |
| `caddy/Caddyfile.prod` | `TP_SITE_ADDRESS`, a local CA or ACME (`TP_TLS`), and HSTS |
| `check_https.py` | Live acceptance checks: redirect, headers, CORS, spoofing, body limits |

The services themselves are defined in `../compose.yaml`: `db`, `caddy-dev`
and `caddy-prod`. `caddy/data/` and `caddy/config/` are created at run time.
They hold the local CA's **private key** and are gitignored.

Background: [docs/https.md](../docs/https.md).
