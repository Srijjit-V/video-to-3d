"""Phase 0 evidence: what works in WebKit (the engine behind Safari) with this site, under the real security headers.
Playwright's WebKit is not Safari (no system codecs, no Apple GPU stack tweaks), so a pass is evidence, not a Safari support claim.
Run: .venv/bin/python scripts/spike/webkit_probe.py
"""

import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HEADERS = {h["key"]: h["value"] for r in json.loads((ROOT / "vercel.json").read_text())["headers"] if r["source"] == "/(.*)" for h in r["headers"]}


class Q(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        for k, v in HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def log_message(self, *a):
        pass


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(ROOT / "viewer")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    out = {}
    with sync_playwright() as p:
        for name, kw in (("webkit desktop", {"viewport": {"width": 1280, "height": 800}}), ("webkit iPhone 15", p.devices["iPhone 15"])):
            b = p.webkit.launch()
            ctx = b.new_context(**kw)
            pg = ctx.new_page()
            pg.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', e => window.__csp.push([e.violatedDirective, e.blockedURI, (e.sourceFile||'').slice(-40), e.lineNumber]));")
            errors = []
            pg.on("console", lambda m, e=errors: e.append(m.text[:160]) if m.type == "error" else None)
            pg.on("pageerror", lambda e, ee=errors: ee.append("pageerror: " + str(e)[:160]))
            pg.goto(url)
            pg.wait_for_timeout(1500)
            r = {"mode": pg.evaluate("document.documentElement.dataset.mode"),
                 "capabilities": pg.evaluate("({webgpu: !!navigator.gpu, webcodecs: typeof VideoDecoder !== 'undefined', webgl2: !!document.createElement('canvas').getContext('webgl2'), "
                                             "subtle: !!(crypto && crypto.subtle), worker: typeof Worker !== 'undefined', wasm: typeof WebAssembly !== 'undefined'})")}
            pg.click("#sample-btn")
            r["demo_scene_loads"] = False
            for _ in range(120):  # poll with evaluate: wait_for_function evaluates a string, which the CSP forbids
                if pg.evaluate("!!(window.__vid3d && window.__vid3d.meta)"):
                    pg.wait_for_timeout(800)
                    r["demo_scene_loads"] = True
                    r["dims"] = pg.inner_text("#dims")
                    break
                pg.wait_for_timeout(250)
            r["csp_violations"] = pg.evaluate("window.__csp")
            pg.click("#theme-btn") if pg.is_visible("#theme-btn") else None
            r["theme_after_toggle"] = pg.evaluate("document.documentElement.dataset.theme")
            r["console_errors"] = errors[:4]
            out[name] = r
            b.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
