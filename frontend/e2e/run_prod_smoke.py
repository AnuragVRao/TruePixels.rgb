"""Production-profile browser smoke run (Phase 6). Scratch database only.

    TP_BASE=https://localhost python frontend/e2e/run_prod_smoke.py <out_dir>

API running with ENVIRONMENT=production and REQUIRE_2FA=False (production
never prints OTP codes, and this run has no SMTP), behind caddy-prod. Seed
first with seed_admin_scratch.py. Certificate errors are IGNORED (local CA);
any CSP / mixed-content console message fails the run (csp_guard).
"""
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csp_guard  # noqa: E402

BASE = csp_guard.BASE
OUT = Path(sys.argv[1])
SEED = json.loads((OUT / "seed.json").read_text())
results = []


def step(name, fn):
    try:
        fn()
        results.append((name, "PASS", ""))
    except Exception as exc:  # noqa: BLE001
        results.append((name, "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}"))


image = OUT / "prod_smoke.png"
Image.fromarray(np.random.default_rng(3).integers(0, 256, (512, 512, 3), dtype=np.uint8)).save(image)

with sync_playwright() as p:
    browser = p.chromium.launch()
    csp_guard.install(browser)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    documents = []
    page.on("response", lambda r: documents.append(r) if r.request.resource_type == "document" else None)

    def sign_in(email, admin):
        if admin:
            page.goto(f"{BASE}/admin/login")
            page.get_by_label("Admin Email").fill(email)
            page.get_by_label("Master Password").fill(SEED["password"])
            page.get_by_role("button", name="Sign in as administrator").click()
            page.wait_for_url(f"{BASE}/admin")
        else:
            page.goto(f"{BASE}/login")
            page.get_by_label("Email").fill(email)
            page.get_by_label("Password", exact=True).fill(SEED["password"])
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.wait_for_url(f"{BASE}/")

    def user_flow():
        sign_in(SEED["user"]["email"], admin=False)
        page.set_input_files("input[type=file]", str(image))
        page.get_by_role("button", name="Analyse").click()
        page.wait_for_url(re.compile(r"/results/\d+"), timeout=120000)
        expect(page.locator('img[src^="blob:"]').first).to_be_attached(timeout=30000)
        page.goto(f"{BASE}/history")
        expect(page.locator('img[src^="blob:"]').first).to_be_attached(timeout=30000)
        page.get_by_role("button", name="Sign Out").click()
        page.get_by_role("dialog").get_by_role("button", name="Yes, sign out").click()

    def admin_flow():
        sign_in(SEED["admin"]["email"], admin=True)
        page.goto(f"{BASE}/admin")
        expect(page.get_by_role("heading", name="System overview")).to_be_visible()
        expect(page.locator(".recharts-wrapper").first).to_be_visible(timeout=30000)  # inline-styled SVG
        for path in ("/admin/logs", "/admin/users", "/admin/models"):
            page.goto(f"{BASE}{path}")
            page.wait_for_load_state("networkidle")

    def hsts_on_documents():
        assert documents, "no document responses seen"
        missing = [r.url for r in documents if r.headers.get("strict-transport-security") is None]
        assert not missing, missing[:3]

    step("user: sign in (no OTP), analyse, results + history with blob: images", user_flow)
    step("admin: overview with recharts, logs, users, models", admin_flow)
    step("HSTS on every document response (prod profile)", hsts_on_documents)
    browser.close()

for name, status, detail in results:
    print(f"{status}  {name}" + (f"  -- {detail}" if detail else ""))
line, ok = csp_guard.summary()
print(("PASS  " if ok else "FAIL  ") + line)
for v in csp_guard.violations[:20]:
    print("      " + v)
sys.exit(0 if ok and all(r[1] == "PASS" for r in results) else 1)
