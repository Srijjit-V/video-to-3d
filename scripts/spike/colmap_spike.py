"""Phase 0 spike: colmap-wasm (global SfM) on the synthetic room's frames, in real Chrome.

Writes scripts/spike/_work/sfm_wasm.json (camera poses + per-frame sparse observations u, v, z).
Run: .venv/bin/python scripts/spike/colmap_spike.py   (frames: see docs/VERIFICATION.md, "Phase 0")
"""

import functools
import http.server
import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

WORK = Path(__file__).resolve().parent / "_work"

PAGE = """<!doctype html><meta charset=utf-8><body><script type=module>
import { estimatePoses, sequentialPairs } from "/node_modules/colmap-wasm/dist/index.js";
window.run = async (names, seq) => {
  const files = [];
  for (const n of names) files.push(new File([await (await fetch("/frames/" + n)).blob()], n, { type: "image/jpeg" }));
  const t0 = performance.now(), stages = {};
  const { reconstruction: rec, features, timings } = await estimatePoses(files, {
    ...(seq ? { pairs: sequentialPairs(files.length, { window: 8, loop: true }) } : {}),
    onProgress: ({ stage, done, total }) => { stages[stage] = [done, total]; },
  });
  const wall = performance.now() - t0;
  const cam = rec.camera, obs = [];
  const frames = rec.images.map((im, i) => ({ i, name: im.name, registered: im.registered, R: im.R && Array.from(im.R), t: im.t, obs: [] }));
  for (const p of rec.points) for (const [ii, ki] of p.track) {
    const im = rec.images[ii]; if (!im.registered) continue;
    const R = im.R, t = im.t, X = p.xyz;
    const z = R[6] * X[0] + R[7] * X[1] + R[8] * X[2] + t[2];
    const kp = features[ii].keypoints;
    frames[ii].obs.push([kp[ki * 6], kp[ki * 6 + 1], z]);
  }
  return { wall_ms: Math.round(wall), timings, stages, camera: cam, points: rec.points.length,
           registered: rec.images.filter(i => i.registered).length, total: rec.images.length, frames };
};
window.ready = true;
</script>"""


class H(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        return super().translate_path(path)

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
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(WORK)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    names = sorted(p.name for p in (WORK / "frames").glob("*.jpg"))
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=False, args=["--enable-unsafe-webgpu"])
        pg = b.new_page()
        logs = []
        pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}"[:200]))
        pg.on("pageerror", lambda e: logs.append(f"pageerror: {e}"[:300]))
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/spike.html")
        pg.wait_for_function("window.ready === true", timeout=60000)
        try:
            res = pg.evaluate("([n, s]) => window.run(n, s)", [names, sys.argv[1:2] == ["seq"]])
        except Exception as e:  # noqa: BLE001
            print("FAILED:", str(e)[:500], logs[-8:])
            return
        b.close()
    srv.shutdown()
    (WORK / ("sfm_wasm_seq.json" if sys.argv[1:2] == ["seq"] else "sfm_wasm.json")).write_text(json.dumps(res))
    print({k: res[k] for k in ("wall_ms", "timings", "camera", "points", "registered", "total")})
    print("obs per frame (min/median/max):", sorted(len(f["obs"]) for f in res["frames"])[::max(1, len(res["frames"]) // 4)])
    print("console tail:", logs[-5:])


if __name__ == "__main__":
    main()
