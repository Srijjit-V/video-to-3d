"""Record docs/demo.gif: orbit the demo room, colour by height, top-down, then the bad capture.

Run: .venv/bin/python scripts/make_readme_gif.py   (needs Chrome and Playwright; output stays under ~3 MB)
"""

import functools
import http.server
import io
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
W = 720


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "viewer")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    frames: list[Image.Image] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=ARGS)
        pg = b.new_page(viewport={"width": 1440, "height": 900})

        def grab(n=1):
            for _ in range(n):
                im = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
                frames.append(im.resize((W, round(W * im.height / im.width)), Image.LANCZOS))

        def until(expr):
            for _ in range(200):
                if pg.evaluate(expr):
                    return
                pg.wait_for_timeout(100)
            raise TimeoutError(expr)

        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
        grab(3)
        pg.click("#sample-btn")
        until("window.__vid3d && window.__vid3d.meta")
        pg.wait_for_timeout(800)
        grab(4)
        pg.mouse.move(900, 450)
        pg.mouse.down()
        for i in range(10):  # slow orbit
            pg.mouse.move(900 - 40 * (i + 1), 450 + 3 * i)
            pg.wait_for_timeout(120)
            grab()
        pg.mouse.up()
        pg.select_option("#color-mode", "height")
        pg.wait_for_timeout(500)
        grab(4)
        pg.keyboard.press("t")
        pg.wait_for_timeout(900)
        grab(4)
        pg.click("#demo-switch")
        until("window.__vid3d.meta && window.__vid3d.meta.demo && window.__vid3d.meta.demo.kind === 'bad'")
        pg.wait_for_timeout(900)
        grab(6)
        b.close()
    srv.shutdown()
    pal = [f.quantize(96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    out = ROOT / "docs" / "demo.gif"
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=[220] * len(pal), loop=0, optimize=True)
    print(out, f"{out.stat().st_size / 1e6:.2f} MB, {len(pal)} frames")


if __name__ == "__main__":
    main()
