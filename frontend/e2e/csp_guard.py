"""Shared by the Playwright suites (Phase 6): base URL, HTTPS, CSP watch.

TP_BASE selects where the suites run: the Vite dev server (default,
http://localhost:3000) or the Caddy HTTPS front (https://localhost). Over
HTTPS the browser contexts IGNORE CERTIFICATE ERRORS (the certificate comes
from Caddy's local CA, which this machine's browser does not trust by
default) - every report of an HTTPS run must say so.

Every context gets a listener for `securitypolicyviolation` events, and every
page's console is watched for CSP refusals and mixed-content warnings. The
suites FAIL if any were seen (`violations`).
"""

from __future__ import annotations

import os

BASE = os.environ.get("TP_BASE", "http://localhost:3000").rstrip("/")
API = f"{BASE}/api/v1"
HTTPS = BASE.startswith("https://")
violations: list[str] = []

_INIT = """
document.addEventListener('securitypolicyviolation', (e) => {
  console.error('CSP-VIOLATION directive=' + e.violatedDirective + ' blocked=' + e.blockedURI +
                ' source=' + e.sourceFile + ':' + e.lineNumber + ' sample=' + (e.sample || ''));
});
"""
_MARKERS = ("CSP-VIOLATION", "Content Security Policy", "Refused to", "Mixed Content")


def _watch(page) -> None:
    page.on("console", lambda m: violations.append(f"{page.url} :: {m.text[:240]}")
            if any(marker in m.text for marker in _MARKERS) else None)


def install(browser) -> None:
    """Wrap browser.new_context so every context and page is guarded."""
    original = browser.new_context

    def new_context(**kwargs):
        if HTTPS:
            kwargs.setdefault("ignore_https_errors", True)
        context = original(**kwargs)
        context.add_init_script(_INIT)
        context.on("page", _watch)
        return context

    browser.new_context = new_context


def summary() -> tuple[str, bool]:
    mode = (f"{BASE} (HTTPS; certificate errors IGNORED for this run)" if HTTPS else f"{BASE} (plain HTTP dev server)")
    return f"base {mode}; CSP / mixed-content violations: {len(violations)}", not violations
