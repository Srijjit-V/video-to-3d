"""Hybrid-mode server: receives about 80 small JPEG frames, solves the camera path, returns a small sfm payload.

This is the only part of the system that needs COLMAP on a server. It has no torch: depth, fusion and measuring
happen on the user's device. It never receives the video, keeps nothing after the job and logs no image content.

    POST /v1/sfm?fov=70   body: a zip of .jpg frames (application/zip)   ->  200 JSON sfm payload (see sfm_payload.py)
    GET  /v1/health

Guards: body-size cap checked before reading, frame-count / resolution caps, files re-encoded (drops EXIF and GPS)
under server-made names, Origin allow-list, one job at a time (503 + Retry-After), a per-client minimum interval
(429), a hard job timeout, and a temporary folder that is always deleted.
Run: python -m vid3d.sfm_server --port 8787 --origin https://your-site.example
"""

from __future__ import annotations

import argparse
import http.server
import io
import json
import os
import shutil
import subprocess  # noqa: S404
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from .sfm_payload import npz_to_payload

Runner = Callable[[Path, Path, float], dict]


@dataclass(frozen=True)
class Limits:
    max_frames: int = 120
    min_frames: int = 3
    max_body: int = 40_000_000       # bytes of zip, checked from Content-Length before anything is read
    max_side: int = 1280             # pixels, long side of a frame (the browser sends 1024)
    min_side: int = 64
    min_interval_s: float = 20.0     # per client address between accepted jobs
    job_timeout_s: float = 900.0


def default_runner(frames_dir: Path, work: Path, fov: float, timeout: float = 900.0) -> dict:
    """pycolmap in its own process (the same step the CLI uses), then pack its result as a payload."""
    src_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(src_dir), PYTHONSAFEPATH="1")
    cmd = [sys.executable, "-P", "-m", "vid3d.sfm", str(frames_dir), str(work), str(fov)]
    try:
        r = subprocess.run(cmd, env=env, cwd=src_dir, stderr=subprocess.PIPE, text=True, timeout=timeout)  # noqa: S603
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("The camera solve took too long and was stopped. Try fewer frames.") from e
    if r.returncode != 0:
        said = [ln[6:] for ln in r.stderr.splitlines() if ln.startswith("error: ")]
        raise RuntimeError(said[-1] if said else "The camera solve failed. Try a different video.")
    return npz_to_payload(work / "sfm.npz", json.loads((work / "sfm_stats.json").read_text()))


class Refusal(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


def read_frames(body: bytes, out: Path, lim: Limits) -> int:
    """Validate the zip and write clean, re-encoded frames as frame_0000.jpg ... Names inside the zip are never used."""
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as e:
        raise Refusal(400, "That is not a zip of JPEG frames.") from e
    infos = sorted((i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith((".jpg", ".jpeg"))),
                   key=lambda i: i.filename)
    if len(infos) > lim.max_frames:
        raise Refusal(400, f"Too many frames: {len(infos)} (the limit is {lim.max_frames}).")
    if len(infos) < lim.min_frames:
        raise Refusal(400, f"Too few frames: send at least {lim.min_frames}.")
    if sum(i.file_size for i in infos) > 3 * lim.max_body:
        raise Refusal(400, "The frames are too large when unpacked.")
    size = None
    for n, info in enumerate(infos):
        raw = z.open(info).read(lim.max_body + 1)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise Refusal(400, "One of the files is not a readable JPEG.")
        h, w = img.shape[:2]
        if max(h, w) > lim.max_side:
            raise Refusal(400, f"Frames are too large: {w} x {h}. Resize to {lim.max_side} px or less.")
        if min(h, w) < lim.min_side:
            raise Refusal(400, "Frames are too small to use.")
        if size is None:
            size = (h, w)
        elif size != (h, w):
            raise Refusal(400, "All frames must be the same size.")
        cv2.imwrite(str(out / f"frame_{n:04d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])  # re-encoding drops EXIF/GPS
    return len(infos)


def make_server(host: str, port: int, runner: Runner = default_runner, allowed_origins: set[str] | None = None,
                limits: Limits | None = None, tmp_root: Path | None = None) -> http.server.ThreadingHTTPServer:
    lim = limits or Limits()
    origins = set(allowed_origins or ())
    lock = threading.Lock()
    last_seen: dict[str, float] = {}
    root = tmp_root

    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 60  # a stalled client must not hold a thread forever
        server_version = "vid3d-sfm"

        def log_message(self, *a):  # no request lines: nothing about users or their images is logged
            pass

        def _send(self, status: int, body: dict | None = None, extra: dict | None = None) -> None:
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin")
            if origin and origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _origin_ok(self) -> bool:
            o = self.headers.get("Origin")
            return o is None or o in origins  # no Origin = not a browser (CLI, curl); browsers must be on the list

        def do_OPTIONS(self):
            if not self._origin_ok() or self.headers.get("Origin") is None:
                return self._send(403, {"error": "Requests from this site are not allowed."})
            self._send(204, None, {"Access-Control-Allow-Methods": "POST, GET",
                                   "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600",
                                   "Access-Control-Allow-Private-Network": "true"})

        def do_GET(self):
            if urlparse(self.path).path == "/v1/health":
                return self._send(200, {"mode": "sfm-server"})
            self._send(404, {"error": "Not found."})

        def do_POST(self):
            url = urlparse(self.path)
            if url.path != "/v1/sfm":
                return self._send(404, {"error": "Not found."})
            if not self._origin_ok():
                return self._send(403, {"error": "Requests from other sites are not allowed."})
            try:
                self._handle(parse_qs(url.query))
            except Refusal as e:
                retry = {"Retry-After": str(e.retry_after)} if e.retry_after else None
                self._send(e.status, {"error": e.message}, retry)
            except Exception:  # noqa: BLE001 - never leak internals to a client
                self._send(500, {"error": "The server hit an unexpected problem. Try again later."})

        def _drain(self, length: int) -> None:
            """Discard a bounded amount of the body so the client can read our refusal, not a reset."""
            left = min(length, 2 * lim.max_body)
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
            self.close_connection = True

        def _handle(self, q: dict) -> None:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as e:
                raise Refusal(411, "A Content-Length header is required.") from e
            if length > lim.max_body:
                self._drain(length)
                raise Refusal(413, f"The upload is too large (limit {lim.max_body // 1_000_000} MB). "
                              "Send resized frames, not the video.")
            try:
                fov = float(q.get("fov", ["70"])[0])
            except ValueError as e:
                raise Refusal(400, "fov must be a number.") from e
            if not 20 <= fov <= 140:
                raise Refusal(400, "fov must be between 20 and 140 degrees.")
            client = self.client_address[0]
            now = time.monotonic()
            if now - last_seen.get(client, -1e9) < lim.min_interval_s:
                wait = int(lim.min_interval_s - (now - last_seen[client])) + 1
                self._drain(length)
                raise Refusal(429, f"Please wait {wait} s before sending another job.", wait)
            if not lock.acquire(blocking=False):
                self._drain(length)
                raise Refusal(503, "The server is busy with another job. Try again in a minute.", 60)
            try:
                last_seen[client] = now
                if len(last_seen) > 10_000:  # bound memory: forget the oldest half
                    for k in sorted(last_seen, key=last_seen.__getitem__)[:5_000]:
                        last_seen.pop(k, None)
                body = self.rfile.read(length)
                tmp = Path(tempfile.mkdtemp(prefix="vid3d-sfm-", dir=root))
                try:
                    frames_dir, work = tmp / "frames", tmp / "work"
                    frames_dir.mkdir()
                    read_frames(body, frames_dir, lim)
                    del body
                    try:
                        payload = runner(frames_dir, work, fov)
                    except RuntimeError as e:
                        raise Refusal(422, str(e)) from e
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            finally:
                lock.release()
            self._send(200, payload)

    return http.server.ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    ap = argparse.ArgumentParser(description="vid3d camera-solve server (Hybrid mode)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--origin", action="append", default=[],
                    help="a site allowed to call this server from a browser (repeatable)")
    a = ap.parse_args()
    srv = make_server(a.host, a.port, allowed_origins=set(a.origin))
    print(f"vid3d sfm server on http://{a.host}:{a.port}  (browser origins: {a.origin or 'none'})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
