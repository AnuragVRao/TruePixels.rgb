# Legacy static dashboard (M3)

**Demoted in Phase 5b (2026-10-03).** The React app in `frontend/src` is the
primary interface: it covers everything here plus user management, model
management, a filterable log explorer and warm-only latency charts. This
dashboard is still served at `/` and `/api-tester` for reference and quick
manual checks; new features are not added here.

Fixed when it was demoted (changes.md 6.11):

- the audit-log table put `event_detail` into `innerHTML` - an XSS sink, since
  log details quote user-supplied text. Every cell is now plain text, as is
  the API tester's endpoint list and its batch output;
- "CLIP" labels renamed: the semantic branch is SigLIP 2;
- the hard-coded "System Health 100% Operational" tile now shows the API's
  own error count (last 24 h) and number of active models;
- `api_tester.html`'s "Run All" printed PASS for any status code, 500s
  included. A request now passes only with its expected status, and the run
  reports its pass and fail counts. False descriptions of contract C3, the
  explainability payload and the PDF were corrected.
