"""Drives the real viewer in Chrome with Playwright. Opt-in: VID3D_UI=1 pytest tests/test_ui.py

The full local run (drop the synthetic video, ~3 minutes of real processing) also needs VID3D_E2E=1.
Set VID3D_SHOTS=1 to refresh the screenshots in docs/screenshots/.
"""

import functools
import http.server
import json
import os
import re
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VID3D_UI") != "1", reason="set VID3D_UI=1 to run")

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "viewer"
SHOTS = ROOT / "docs" / "screenshots"
VIDEO = ROOT / "samples" / "synthetic_room.mp4"
CHROME_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


VERCEL_HEADERS = {h["key"]: h["value"] for h in next(r for r in json.loads((ROOT / "vercel.json").read_text())["headers"]
                                                    if r["source"] == "/(.*)")["headers"]}


class Quiet(http.server.SimpleHTTPRequestHandler):
    """Static files with the headers vercel.json sends, so the strict CSP is enforced in these tests."""

    def end_headers(self):
        for k, v in VERCEL_HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def log_message(self, *a):
        pass


def serve_in_thread(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(scope="module")
def pw():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:  # one Playwright session per module: two cannot run in the same thread
        yield p


@pytest.fixture(scope="module")
def playwright_browser(pw):
    browser = pw.chromium.launch(channel="chrome", headless=True, args=CHROME_ARGS)
    yield browser
    browser.close()


@pytest.fixture
def hosted_url():
    """The viewer folder served as plain static files, exactly what Vercel or GitHub Pages serves."""
    srv = serve_in_thread(functools.partial(Quiet, directory=str(VIEWER)))
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


@pytest.fixture(scope="module")
def gpu_browser(pw):
    """Real Chrome with WebGPU (no software-graphics flags): depth runs on the GPU at ~0.35 s per frame instead of ~6 s on the CPU."""
    browser = pw.chromium.launch(channel="chrome", headless=True, args=["--enable-unsafe-webgpu"])
    yield browser
    browser.close()


@pytest.fixture
def gpu_desktop(gpu_browser):
    p = Page(gpu_browser, viewport={"width": 1440, "height": 900})
    yield p
    p.close()


@pytest.fixture(scope="session")
def h264_video():
    """The synthetic room as H.264 (tests/data, 6 s, 640 x 480): browsers cannot decode the sample's MPEG-4 Part 2, phones record H.264 or HEVC.
    Committed so the test does not depend on the machine's OpenCV having an H.264 encoder (CI runners often do not)."""
    path = ROOT / "tests" / "data" / "synthetic_room_h264.mp4"
    assert path.exists() and path.stat().st_size > 10_000
    return path


@pytest.fixture
def local_url(tmp_path):
    """`vid3d serve`: the same server, running the real pipeline."""
    from vid3d.server import Jobs, ServeHandler

    srv = serve_in_thread(functools.partial(ServeHandler, jobs=Jobs(tmp_path / "jobs")))
    (tmp_path / "jobs").mkdir(exist_ok=True)
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


class Page:
    """A browser page that remembers every console error, page error and failed request."""

    def __init__(self, browser, **ctx):
        self.context = browser.new_context(**ctx)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(f"console: {m.text}"))
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("requestfailed", lambda r: self.errors.append(f"request failed: {r.url}"))

    def close(self):
        self.context.close()


@pytest.fixture
def desktop(playwright_browser):
    p = Page(playwright_browser, viewport={"width": 1440, "height": 900})
    yield p
    p.close()


@pytest.fixture
def phone(playwright_browser):
    p = Page(playwright_browser, viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    yield p
    p.close()


def until(page, expr, timeout=20000):
    """Wait for a JS expression to be truthy. Polls with evaluate: wait_for_function uses eval, which our CSP blocks."""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if page.evaluate(expr):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"timed out waiting for: {expr}")


def shot(page, name):
    if os.environ.get("VID3D_SHOTS") == "1":
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def open_sample(pg, url):
    pg.page.goto(url)
    pg.page.click("#sample-btn")
    until(pg.page, "window.__vid3d && window.__vid3d.meta", 20000)
    pg.page.wait_for_timeout(600)  # let the first frames render


FIND_POINT = """([minX, minY, maxX, maxY]) => {
  const v = window.__vid3d.view, r = v.renderer.domElement.getBoundingClientRect();
  const found = [];
  for (let i = 0; i < v.data.count && found.length < 2; i += 53) {
    const s = v.screenPositionOf(i);
    if (s.x < minX || s.x > maxX || s.y < minY || s.y > maxY) continue;
    const hit = v.pickPoint(((s.x - r.left) / r.width) * 2 - 1, -((s.y - r.top) / r.height) * 2 + 1);
    if (!hit) continue;
    const c = v.data.colors, j = hit.index;
    // click exactly where the pick was computed, so the app picks the very same point
    found.push({ x: s.x, y: s.y, rgb: [c[3*j], c[3*j+1], c[3*j+2]], index: j, height: v.data.positions[3*j+1] });
  }
  return found;
}"""


def points_on_screen(pg, box):
    pts = pg.page.evaluate(FIND_POINT, box)
    assert len(pts) == 2, "no two pickable points were visible"
    return pts


# ---------- hosted (static) site ----------

def test_hosted_start_screen_is_honest_about_what_it_can_do(desktop, hosted_url):
    pg = desktop.page
    pg.goto(hosted_url)
    until(pg, "document.documentElement.dataset.mode === 'hosted'")
    note = pg.inner_text("#mode-note")
    assert "Nothing leaves it until you say so" in note and "run on your device" in note
    assert pg.is_visible("#sample-btn") and pg.is_visible("#drop")
    pg.click("#advanced summary")
    assert pg.is_visible("#opt-server") and pg.is_visible("#opt-camera")  # server address plus the scale options
    assert "GitHub.com/Srijjit-V/video-to-3d".lower() in pg.get_attribute("a.link", "href").lower()
    shot(pg, "desktop-landing")
    assert desktop.errors == []
    assert "script-src 'self'" in VERCEL_HEADERS["Content-Security-Policy"]


def test_hosted_sample_loads_colour_modes_picker_and_measure_work(desktop, hosted_url):
    pg = desktop.page
    open_sample(desktop, hosted_url)
    assert re.fullmatch(r"\d\.\d\d × \d\.\d\d m", pg.inner_text("#dims"))
    assert pg.locator(".swatch").count() >= 3  # wall / floor palette
    assert "not seen" in pg.inner_text("#palette")  # the sample has no visible ceiling

    # colour modes
    assert pg.is_hidden("#legend")
    for mode, label in (("height", "Height above floor"), ("distance", "Distance from camera path"), ("views", "Frames that saw the point")):
        pg.select_option("#color-mode", mode)
        assert pg.is_visible("#legend") and pg.inner_text("#legend-title") == label
    pg.select_option("#color-mode", "true")
    assert pg.is_hidden("#legend")

    # colour picker: click a point, the readout must hold that point's real colour
    pg.keyboard.press("p")
    assert pg.get_attribute("#tool-pick", "aria-pressed") == "true"
    a, b = points_on_screen(desktop, [420, 120, 1400, 760])
    pg.mouse.click(a["x"], a["y"])
    pg.wait_for_selector("#pick-readout", state="visible")
    r, g, bl = a["rgb"]
    assert pg.inner_text("#pick-rgb") == f"RGB {r}, {g}, {bl}"
    assert pg.inner_text("#pick-hex") == f"#{r:02x}{g:02x}{bl:02x}"
    assert "Height" in pg.inner_text("#pick-extra") and "seen in" in pg.inner_text("#pick-extra")
    assert pg.evaluate("getComputedStyle(document.getElementById('pick-swatch')).backgroundColor") == f"rgb({r}, {g}, {bl})"

    # measuring still works
    pg.keyboard.press("m")
    assert pg.get_attribute("#tool-measure", "aria-pressed") == "true"
    pg.mouse.click(a["x"], a["y"])
    pg.mouse.click(b["x"], b["y"])
    pg.wait_for_selector("#measures li")
    assert re.search(r"\d\.\d\d m · \d+′\d+″", pg.inner_text("#measures"))

    # calibration rescales the room numbers
    before = pg.inner_text("#dims")
    pg.fill("#true-len", "1")
    pg.click("#cal-btn")
    assert pg.inner_text("#dims") != before
    assert "calibrated" in pg.inner_text("#warnings")
    pg.click("#uncal-btn")
    assert pg.inner_text("#dims") == before

    pg.keyboard.press("t")
    assert pg.get_attribute("#tool-top", "aria-pressed") == "true"
    shot(pg, "desktop-scene")
    assert desktop.errors == []


def test_hosted_opens_dropped_cloud_and_scene_files(desktop, hosted_url):
    pg = desktop.page
    pg.goto(hosted_url)
    pg.set_input_files("#file", [str(VIEWER / "sample" / n) for n in ("cloud.ply", "scene.json", "floorplan.png")])
    until(pg, "window.__vid3d && window.__vid3d.meta", 20000)
    assert re.fullmatch(r"\d\.\d\d × \d\.\d\d m", pg.inner_text("#dims"))
    pg.wait_for_selector("#plan", state="visible")
    assert desktop.errors == []


def test_hosted_opens_a_lone_cloud_with_a_clear_limitation(desktop, hosted_url):
    pg = desktop.page
    pg.goto(hosted_url)
    pg.set_input_files("#file", [str(VIEWER / "sample" / "cloud.ply")])
    until(pg, "window.__vid3d && window.__vid3d.meta")
    assert "No scene.json" in pg.inner_text("#warnings")
    assert pg.is_hidden("#plan-wrap")


def test_hosted_explains_a_video_this_browser_cannot_read(desktop, hosted_url, tmp_path):
    fake = tmp_path / "room.mp4"
    fake.write_bytes(b"not really a video")
    desktop.page.goto(hosted_url)
    desktop.page.set_input_files("#file", str(fake))
    desktop.page.wait_for_selector("#prog-error", state="visible")
    assert "couldn't read that video" in desktop.page.inner_text("#prog-error-msg")


def test_hosted_hybrid_picks_frames_asks_consent_then_gets_the_camera_path(gpu_desktop, hosted_url, h264_video, tmp_path):
    """The real synthetic video, the real browser, a real camera-solve server running real COLMAP."""
    from urllib.parse import urlparse

    from vid3d.sfm_server import Limits, default_runner, make_server

    origin = "http://" + urlparse(hosted_url).netloc
    srv = make_server("127.0.0.1", 0, runner=default_runner, allowed_origins={origin}, limits=Limits(min_interval_s=0.0), tmp_root=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    seen = []
    pg = gpu_desktop.page
    pg.on("request", lambda r: seen.append((r.method, r.url, r.post_data_buffer and len(r.post_data_buffer))))
    pg.goto(hosted_url)
    # a real GPU with 16-bit float shaders is needed (software adapters have no shader-f16; the CPU path takes about 8 minutes)
    if not pg.evaluate("async () => { const a = navigator.gpu && await navigator.gpu.requestAdapter(); return !!(a && a.features.has('shader-f16')); }"):
        srv.shutdown()
        pytest.skip("needs a browser with a real WebGPU adapter that supports shader-f16")
    pg.click("#advanced summary")
    pg.fill("#opt-server", f"http://127.0.0.1:{srv.server_address[1]}")
    pg.fill("#opt-camera", "1.5")  # the true camera height of the synthetic room
    pg.set_input_files("#file", str(h264_video))
    # stage 1 runs on the device; nothing has been sent yet when the consent screen appears
    pg.wait_for_selector("#consent", state="visible", timeout=240000)
    assert not [r for r in seen if r[0] == "POST"], "something was sent before consent"
    assert int(pg.inner_text("#consent-count")) >= 30
    assert pg.locator("#consent-thumbs img").count() >= 3
    assert "127.0.0.1" in pg.inner_text("#consent-host")
    assert "Your video stays on this device" in pg.inner_text("#consent")
    shot(pg, "desktop-consent")
    pg.click("#consent-send")
    # stage 2 on the server, then depth + measuring on this device; fail fast on an error instead of waiting out the timeout
    for _ in range(1500):
        if pg.is_visible("#scene") or pg.is_visible("#prog-error"):
            break
        pg.wait_for_timeout(500)
    assert not pg.is_visible("#prog-error"), pg.inner_text("#prog-error-msg")
    assert pg.is_visible("#scene")
    until(pg, "window.__vid3d && window.__vid3d.meta", 20000)
    room = pg.evaluate("window.__vid3d.meta.room")
    sides = sorted([room["length_m"], room["width_m"]])
    # 5 measured runs: long side +2, +3, +2, +3 and +7 %, short side +1 to +5 %. The camera solver differs from run to run, so the gate is 8 %.
    assert abs(sides[0] - 4.0) <= 0.32 and abs(sides[1] - 5.0) <= 0.40, f"room {sides} is not within 8% of 4.0 x 5.0 m"
    rg = pg.evaluate("window.__vid3d.meta.uncertainty.ranges.area_m2")
    assert rg[0] <= 20.0 and (rg[1] is None or rg[1] >= 20.0), f"area range {rg} should contain the true 20 m2"
    assert pg.evaluate("window.__vid3d.meta.video") == h264_video.name  # a file name only, never a path
    assert pg.evaluate("window.__vid3d.meta.scale_method").startswith("camera height given")
    posts = [r for r in seen if r[0] == "POST"]
    assert len(posts) == 1 and "/v1/sfm" in posts[0][1]
    assert posts[0][2] < 40_000_000 and posts[0][2] < h264_video.stat().st_size * 20  # pictures, not the video
    shot(pg, "desktop-hybrid-scene")
    srv.shutdown()
    assert gpu_desktop.errors == [], gpu_desktop.errors


def test_hosted_hybrid_says_so_when_the_server_is_not_there(desktop, hosted_url, h264_video):
    pg = desktop.page
    pg.goto(hosted_url)
    pg.click("#advanced summary")
    pg.fill("#opt-server", "http://127.0.0.1:9")
    pg.set_input_files("#file", str(h264_video))
    pg.wait_for_selector("#consent", state="visible", timeout=240000)
    pg.click("#consent-send")
    pg.wait_for_selector("#prog-error", state="visible", timeout=60000)
    assert "Could not reach the server at 127.0.0.1:9" in pg.inner_text("#prog-error-msg")


def test_hosted_hybrid_consent_can_be_refused_and_nothing_is_sent(desktop, hosted_url, h264_video):
    pg = desktop.page
    sent = []
    pg.on("request", lambda r: sent.append(r) if r.method == "POST" else None)
    pg.goto(hosted_url)
    pg.set_input_files("#file", str(h264_video))
    pg.wait_for_selector("#consent", state="visible", timeout=240000)
    pg.click("#consent-cancel")
    pg.wait_for_selector("#start", state="visible")
    assert sent == []


def test_hosted_rejects_a_bad_file_with_a_message(desktop, hosted_url, tmp_path):
    bad = tmp_path / "cloud.ply"
    bad.write_text("hello")
    desktop.page.goto(hosted_url)
    desktop.page.set_input_files("#file", str(bad))
    desktop.page.wait_for_selector("#start-error", state="visible")
    assert "doesn't look like a .ply" in desktop.page.inner_text("#start-error")


def test_keyboard_reaches_everything_and_shortcuts_work(desktop, hosted_url):
    pg = desktop.page
    pg.goto(hosted_url)
    until(pg, "document.documentElement.dataset.mode === 'hosted'")  # the page has wired its handlers (slower on CI)
    pg.keyboard.press("Tab")
    assert pg.evaluate("document.activeElement.className") == "skip"
    pg.keyboard.press("Enter")
    # the drop zone opens with the keyboard too
    pg.focus("#drop")
    try:
        with pg.expect_file_chooser(timeout=10000):
            pg.keyboard.press("Enter")
    except Exception as e:  # report what the page was doing: on CI this is the only evidence available
        state = pg.evaluate("({active: document.activeElement && (document.activeElement.id || document.activeElement.tagName), "
                            "mode: document.documentElement.dataset.mode, accept: document.getElementById('file').accept, "
                            "hidden: document.getElementById('start').hidden})")
        raise AssertionError(f"no file chooser after Enter on #drop: {state}; page errors: {desktop.errors}; {str(e)[:120]}") from e
    open_sample(desktop, hosted_url)
    for key, btn in (("m", "#tool-measure"), ("p", "#tool-pick")):
        pg.keyboard.press(key)
        assert pg.get_attribute(btn, "aria-pressed") == "true"
    pg.keyboard.press("Escape")
    assert pg.get_attribute("#tool-pick", "aria-pressed") == "false"
    # every control shows a visible focus ring
    pg.focus("#tool-reset")
    assert pg.evaluate("getComputedStyle(document.activeElement).outlineStyle") == "solid"
    # typing in a field must not trigger shortcuts
    pg.focus("#true-len")
    pg.keyboard.type("m")
    assert pg.get_attribute("#tool-measure", "aria-pressed") == "false"


def test_phone_layout_fits_and_targets_are_big_enough(phone, hosted_url):
    pg = phone.page
    pg.goto(hosted_url)
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390  # no sideways scroll
    shot(pg, "phone-landing")
    pg.click("#sample-btn")
    until(pg, "window.__vid3d && window.__vid3d.meta", 20000)
    pg.wait_for_timeout(600)
    assert pg.is_hidden("#panel")  # the details sheet starts closed on a phone
    boxes = pg.evaluate("[...document.querySelectorAll('.toolbar .btn')].map(b => { const r = b.getBoundingClientRect(); return [r.width, r.height]; })")
    assert all(h >= 44 for _, h in boxes)
    bar = pg.evaluate("(() => { const r = document.querySelector('.toolbar').getBoundingClientRect(); return [r.left, r.right]; })()")
    assert bar[0] >= 0 and bar[1] <= 390
    assert pg.evaluate("(() => { const t = document.querySelector('.toolbar'); return t.scrollWidth <= t.clientWidth + 1; })()"), "toolbar buttons are clipped"
    shot(pg, "phone-scene")
    pg.tap("#tool-panel")
    assert pg.is_visible("#panel")
    pg.wait_for_timeout(700)  # let the panel's fade-in finish before measuring and screenshotting
    sizes = pg.evaluate("[...document.querySelectorAll('#panel button, #panel select, #panel input')].filter(e => e.offsetParent && e.type !== 'checkbox' && e.type !== 'range').map(e => e.getBoundingClientRect().height)")
    assert sizes and min(sizes) >= 43.5
    shot(pg, "phone-details")
    # a tap picks a colour on a phone
    pg.tap("#tool-panel")
    pg.tap("#tool-pick")
    a, _ = points_on_screen(phone, [20, 110, 370, 700])
    pg.touchscreen.tap(a["x"], a["y"])
    pg.wait_for_selector("#pick-readout", state="attached")
    assert pg.inner_text("#pick-hex") == "#{:02x}{:02x}{:02x}".format(*a["rgb"])
    assert phone.errors == []


# ---------- local mode (vid3d serve) ----------

def short_video(path, seconds=1):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (160, 120))
    for _ in range(30 * seconds):
        vw.write(np.zeros((120, 160, 3), np.uint8))
    vw.release()


def test_local_mode_offers_upload_and_advanced_options(desktop, local_url):
    pg = desktop.page
    pg.goto(local_url)
    until(pg, "document.documentElement.dataset.mode === 'local'")
    assert "Drop a video here" in pg.inner_text("#drop")
    pg.click("#advanced summary")
    assert all(pg.is_visible(i) for i in ("#opt-camera", "#opt-ceiling", "#opt-fov"))
    assert desktop.errors == []


def test_local_mode_explains_a_too_short_video(desktop, local_url, tmp_path):
    clip = tmp_path / "short.mp4"
    short_video(clip)
    pg = desktop.page
    pg.goto(local_url)
    pg.set_input_files("#file", str(clip))
    pg.wait_for_selector("#prog-error", state="visible", timeout=60000)
    assert "only 1.0 seconds long" in pg.inner_text("#prog-error-msg")
    assert pg.is_visible("#again-btn") and pg.is_hidden("#cancel-btn")
    assert pg.locator("#stage-list li[data-status='error']").count() == 1
    assert "Stopped at stage 1 of 6" in pg.inner_text("#prog-summary")
    shot(pg, "desktop-error")
    pg.click("#again-btn")
    assert pg.is_visible("#drop")


def test_local_mode_can_cancel_a_running_job(desktop, local_url):
    if not VIDEO.exists():
        pytest.skip("run scripts/make_synthetic_room.py first")
    pg = desktop.page
    pg.goto(local_url)
    pg.set_input_files("#file", str(VIDEO))
    pg.wait_for_selector("#stage-list li[data-status='running']", timeout=60000)
    pg.click("#cancel-btn")
    pg.wait_for_selector("#drop", state="visible", timeout=30000)


def test_local_mode_end_to_end_with_live_progress(desktop, local_url):
    """Drop the synthetic video: every stage reports, then the scene opens by itself."""
    if os.environ.get("VID3D_E2E") != "1":
        pytest.skip("set VID3D_E2E=1 (about 3 minutes of real processing)")
    if not VIDEO.exists():
        pytest.skip("run scripts/make_synthetic_room.py first")
    pg = desktop.page
    snaps = []
    pg.on("response", lambda r: re.search(r"/api/jobs/[0-9a-f]{12}$", r.url) and snaps.append(r.json()))
    pg.goto(local_url)
    pg.click("#advanced summary")
    pg.fill("#opt-camera", "1.5")
    pg.set_input_files("#file", str(VIDEO))
    pg.wait_for_selector("#stage-list li", timeout=30000)
    # screenshot once the AI-depth stage shows live frame counts (the card has finished fading in by then)
    until(pg, "(document.querySelector('#stage-list li:nth-child(3) .stage-detail')?.textContent || '').includes('frame')", 300000)
    shot(pg, "desktop-progress")
    until(pg, "window.__vid3d && window.__vid3d.meta", 480000)

    seen = {n: {s["stages"][n - 1]["status"] for s in snaps} for n in range(1, 7)}
    for n in (2, 3):  # stage 1 takes under a second: faster than the page polls
        assert "running" in seen[n], f"stage {n} was never seen running: {seen}"
    final = snaps[-1]
    assert final["state"] == "done" and all(s["status"] == "done" for s in final["stages"])
    details = " | ".join(s["detail"] for s in final["stages"])
    assert re.search(r"\d+ frames kept", details) and re.search(r"\d+ of \d+ frames placed", details)
    assert re.search(r"frame \d+ of \d+", details) and re.search(r"[\d,]+ points", details)
    assert [s["elapsed"] for s in snaps] == sorted(s["elapsed"] for s in snaps) and final["elapsed"] > 30
    assert re.fullmatch(r"\d\.\d\d × \d\.\d\d m", pg.inner_text("#dims"))
    assert desktop.errors == []


def test_demo_shows_guided_steps_ranges_confidence_and_the_bad_capture(desktop, hosted_url):
    pg = desktop.page
    open_sample(desktop, hosted_url)
    assert pg.is_visible("#demo")
    assert pg.locator("#demo-steps li").count() == 6
    steps = pg.inner_text("#demo-steps")
    assert "5.0 × 4.0 m" in steps and "2.03" in steps  # expected values come from scene.json's truth
    stats = pg.inner_text("#stats")
    assert "Area range" in stats and " to " in stats
    assert pg.inner_text("#confidence").startswith("Confidence: ")
    assert pg.get_attribute("#confidence", "data-level") in ("high", "medium")

    # measure two points, calibrate: the matching steps tick and a before/after readout appears
    pg.keyboard.press("m")
    a, b = points_on_screen(desktop, [420, 120, 1400, 760])
    pg.mouse.click(a["x"], a["y"])
    pg.mouse.click(b["x"], b["y"])
    assert "done" in pg.get_attribute('#demo-steps [data-step="measure"]', "class")
    pg.fill("#true-len", "2.03")
    pg.click("#cal-btn")
    assert "done" in pg.get_attribute('#demo-steps [data-step="calibrate"]', "class")
    assert "Before:" in pg.inner_text("#cal-readout") and "After your calibration" in pg.inner_text("#cal-readout")
    shot(pg, "desktop-demo")

    # the deliberately bad capture: honest warnings, open-ended range, low confidence
    pg.click("#demo-switch")
    until(pg, "window.__vid3d.meta && window.__vid3d.meta.demo && window.__vid3d.meta.demo.kind === 'bad'", 20000)
    pg.wait_for_timeout(400)
    assert pg.inner_text("#dims").startswith("at least")
    assert pg.get_attribute("#confidence", "data-level") == "low"
    assert "never filmed" in pg.inner_text("#warnings")
    assert "at least" in pg.inner_text("#stats")
    assert pg.locator("#demo-steps li").count() == 3
    shot(pg, "desktop-demo-bad")
    pg.click("#demo-switch")
    until(pg, "window.__vid3d.meta.demo.kind === 'good'", 20000)
    assert desktop.errors == []


def test_floor_plan_downloads_as_svg_and_json_under_the_strict_csp(desktop, hosted_url, tmp_path):
    pg = desktop.page
    open_sample(desktop, hosted_url)
    assert pg.is_visible("#plan-export")
    with pg.expect_download() as d:
        pg.click("#plan-svg")
    svg = Path(d.value.path()).read_text()
    assert d.value.suggested_filename == "floorplan.svg" and svg.startswith("<svg") and "m²" in svg
    with pg.expect_download() as d:
        pg.click("#plan-json")
    data = json.loads(Path(d.value.path()).read_text())
    assert d.value.suggested_filename == "floorplan.json" and len(data["room"]["rect_m"]) == 4
    assert data["ranges"]["area_m2"][0] < data["room"]["area_m2"] < data["ranges"]["area_m2"][1]
