"""Headless-Chromium run of docs/manual-test-react.md (Phase 5a).

    pip install playwright==1.55.0 && python -m playwright install chromium
    python frontend/e2e/run_manual_flows.py <out_dir> <backend_log> <repo_root> <backend_STORAGE_DIR>

Needs the backend on :8000 (REQUIRE_2FA=True, EMAIL_BACKEND=console, writing
its console to <backend_log>) and `npm run dev` on :3000. Uses a scratch
database and storage: step 16 DELETES the uploads under <backend_STORAGE_DIR>.
"""
import io
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

BASE = "http://localhost:3000"
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
        page.wait_for_function("document.querySelectorAll('img[src^=\"blob:\"]').length >= 3", timeout=30000)
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
        page.goto(f"{BASE}/history")
        expect(page.get_by_role("heading", name="Your results")).to_be_visible()
        page.wait_for_function("document.querySelectorAll('img[src^=\"blob:\"]').length >= 3", timeout=30000)
        assert page.locator("li").count() == 3, page.locator("li").count()
        page.screenshot(path=str(OUT / "12-history.png"), full_page=True)
        page.locator("li a").first.click()
        page.wait_for_url(re.compile(r"/results/\d+"))
    step(12, "history list with thumbnails; row opens result", s12)

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
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url(re.compile(r"/login"))
        assert page.evaluate("sessionStorage.getItem('tp_token')") is None
        page.goto(f"{BASE}/history")
        page.wait_for_url(re.compile(r"/login\?next="))
    step(15, "sign in again (OTP, returns to next), sign out", s15)

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
