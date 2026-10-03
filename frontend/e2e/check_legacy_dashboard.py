"""Headless-Chromium check of the legacy static dashboard's Phase 5b fixes.

    DATABASE_URL=<scratch> python frontend/e2e/seed_admin_scratch.py <out>/seed.json   # fresh payload row
    python frontend/e2e/check_legacy_dashboard.py <out_dir> <backend_log>

Backend on :8000 as for run_admin_flows.py. Checks, in the dashboard served at
/: the log table shows the seeded HTML payload as text without executing it,
no "CLIP" or "100% Operational" text, and the error tile shows the API's
figures. In /api-tester: "Run All" reports failures instead of always PASS.
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(sys.argv[1])
LOG = Path(sys.argv[2])
SEED = json.loads((OUT / "seed.json").read_text())
email = SEED["admin"]["email"]

mark = len(LOG.read_text(encoding="utf-8", errors="ignore"))
r = httpx.post(f"{BASE}/api/v1/auth/admin/login", json={"email": email, "password": SEED["password"]})
r.raise_for_status()
token = r.json().get("token")
if r.json().get("requires_otp"):
    code = None
    for _ in range(40):
        found = re.findall(rf"for {re.escape(email)}: code=(\d{{6}})",
                           LOG.read_text(encoding="utf-8", errors="ignore")[mark:])
        if found:
            code = found[-1]
            break
        time.sleep(0.5)
    token = httpx.post(f"{BASE}/api/v1/auth/otp/verify", json={"email": email, "otp": code}).json()["token"]
summary = httpx.get(f"{BASE}/api/v1/admin/summary", headers={"Authorization": f"Bearer {token}"}).json()

results = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/")
    page.evaluate("s => sessionStorage.setItem('tp_session', s)",
                  json.dumps({"token": token, "name": "E2E admin", "role": "Admin"}))
    page.reload()
    page.click("#tab-admin")
    expect(page.locator("#logsTableBody tr").first).to_be_visible(timeout=30000)
    body = page.locator("#logsTableBody").inner_text()
    results.append(("payload rendered as text", SEED["xss"] in body))
    results.append(("payload did not execute", page.evaluate("window.__xss") is None))
    results.append(("no img/script in log table", page.locator("#logsTableBody img, #logsTableBody script").count() == 0))
    expect(page.locator("#tileErrors")).not_to_have_text("n/a", timeout=30000)
    results.append(("error tile = API", page.locator("#tileErrors").inner_text().strip()
                     == f"{summary['error_count_last_24h']} errors · {len(summary['active_models'])} active models"))
    html = page.content()
    results.append(("no 'CLIP' label", "CLIP" not in html))
    results.append(("no hard-coded health", "100% Operational" not in html))

    page.goto(BASE + "/api-tester")
    page.evaluate("t => { try { localStorage.setItem('tp_token', t); sessionStorage.setItem('tp_token', t); } catch (e) {} }", token)
    page.click("#btnBatchTest")
    expect(page.locator("#responseOutput")).to_contain_text("BATCH RUN COMPLETED", timeout=120000)
    out = page.locator("#responseOutput").inner_text()
    statuses = re.findall(r"\[STATUS (\d+)\][^\n]*?(PASS|FAIL)", out)
    # PASS only ever for 2xx or the isolation probe's 404; any other 4xx/5xx must be FAIL.
    honest = bool(statuses) and all(
        (s.startswith("2") or s == "404") if v == "PASS" else True for s, v in statuses) and all(
        v == "FAIL" for s, v in statuses if s[0] in "45" and s != "404")
    results.append(("api-tester verdicts follow status codes", honest))
    results.append(("api-tester summary counts", bool(re.search(r"COMPLETED: \d+ passed, \d+ failed", out))))
    print(out.splitlines()[-2:] if out else "")
    results.append(("no page errors", not errors))
    browser.close()

for name, ok in results:
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(ok for _, ok in results) else 1)
