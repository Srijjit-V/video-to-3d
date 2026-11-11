"""Phase 0 spike: Depth Anything V2 Small (q4f16) via transformers.js in real Chrome.

Measures capability flags, model download bytes and ms per frame on WebGPU and on WASM.
Run: .venv/bin/python scripts/spike/depth_spike.py     (network needed once for the model)
"""

import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TJS = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2/dist/transformers.min.js"
MODEL = "onnx-community/depth-anything-v2-small"

PAGE = f"""<!doctype html><meta charset=utf-8><body><img id=im src="/samples/preview.jpg">
<script type=module>
import {{ pipeline, env }} from "{TJS}";
window.run = async (device, dtype, n) => {{
  const out = {{ device, dtype }};
  const t0 = performance.now();
  const p = await pipeline("depth-estimation", "{MODEL}", {{ device, dtype }});
  out.load_ms = Math.round(performance.now() - t0);
  const url = document.getElementById("im").src;
  const times = [];
  for (let i = 0; i < n; i++) {{
    const t = performance.now();
    const r = await p(url);
    times.push(Math.round(performance.now() - t));
    out.shape = r.depth.dims || [r.depth.height, r.depth.width];
  }}
  out.ms_each = times;
  out.mb_downloaded = Math.round(performance.getEntriesByType("resource")
      .filter(e => /huggingface|hf\\.co/.test(e.name) && /onnx/.test(e.name))
      .reduce((s, e) => s + e.encodedBodySize, 0) / 1e5) / 10;
  return out;
}};
window.ready = true;
</script>"""


class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/spike.html":
            b = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            super().do_GET()

    def log_message(self, *a):
        pass


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    res = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=False, args=["--enable-unsafe-webgpu", "--enable-features=Vulkan"])
        pg = b.new_page()
        logs = []
        pg.on("console", lambda m: logs.append(m.text) if m.type in ("error", "warning") else None)
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/spike.html")
        pg.wait_for_function("window.ready === true", timeout=60000)
        res["browser"] = b.version
        res["capabilities"] = pg.evaluate("""async () => ({
          webgpu: !!navigator.gpu, webcodecs: typeof VideoDecoder !== 'undefined',
          memory_gb: navigator.deviceMemory ?? null, cores: navigator.hardwareConcurrency,
          adapter: navigator.gpu ? await navigator.gpu.requestAdapter().then(a => a ? (a.info?.description || a.info?.vendor || 'yes') : null) : null,
          crossOriginIsolated })""")
        res["runs"] = []
        for device in ("webgpu", "wasm"):
            try:
                res["runs"].append(pg.evaluate(f"window.run('{device}', 'q4f16', 4)"))
            except Exception as e:  # noqa: BLE001
                res["runs"].append({"device": device, "error": str(e)[:300]})
        res["console"] = logs[:5]
        b.close()
    srv.shutdown()
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
