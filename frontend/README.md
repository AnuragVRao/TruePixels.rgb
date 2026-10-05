# Frontend

The React 18 + TypeScript + Vite app. It is the primary interface. Run
commands are in the [repository README](../readme.md).

| Path | Contents |
|---|---|
| `src/pages/` | Landing page, sign-in, Administrator Portal, registration and OTP; Forensic Detection (upload and results); History; 1-Click Verification |
| `src/pages/admin/` | Admin Dashboard & Analytics: overview, logs, users, models |
| `src/components/` | Layout (tabs and header), feedback notices, authenticated images, confirmation dialog |
| `src/api/` | The fetch client (sessionStorage token, error mapping) and response types |
| `src/context/`, `src/hooks/` | Session state; loading files with the Authorization header as blob URLs |
| `e2e/` | Playwright suites. Run them against a scratch API only. |
| `m3_dashboard/` | M3's legacy static dashboard. The API serves it in development only. |

```powershell
npm run dev          # http://localhost:3000, /api proxied to :8000 (TP_API_TARGET overrides)
npm run typecheck; npm run lint; npm run build
```

There are no inline scripts and no `dangerouslySetInnerHTML`; ESLint enforces
the latter. Fonts are bundled, not loaded from Google Fonts, and no asset is
inlined as a `data:` URI. Together these let the production CSP stay at
`'self'`.
