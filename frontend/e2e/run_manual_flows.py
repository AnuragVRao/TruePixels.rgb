"""Headless-Chromium run of docs/manual-test-react.md (Phase 5a).

    pip install playwright==1.55.0 && python -m playwright install chromium
    python frontend/e2e/run_manual_flows.py <out_dir> <backend_log> <repo_root> <backend_STORAGE_DIR>

Needs the backend on :8000 (REQUIRE_2FA=True, EMAIL_BACKEND=console, writing
its console to <backend_log>) and `npm run dev` on :3000. Uses a scratch
database and storage: step 16 DELETES the uploads under <backend_STORAGE_DIR>.
"""
import io
from urllib.parse import quote
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csp_guard  # noqa: E402  (Phase 6: TP_BASE, HTTPS, CSP watch)

BASE = csp_guard.BASE
OUT = Path(sys.argv[1])
LOG = Path(sys.argv[2])
REPO = Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
results = []


def step(n, name, fn):
    try:
        fn()
        results.append((n, name, "PASS", ""))
    except Exception as exc:  # noqa: BLE001
        results.append((n, name, "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}"))


def otp_for(email: str, after: int) -> str:
    for _ in range(40):
        text = LOG.read_text(encoding="utf-8", errors="ignore")[after:]
        found = re.findall(rf"for {re.escape(email)}: code=(\d{{6}})", text)
        if found:
            return found[-1]
        time.sleep(0.5)
    raise AssertionError("no OTP in backend console")


def img(path: Path, w: int, h: int, fmt: str = "PNG", seed: int = 0):
    Image.fromarray(np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)).save(path, fmt)
    return path


files = OUT / "files"
files.mkdir(exist_ok=True)
gif = img(files / "x.gif", 200, 200, "GIF")
tiny = img(files / "tiny.png", 32, 32)
small = img(files / "small160.png", 160, 160, seed=4)
big = files / "big.png"
img(big, 4000, 3000, seed=5)  # random noise PNG compresses badly: > 10 MB
assert big.stat().st_size > 10 * 2**20, big.stat().st_size
normal = REPO / "ml/datasets/synthbuster_raise/1_fake/midjourney-v5/r01a5f38at.png"

email = f"react{int(time.time())}@example.com"
other_email = f"other{int(time.time())}@example.com"
password = "ReactTest12345"

with sync_playwright() as p:
    browser = p.chromium.launch()
    csp_guard.install(browser)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page = ctx.new_page()
    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
    report_requests = []
    page.on("request", lambda r: report_requests.append(r.url) if "/reports/" in r.url else None)

    def s1():
        page.goto(f"{BASE}/history")
        page.wait_for_url(re.compile(r"/login\?next=%2Fhistory"))
    step(1, "guard redirects to login", s1)

    def s2():
        page.goto(f"{BASE}/register")
        page.get_by_label("Full name").fill("React Tester")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password", exact=True).fill("short")
        expect(page.get_by_role("button", name="Create account")).to_be_disabled()
        page.get_by_label("Password", exact=True).fill(password)
        expect(page.get_by_role("button", name="Create account")).to_be_enabled()
    step(2, "register form rules", s2)

    mark = {"pos": 0}

    def s3():
        mark["pos"] = len(LOG.read_text(encoding="utf-8", errors="ignore"))
        page.get_by_role("button", name="Create account").click()
        page.wait_for_url(re.compile(r"/verify\?email="))
        expect(page.get_by_text("print the code to the server console")).to_be_visible()
        page.screenshot(path=str(OUT / "03-verify.png"))
    step(3, "registration -> OTP page with console hint", s3)

    def s4():
        page.get_by_label("Verification code").fill("000000")
        page.get_by_role("button", name="Verify").click()
        expect(page.get_by_role("alert")).to_be_visible()
        page.screenshot(path=str(OUT / "04-wrong-otp.png"))
    step(4, "wrong OTP -> structured error", s4)

    def s5():
        code = otp_for(email, mark["pos"])
        page.get_by_label("Verification code").fill(code)
        page.get_by_role("button", name="Verify").click()
        page.wait_for_url(f"{BASE}/")
        expect(page.get_by_role("heading", name="Analyse an image")).to_be_visible()
    step(5, "right OTP -> signed in", s5)

    def s6():
        chooser = page.locator('input[type="file"]')
        for f, expected in ((gif, "Only JPG"), (big, "the limit is 10 MB"), (tiny, "at least 64 px")):
            chooser.set_input_files(str(f))
            expect(page.get_by_text(expected)).to_be_visible()
        page.screenshot(path=str(OUT / "06-validation.png"))
    step(6, "client-side upload validation (gif, >10MB, 32px)", s6)

    xai_result = {"id": None}

    def s7_8():
        page.locator('input[type="file"]').set_input_files(str(normal))
        page.get_by_role("button", name="Analyse").click()
        expect(page.get_by_text(re.compile(r"Analysing… \d+s"))).to_be_visible(timeout=30000)
        page.screenshot(path=str(OUT / "07-analysing.png"))
        page.wait_for_url(re.compile(r"/results/\d+"), timeout=180000)
        expect(page.get_by_text("SigLIP 2 attention rollout")).to_be_visible(timeout=30000)
        expect(page.get_by_text("SPAI patch spectrum")).to_be_visible()
        expect(page.get_by_text("attention-based proxy")).to_be_visible()   # backend caption, as text
        expect(page.get_by_text("Models that produced this result")).to_be_visible()
        # A locator wait, not wait_for_function: the latter evals a string in the
        # page, which the production CSP (no 'unsafe-eval') rightly blocks.
        expect(page.locator('img[src^="blob:"]').nth(2)).to_be_attached(timeout=30000)
        page.screenshot(path=str(OUT / "08-results.png"), full_page=True)
        xai_result["id"] = page.url.rsplit("/", 1)[-1]
    step(7, "analyse with xai: progress then results (panels, captions, models, blob images)", s7_8)

    def s9():
        with page.expect_download() as dl:
            page.get_by_role("button", name="PDF report").click()
        path = dl.value.path()
        assert Path(path).read_bytes()[:5] == b"%PDF-"
        assert report_requests and all("token=" not in u for u in report_requests), report_requests
    step(9, "PDF download (header auth, no token in URL)", s9)

    def s10():
        page.goto(f"{BASE}/")
        page.locator('input[type="file"]').set_input_files(str(small))
        page.get_by_role("button", name="Analyse").click()
        page.wait_for_url(re.compile(r"/results/\d+"), timeout=120000)
        expect(page.get_by_text("not measured")).to_be_visible(timeout=30000)
        expect(page.get_by_text("Semantic-only verdict")).to_be_visible()
        expect(page.get_by_text("smaller than the frequency detector's 224-pixel patch").first).to_be_visible()
        page.screenshot(path=str(OUT / "10-small.png"), full_page=True)
    step(10, "small image: semantic-only + partial xai", s10)

    def s11():
        page.goto(f"{BASE}/")
        page.locator('input[type="file"]').set_input_files(str(normal))
        page.get_by_label(re.compile("Include explainability")).uncheck()
        page.get_by_role("button", name="Analyse").click()
        page.wait_for_url(re.compile(r"/results/\d+"), timeout=120000)
        expect(page.get_by_text("No explainability panels were requested")).to_be_visible(timeout=30000)
    step(11, "xai off: no panels, message shown", s11)

    def s12():
        # Seed 25 more results through the API (same session token) so the
        # history has 28 rows and pagination is exercised in the browser.
        token = page.evaluate("sessionStorage.getItem('tp_token')")
        auth = {"Authorization": f"Bearer {token}"}
        for i in range(25):
            buf = io.BytesIO()
            Image.fromarray(np.random.default_rng(100 + i).integers(0, 256, (240, 240, 3), dtype=np.uint8)).save(buf, "PNG")
            up = page.request.post(f"{BASE}/api/v1/images", headers=auth,
                                   multipart={"file": {"name": f"seed{i}.png", "mimeType": "image/png", "buffer": buf.getvalue()}})
            assert up.ok, up.text()
            pr = page.request.post(f"{BASE}/api/v1/predictions", headers=auth,
                                   data={"image_id": up.json()["image_id"], "xai": False}, timeout=120000)
            assert pr.ok, pr.text()
        page.goto(f"{BASE}/history")
        expect(page.get_by_role("heading", name="Your results")).to_be_visible()
        expect(page.get_by_text("Page 1 of 3 · 28 results")).to_be_visible(timeout=30000)
        assert page.locator("li").count() == 10, page.locator("li").count()
        # A locator wait, not wait_for_function: the latter evals a string in the
        # page, which the production CSP (no 'unsafe-eval') rightly blocks.
        expect(page.locator('img[src^="blob:"]').nth(9)).to_be_attached(timeout=30000)
        page.screenshot(path=str(OUT / "12-history.png"), full_page=True)
        page.get_by_role("button", name="Next").click()
        expect(page.get_by_text("Page 2 of 3 · 28 results")).to_be_visible()
        page.get_by_role("button", name="Next").click()
        expect(page.get_by_text("Page 3 of 3 · 28 results")).to_be_visible()
        assert page.locator("li").count() == 8, page.locator("li").count()
        expect(page.get_by_role("button", name="Next")).to_be_disabled()
        page.locator("li a").last.click()  # the oldest: the step-7 xai result
        page.wait_for_url(re.compile(r"/results/\d+"))
    step(12, "history: 28 rows, 3 pages (10/10/8), thumbnails, row opens result", s12)

    my_result = {"id": None}

    def s13():
        my_result["id"] = page.url.rsplit("/", 1)[-1]
        other = browser.new_context()
        op = other.new_page()
        op.goto(f"{BASE}/register")
        op.get_by_label("Full name").fill("Other User")
        op.get_by_label("Email").fill(other_email)
        op.get_by_label("Password", exact=True).fill(password)
        pos = len(LOG.read_text(encoding="utf-8", errors="ignore"))
        op.get_by_role("button", name="Create account").click()
        op.wait_for_url(re.compile(r"/verify"))
        op.get_by_label("Verification code").fill(otp_for(other_email, pos))
        op.get_by_role("button", name="Verify").click()
        op.wait_for_url(f"{BASE}/")
        op.goto(f"{BASE}/results/{my_result['id']}")
        expect(op.get_by_text("That result was not found.")).to_be_visible(timeout=15000)
        op.screenshot(path=str(OUT / "13-not-yours.png"))
        other.close()
    step(13, "another user's result -> not found", s13)

    def s16():
        # Remove every stored original (scratch storage only), then reopen a result.
        uploads = Path(sys.argv[4]) / "uploads"
        removed = [f.unlink() for f in uploads.rglob("*") if f.is_file()]
        assert removed, "no uploads to remove"
        page.goto(f"{BASE}/results/{xai_result['id']}")  # the xai result: it has panels
        expect(page.get_by_text("The original image is no longer stored.")).to_be_visible(timeout=15000)
        expect(page.get_by_text("SigLIP 2 attention rollout")).to_be_visible()  # panels still served
        page.screenshot(path=str(OUT / "16-missing-original.png"), full_page=True)
        page.goto(f"{BASE}/history")
        expect(page.get_by_text("image unavailable").first).to_be_visible(timeout=15000)
    step(16, "missing original: notice on result, placeholder thumbnails", s16)

    def s14():
        page.evaluate("sessionStorage.removeItem('tp_token'); sessionStorage.setItem('tp_token', 'expired-token')")
        page.goto(f"{BASE}/history")
        page.wait_for_url(re.compile(r"/login\?"), timeout=15000)
        page.screenshot(path=str(OUT / "14-expired.png"))
    step(14, "invalid/expired token -> back to sign-in", s14)

    def s15():
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password", exact=True).fill(password)
        pos = len(LOG.read_text(encoding="utf-8", errors="ignore"))
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url(re.compile(r"/verify"))
        page.get_by_label("Verification code").fill(otp_for(email, pos))
        page.get_by_role("button", name="Verify").click()
        page.wait_for_url(re.compile(r"/history"))  # returned to the page it was sent from
        page.get_by_role("button", name="Sign Out").click()
        page.get_by_role("dialog").get_by_role("button", name="Yes, sign out").click()
        page.wait_for_url(f"{BASE}/")  # back to the landing page, as in M1
        expect(page.get_by_role("heading", name="Verify Still Image Authenticity")).to_be_visible()
        assert page.evaluate("sessionStorage.getItem('tp_token')") is None
        page.goto(f"{BASE}/history")
        page.wait_for_url(re.compile(r"/login\?next="))
    step(15, "sign in again (OTP, returns to next), sign out", s15)

    def s19():
        # Signed out, "/" is the landing page with M1's three separate entry points.
        lp = browser.new_context().new_page()
        lp.goto(f"{BASE}/")
        expect(lp.get_by_role("heading", name="Verify Still Image Authenticity")).to_be_visible()
        expect(lp.get_by_text("Authentication Required to Upload")).to_be_visible()
        nav = lp.get_by_role("navigation", name="Account")
        for name, path in (("Admin Login", "/admin/login"), ("Sign In", "/login"), ("Create Account", "/register")):
            nav.get_by_role("link", name=name).click()
            lp.wait_for_url(f"{BASE}{path}")
            lp.goto(f"{BASE}/")
        # The user sign-in page has no administrator option; the portals are separate.
        lp.goto(f"{BASE}/login")
        expect(lp.get_by_text("Sign in as administrator")).to_have_count(0)
        lp.goto(f"{BASE}/admin/login")
        expect(lp.get_by_role("heading", name="Administrator Portal")).to_be_visible()
        # A normal user is refused by the Administrator Portal (server-side AUTH_FORBIDDEN).
        lp.get_by_label("Admin Email").fill(email)
        lp.get_by_label("Master Password").fill(password)
        lp.get_by_role("button", name="Sign in as administrator").click()
        expect(lp.get_by_role("alert")).to_contain_text("AUTH_FORBIDDEN")
        assert "/verify" not in lp.url
        lp.context.close()
    step(19, "landing page (M1), separate Create Account / Sign In / Admin Login; user refused by admin portal", s19)

    def s20():
        # Signed in: the four numbered tabs of M3's original dashboard.
        page.goto(f"{BASE}/login")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password", exact=True).fill(password)
        pos = len(LOG.read_text(encoding="utf-8", errors="ignore"))
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url(re.compile(r"/verify"))
        page.get_by_label("Verification code").fill(otp_for(email, pos))
        page.get_by_role("button", name="Verify").click()
        page.wait_for_url(f"{BASE}/")
        tabs = page.get_by_role("navigation", name="Main")
        for label in ("1. Forensic Detection", "2. User Scan History", "3. Admin Dashboard & Analytics",
                      "4. 1-Click Verification"):
            expect(tabs.get_by_role("link", name=label)).to_be_visible()
        # Tab 2: the isolation notice and its Test Security Barrier button.
        tabs.get_by_role("link", name="2. User Scan History").click()
        page.get_by_role("button", name="Test Security Barrier").click()
        expect(page.get_by_role("status").filter(has_text="Barrier active")).to_be_visible()
        # Tab 3 for a normal user: visible but locked.
        tabs.get_by_role("link", name="3. Admin Dashboard & Analytics").click()
        expect(page.get_by_text("Administrators only.")).to_be_visible()
        # Tab 4: every live check passes on its exact expected status.
        tabs.get_by_role("link", name="4. 1-Click Verification").click()
        page.get_by_role("button", name="Run Verification").click()
        summary = page.get_by_test_id("verification-summary")
        expect(summary).to_contain_text(re.compile(r"\d+ passed, 0 failed"), timeout=60000)
        assert page.locator('[data-outcome="fail"]').count() == 0
        # Sign Out asks first; Cancel keeps the session.
        page.get_by_role("button", name="Sign Out").click()
        page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
        assert page.evaluate("sessionStorage.getItem('tp_token')") is not None
        page.get_by_role("button", name="Sign Out").click()
        page.get_by_role("dialog").get_by_role("button", name="Yes, sign out").click()
        page.wait_for_url(f"{BASE}/")
    step(20, "signed in: 4 dashboard tabs; security barrier; admin tab locked for users; 1-click verification all PASS; sign-out confirmation", s20)

    def s18():
        # After signing in, ?next= must never leave this origin.
        for target in ("https://evil.example/steal", "//evil.example/steal", "/" + chr(92) + "evil.example/steal"):
            fresh = browser.new_context()
            fp = fresh.new_page()
            fp.goto(f"{BASE}/login?next={quote(target, safe='')}")
            fp.get_by_label("Email").fill(email)
            fp.get_by_label("Password", exact=True).fill(password)
            pos = len(LOG.read_text(encoding="utf-8", errors="ignore"))
            fp.get_by_role("button", name="Sign in").click()
            fp.wait_for_url(re.compile(r"/verify"))
            fp.get_by_label("Verification code").fill(otp_for(email, pos))
            fp.get_by_role("button", name="Verify").click()
            fp.wait_for_url(f"{BASE}/", timeout=15000)  # landed on our start page, not the target
            assert fp.url.startswith(BASE), fp.url
            fresh.close()
    step(18, "post-login redirect ignores external next= targets (3 forms)", s18)

    def s17():
        mobile = browser.new_context(viewport={"width": 375, "height": 800})
        mp = mobile.new_page()
        mp.goto(f"{BASE}/login")
        width = mp.evaluate("document.documentElement.scrollWidth")
        assert width <= 375, width
        mp.screenshot(path=str(OUT / "17-mobile-login.png"))
        mobile.close()
    step(17, "375 px: no horizontal scroll (login page)", s17)

    browser.close()

for n, name, status, detail in results:
    print(f"{n:>2} {status}  {name}" + (f"  -- {detail}" if detail else ""))
print("console errors:", [e for e in console_errors if "401" not in e and "404" not in e][:10])
csp_line, csp_ok = csp_guard.summary()
print(("PASS  " if csp_ok else "FAIL  ") + csp_line)
for v in csp_guard.violations[:20]:
    print("      " + v)
sys.exit(0 if csp_ok and all(r[2] == "PASS" for r in results) else 1)
