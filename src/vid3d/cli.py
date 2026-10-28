"""Command line: `vid3d process VIDEO` and `vid3d view RUN_DIR`."""

from __future__ import annotations

import argparse
import functools
import http.server
import webbrowser
from pathlib import Path

# shortcut: needs a source checkout (pip install -e .); ship viewer/ as package data to lift this.
VIEWER_DIR = Path(__file__).resolve().parents[2] / "viewer"


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the viewer at / and the run folder at /run/."""

    def __init__(self, *a, run_dir: Path, **kw):
        self.run_dir = run_dir
        super().__init__(*a, directory=str(VIEWER_DIR), **kw)

    def _host_ok(self) -> bool:
        # Block DNS rebinding: a web page on evil.com that re-points its name at
        # 127.0.0.1 still sends "Host: evil.com", so only accept local names.
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def send_head(self):
        if not self._host_ok():
            self.send_error(421, "Misdirected Request")
            return None
        return super().send_head()

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/run/"):
            target = (self.run_dir / clean[len("/run/"):]).resolve()
            if self.run_dir.resolve() in target.parents:
                return str(target)
            return str(self.run_dir / "__forbidden__")
        return super().translate_path(path)

    def log_message(self, *a):
        pass


def view(run_dir: Path, port: int, open_browser: bool = True) -> None:
    if not (run_dir / "cloud.ply").exists():
        raise SystemExit(f"No cloud.ply in {run_dir}. Run `vid3d process` first.")
    handler = functools.partial(_Handler, run_dir=run_dir)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"Viewer running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="vid3d", description="Turn a walkthrough video into a measurable 3D model.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("process", help="video -> 3D point cloud + room estimate")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, help="output folder (default: runs/<video name>)")
    p.add_argument("--frames", type=int, default=80, help="frames to use (more = slower, more detail)")
    p.add_argument("--camera-height", type=float, help="phone height above floor in metres (default 1.45)")
    p.add_argument("--ceiling-height", type=float, help="known ceiling height in metres; most accurate scale")
    p.add_argument("--stride", type=int, default=4, help="pixel step for dense points (lower = denser)")
    p.add_argument("--fov", type=float, default=70.0,
                   help="starting guess for the lens's field of view across the long side (deg); ~70 for phone main camera, ~110 for ultra-wide")

    v = sub.add_parser("view", help="open the 3D viewer for a processed run")
    v.add_argument("run", type=Path)
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--no-browser", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "process":
        from .pipeline import process

        out = args.out or Path("runs") / args.video.stem
        process(args.video, out, n_frames=args.frames, camera_height=args.camera_height,
                ceiling_height=args.ceiling_height, stride=args.stride, fov=args.fov)
        print(f"\nView it:  vid3d view {out}")
    else:
        view(args.run, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
