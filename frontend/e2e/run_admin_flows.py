"""Headless-Chromium run of the admin flows (Phase 5b). Scratch database only.

    DATABASE_URL=<scratch> python frontend/e2e/seed_admin_scratch.py <out>/seed.json
    python frontend/e2e/run_admin_flows.py <out_dir> <backend_log>

Needs the backend on :8000 (REQUIRE_2FA=True, EMAIL_BACKEND=console, console
written to <backend_log>, the SAME scratch database) and `npm run dev` on
:3000. Changes model activations and user statuses in that database; every
change it makes is reverted before it finishes (rollback, re-enable).
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csp_guard  # noqa: E402  (Phase 6: TP_BASE, HTTPS, CSP watch)

BASE = csp_guard.BASE
API = csp_guard.API
OUT = Path(sys.argv[1])
LOG = Path(sys.argv[2])
SEED = json.loads((OUT / "seed.json").read_text())
PASSWORD = SEED["password"]
results = []
files = OUT / "files"
files.mkdir(parents=True, exist_ok=True)


def step(n, name, fn):
    try:
        fn()
        results.append((n, name, "PASS", ""))
    except Exception as exc:  # noqa: BLE001
        results.append((n, name, "FAIL", f"{type(exc).__name__}: {str(exc)[:400]}"))


def otp_for(email: str, after: int) -> str:
    for _ in range(40):
        text = LOG.read_text(encoding="utf-8", errors="ignore")[after:]
        found = re.findall(rf"for {re.escape(email)}: code=(\d{{6}})", text)
        if found:
            return found[-1]
        time.sleep(0.5)
    raise AssertionError("no OTP in backend console")


def sign_in(page, email: str, admin: bool, next_path: str = "/"):
    # Separate portals: users at /login, administrators at /admin/login.
    if admin:
        page.goto(f"{BASE}/admin/login?next={next_path}")
        page.get_by_label("Admin Email").fill(email)
        page.get_by_label("Master Password").fill(PASSWORD)
        submit = page.get_by_role("button", name="Sign in as administrator")
    else:
        page.goto(f"{BASE}/login?next={next_path}")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        submit = page.get_by_role("button", name="Sign in", exact=True)
    mark = len(LOG.read_text(encoding="utf-8", errors="ignore"))
    submit.click()
    page.wait_for_url(re.compile(r"/verify"))
    page.get_by_label("Verification code").fill(otp_for(email, mark))
    page.get_by_role("button", name="Verify").click()
    page.wait_for_url(re.compile(re.escape(next_path) + r"$"))


def token(page) -> str:
    return page.evaluate("sessionStorage.getItem('tp_token')")


def api(page, method: str, path: str, **kw):
    headers = {"Authorization": f"Bearer {token(page)}", **(kw.pop("headers", None) or {})}
    return page.request.fetch(f"{API}{path}", method=method, headers=headers, **kw)


fusion_bad = files / "fusion_tau005.json"
fusion_bad.write_text(json.dumps({"strategy": "weighted_average", "weight_semantic": 0.25, "tau": 0.05, "temperature": 1.0}))
fusion_ok = files / "fusion_tau074.json"
fusion_ok.write_text(json.dumps({"strategy": "weighted_average", "weight_semantic": 0.25, "tau": 0.74, "temperature": 1.0}))
wrong_ext = files / "fusion.txt"
wrong_ext.write_text("{}")

with sync_playwright() as p:
    browser = p.chromium.launch()
    csp_guard.install(browser)
    console_errors, image_requests = [], []

    def watch(page):
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        page.on("request", lambda r: image_requests.append(r.url)
                if re.search(r"/images/\d+/(file|thumbnail)|/explainability/", r.url) else None)

    # ---- A1: a normal user's token on admin routes -------------------------
    user_ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    upage = user_ctx.new_page()
    watch(upage)

    def a1():
        sign_in(upage, SEED["user"]["email"], admin=False)
        # The admin tab is shown to everyone (as in M3's dashboard) but locked for users.
        upage.get_by_role("navigation", name="Main").get_by_role("link", name="3. Admin Dashboard & Analytics").click()
        expect(upage.get_by_text("Administrators only.")).to_be_visible()
        upage.goto(f"{BASE}/admin/users")
        expect(upage.get_by_text("Administrators only.")).to_be_visible()
        for method, path in [("GET", "/admin/summary"), ("GET", "/admin/logs"), ("GET", "/admin/users"),
                             ("GET", "/models"), ("POST", "/models/1/gate-preview"),
                             ("PATCH", f"/admin/users/{SEED['admin2']['id']}/status")]:
            kw = {"data": json.dumps({"action": "disable"}), "headers": None} if method == "PATCH" else {}
            r = upage.request.fetch(f"{API}{path}", method=method,
                                    headers={"Authorization": f"Bearer {token(upage)}", "Content-Type": "application/json"},
                                    data=kw.get("data"))
            assert r.status == 403, (path, r.status)
            assert r.json()["error"]["code"] == "AUTH_FORBIDDEN", r.json()
    step("A1", "normal user: no Admin link, UI guard, API 403 on 6 admin endpoints", a1)
    user_ctx.close()

    # ---- A2: admin sign-in + overview numbers come from the API -----------
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    watch(page)

    def a2():
        sign_in(page, SEED["admin"]["email"], admin=True, next_path="/admin")
        expect(page.get_by_role("heading", name="System overview")).to_be_visible()
        summary = api(page, "GET", "/admin/summary").json()
        analytics = api(page, "GET", "/admin/analytics?days=30").json()

        def tile(label):
            return page.locator("div.rounded-xl", has=page.get_by_text(label, exact=True)).first

        expect(tile("Predictions (all time)")).to_contain_text(str(summary["total_predictions"]))
        expect(tile("Error log entries, last 24 h")).to_contain_text(str(summary["error_count_last_24h"]))
        expect(tile("Active models")).to_contain_text(str(len(summary["active_models"])))
        lat = analytics["latency"]
        p50 = "n/a" if lat["p50_ms"] is None else f"{lat['p50_ms'] / 1000:.2f} s"
        expect(tile("Inference p50 (warm)")).to_contain_text(p50)
        expect(tile("Inference p95 (warm)")).to_contain_text(f"excludes {lat['cold_count']} cold start(s)")
        for m in summary["active_models"]:
            expect(page.get_by_text(m["model_type"], exact=True)).to_be_visible()
        expect(page.get_by_text("100% Operational")).to_have_count(0)
        print("overview:", summary["total_predictions"], "predictions;", summary["error_count_last_24h"],
              "errors 24h; latency", lat)
    step("A2", "admin login (checkbox + OTP); tiles equal /admin/summary + /admin/analytics", a2)

    # ---- A3: logs - paging, filter, plain text ----------------------------
    def a3():
        page.goto(f"{BASE}/admin/logs")
        rows = page.get_by_test_id("log-rows").locator("tr")
        expect(rows.first).to_be_visible()
        pager = page.get_by_label("Pagination")
        expect(pager).to_contain_text(re.compile(r"Page 1 of (\d+)"))
        pages = int(re.search(r"Page 1 of (\d+)", pager.inner_text()).group(1))
        assert pages >= 2, f"only {pages} page(s) of logs"
        first_page_ids = rows.first.inner_text()
        pager.get_by_role("button", name="Next").click()
        expect(pager).to_contain_text("Page 2 of")
        assert rows.first.inner_text() != first_page_ids
        pager.get_by_role("button", name="Previous").click()
        expect(pager).to_contain_text("Page 1 of")
        page.get_by_label("Severity").select_option("error")
        expect(pager.or_(rows.first)).to_be_visible()
        expect(page.get_by_text(SEED["xss"], exact=False).first).to_be_visible()  # literal text
        sev = rows.locator("td:nth-child(2)").all_inner_texts()
        assert sev and set(sev) == {"error"}, set(sev)
        assert page.evaluate("window.__xss") is None, "payload executed"
        assert page.get_by_test_id("log-rows").locator("img, script").count() == 0
        page.get_by_role("button", name="Clear filters").click()
    step("A3", "logs: >=2 pages, Next/Previous, severity filter, HTML payload shown as text", a3)

    # ---- A4: users - pagination, self row, disable/enable ------------------
    def a4():
        page.goto(f"{BASE}/admin/users")
        pager = page.get_by_label("Pagination")
        expect(pager).to_contain_text(re.compile(r"Page 1 of ([2-9]|[1-9][0-9]+)"))
        self_row = page.get_by_test_id(f"user-{SEED['admin']['id']}")
        if self_row.count() == 0:  # newest first: may sit on page 2
            pager.get_by_role("button", name="Next").click()
        expect(self_row).to_contain_text("(you)")
        assert self_row.get_by_role("button").count() == 0
        page.goto(f"{BASE}/admin/users")
        target = page.get_by_test_id(f"user-{SEED['admin2']['id']}")
        if target.count() == 0:
            page.get_by_label("Pagination").get_by_role("button", name="Next").click()
        # cancel leaves it unchanged
        target.get_by_role("button", name="Disable").click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("kept unchanged")
        dialog.get_by_role("button", name="Cancel").click()
        expect(target).to_contain_text("active")
        # disable, then enable
        target.get_by_role("button", name="Disable").click()
        page.get_by_role("dialog").get_by_role("button", name="Disable account").click()
        expect(page.get_by_text(f"{SEED['admin2']['email']} is now disabled.")).to_be_visible()
        assert api(page, "GET", "/admin/users").json() and \
            [u for u in api(page, "GET", "/admin/users").json() if u["user_id"] == SEED["admin2"]["id"]][0]["account_status"] == "disabled"
        target.get_by_role("button", name="Enable").click()
        page.get_by_role("dialog").get_by_role("button", name="Enable account").click()
        expect(page.get_by_text(f"{SEED['admin2']['email']} is now active.")).to_be_visible()
        # there is no Remove button (it did exactly what Disable does)
        expect(target.get_by_role("button", name="Remove")).to_have_count(0)
        # the API refuses self-change even without the UI
        r = api(page, "PATCH", f"/admin/users/{SEED['admin']['id']}/status",
                data=json.dumps({"action": "disable"}), headers={"Content-Type": "application/json"})
        assert r.status == 409 and r.json()["error"]["code"] == "ADM_ACTION_NOT_PERMITTED", r.status
    step("A4", "users: 2 pages, no self actions, cancel/disable/enable with confirmation, no Remove; API 409 on self", a4)

    # ---- A5: models - upload, preview, refuse, force, rollback ------------
    def a5():
        page.goto(f"{BASE}/admin/models")
        expect(page.get_by_role("heading", name="Running now")).to_be_visible()
        before = api(page, "GET", "/models").json()["active"]["fusion-configuration"]["model_id"]
        expect(page.get_by_test_id("active-fusion-configuration")).to_contain_text("Evaluation reference:")
        form = page.get_by_role("form", name="Register a model")
        # client-side convenience check
        form.locator("input[type=file]").set_input_files(str(wrong_ext))
        form.get_by_label("Name").fill("e2e fusion")
        form.get_by_label("Version").fill(f"bad{SEED['stamp']}")
        form.get_by_label(re.compile("Evaluation / training reference")).fill("e2e: deliberately extreme tau")
        form.get_by_role("button", name="Register (inactive)").click()
        expect(page.get_by_text("This model type expects a .json file.")).to_be_visible()
        # real upload
        form.locator("input[type=file]").set_input_files(str(fusion_bad))
        form.get_by_role("button", name="Register (inactive)").click()
        expect(page.get_by_text(re.compile(r"Registered model #\d+, inactive"))).to_be_visible(timeout=30000)
        bad_id = int(re.search(r"#(\d+)", page.get_by_text(re.compile(r"Registered model #\d+")).inner_text()).group(1))
        card = page.get_by_test_id(f"model-{bad_id}")
        card.get_by_role("button", name="Check quality gate").click()
        report = card.get_by_test_id("gate-report")
        expect(report).to_be_visible(timeout=120000)
        expect(report).to_contain_text("a coarse safety net, not a verification")
        expect(report).to_contain_text("Outside the gate thresholds")
        expect(report).to_contain_text("false-positive rate")
        # plain activation is refused
        card.get_by_role("button", name="Activate…").click()
        page.get_by_role("dialog").get_by_role("button", name="Activate").click()
        expect(page.get_by_text(f"The quality gate refused model #{bad_id}. Nothing changed.")).to_be_visible(timeout=120000)
        assert api(page, "GET", "/models").json()["active"]["fusion-configuration"]["model_id"] == before
        # force: needs reason (>=10 chars) AND acknowledgement
        card.get_by_role("button", name="Override the gate…").click()
        dialog = page.get_by_role("dialog")
        confirm = dialog.get_by_role("button", name="Override and activate")
        expect(confirm).to_be_disabled()
        dialog.get_by_label(re.compile("Reason")).fill("short")
        dialog.get_by_label(re.compile("I understand")).check()
        expect(confirm).to_be_disabled()
        dialog.get_by_label(re.compile("Reason")).fill("e2e: exercising the audited override path")
        expect(confirm).to_be_enabled()
        confirm.click()
        expect(page.get_by_text(f"Activated (gate overridden): model #{bad_id}")).to_be_visible(timeout=120000)
        assert api(page, "GET", "/models").json()["active"]["fusion-configuration"]["model_id"] == bad_id
        acts = api(page, "GET", "/models/activations").json()
        assert acts[0]["forced"] and acts[0]["reason"] == "e2e: exercising the audited override path"
        # rollback offered and works
        roll = page.get_by_test_id("active-fusion-configuration").get_by_role("button", name=f"Roll back to #{before}")
        roll.click()
        page.get_by_role("dialog").get_by_role("button", name=f"Roll back to #{before}").click()
        expect(page.get_by_text(f"Rolled back to model #{before}")).to_be_visible(timeout=120000)
        assert api(page, "GET", "/models").json()["active"]["fusion-configuration"]["model_id"] == before
        # a passing candidate activates normally, then roll back to leave the baseline active
        form.locator("input[type=file]").set_input_files(str(fusion_ok))
        form.get_by_label("Name").fill("e2e fusion")  # the form clears after a successful upload
        form.get_by_label("Version").fill(f"ok{SEED['stamp']}")
        form.get_by_label(re.compile("Evaluation / training reference")).fill("e2e: moderate tau")
        form.get_by_role("button", name="Register (inactive)").click()
        expect(page.get_by_text(re.compile(rf"Registered model #(?!{bad_id}\b)\d+, inactive"))).to_be_visible(timeout=30000)
        ok_id = int(re.search(r"#(\d+)", page.get_by_text(re.compile(r"Registered model #\d+")).inner_text()).group(1))
        page.get_by_test_id(f"model-{ok_id}").get_by_role("button", name="Activate…").click()
        page.get_by_role("dialog").get_by_role("button", name="Activate").click()
        expect(page.get_by_text(re.compile(r"Running canary and quality gate… \d+s"))).to_be_visible(timeout=10000)
        expect(page.get_by_text(f"Activated model #{ok_id}")).to_be_visible(timeout=120000)
        expect(page.get_by_text("Within the gate thresholds.")).to_be_visible()
        page.get_by_test_id("active-fusion-configuration").get_by_role("button", name=f"Roll back to #{before}").click()
        page.get_by_role("dialog").get_by_role("button", name=f"Roll back to #{before}").click()
        expect(page.get_by_text(f"Rolled back to model #{before}")).to_be_visible(timeout=120000)
        assert api(page, "GET", "/models").json()["active"]["fusion-configuration"]["model_id"] == before
        assert page.get_by_text(re.compile(r"\bverified\b", re.I)).count() == 0
    step("A5", "models: client check, upload, gate preview, refusal, forced override w/ reason, rollback, pass+activate", a5)

    # ---- A6: 375 px emulation of the admin screens ------------------------
    def a6():
        page.set_viewport_size({"width": 375, "height": 800})
        for path in ("/admin", "/admin/logs", "/admin/users", "/admin/models"):
            page.goto(f"{BASE}{path}")
            page.wait_for_load_state("networkidle")
            over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert over <= 0, f"{path}: page scrolls horizontally by {over}px"
        page.set_viewport_size({"width": 1280, "height": 900})
    step("A6", "375 px emulation: no page-level horizontal scroll on the 4 admin screens", a6)

    # ---- A7: expired / invalid admin token --------------------------------
    def a7():
        page.goto(f"{BASE}/admin")
        expect(page.get_by_role("heading", name="System overview")).to_be_visible()
        page.wait_for_load_state("networkidle")
        page.evaluate("sessionStorage.setItem('tp_token', 'invalid.' + sessionStorage.getItem('tp_token'))")
        page.get_by_role("navigation", name="Administration").get_by_role("link", name="Logs").click()
        page.wait_for_url(re.compile(r"/admin/login\?expired=1&next=%2Fadmin%2Flogs"))
        expect(page.get_by_text("Your session ended")).to_be_visible()
    step("A7", "invalid admin token -> Administrator Portal (/admin/login?expired=1) with return path", a7)

    def a8():
        assert not image_requests, image_requests[:5]
    step("A8", "admin screens fetched no user images, thumbnails or panels", a8)
    browser.close()

for n, name, status, detail in results:
    print(f"{n:>3} {status} {name}" + (f"\n      {detail}" if detail else ""))
unexpected = [e for e in console_errors if "401" not in e and "403" not in e and "409" not in e]
print("console errors (401/403/409 expected):", len(console_errors), "unexpected:", unexpected[:5])
csp_line, csp_ok = csp_guard.summary()
print(("PASS  " if csp_ok else "FAIL  ") + csp_line)
for v in csp_guard.violations[:20]:
    print("      " + v)
sys.exit(0 if csp_ok and all(r[2] == "PASS" for r in results) else 1)
