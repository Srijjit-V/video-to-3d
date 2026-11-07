"""Local web servers on 127.0.0.1.

`vid3d view RUN`  shows one finished run.
`vid3d serve`     lets you drop a video in the browser, runs the pipeline and shows live progress.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# shortcut: needs a source checkout (pip install -e .); ship viewer/ as package data to lift this.
VIEWER_DIR = Path(__file__).resolve().parents[2] / "viewer"
SRC_DIR = Path(__file__).resolve().parents[1]

MAX_UPLOAD = 2 * 1024**3  # bytes
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
RESULT_FILES = ("cloud.ply", "scene.json", "floorplan.png")
STAGES = ["Pick sharp frames", "Solve the camera path", "AI depth on each frame",
          "Fuse into one cloud", "Find the floor and scale", "Floor plan and export"]
LIMITS = {"fov": (20, 150), "camera_height": (0.3, 3.0), "ceiling_height": (1.5, 6.0)}

# Same-origin only: no inline scripts or styles, nothing from other sites except the Google Fonts files.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' blob: data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


# ---------- jobs ----------

class Job:
    """One pipeline run. Progress comes from the lines the pipeline really prints."""

    STAGE_RE = re.compile(r"^\[(\d)/6\] ")
    COUNT_RE = re.compile(r"^\s+(\d+)/(\d+)$")  # per-frame depth progress
    KEPT_RE = re.compile(r"^\s+(\d+) frames kept$")
    PLACED_RE = re.compile(r"^\s+(\d+)/(\d+) frames placed$")
    POINTS_RE = re.compile(r"^\s+([\d,]+) points$")
    ERROR_RE = re.compile(r"^error: (.*)")

    def __init__(self, job_id: str, directory: Path):
        self.id, self.dir = job_id, directory
        self.state = "running"  # running | done | error | cancelled
        self.stage = 0  # 1-6, 0 before the first line
        self.details: dict[int, str] = {}
        self.error: str | None = None
        self.tail: list[str] = []
        self.t0, self.t1 = time.time(), None
        self.proc: subprocess.Popen | None = None

    def feed(self, line: str) -> None:
        self.tail = (self.tail + [line])[-40:]
        if m := self.STAGE_RE.match(line):
            self.stage = int(m.group(1))
        elif m := self.ERROR_RE.match(line):
            self.error = m.group(1)
        elif m := self.KEPT_RE.match(line):
            self.details[1] = f"{m.group(1)} frames kept"
        elif m := self.PLACED_RE.match(line):
            self.details[2] = f"{m.group(1)} of {m.group(2)} frames placed"
        elif m := self.COUNT_RE.match(line):
            self.details[3] = f"frame {m.group(1)} of {m.group(2)}"
        elif m := self.POINTS_RE.match(line):
            self.details[4] = f"{m.group(1)} points"
        elif line.startswith("[sfm] ") and self.stage == 2 and "{" not in line:
            self.details[2] = line[6:]

    def snapshot(self) -> dict:
        stages = []
        for n, label in enumerate(STAGES, 1):
            if self.state == "done" or n < self.stage:
                status = "done"
            elif n == self.stage:
                status = {"running": "running", "error": "error", "cancelled": "cancelled"}[self.state]
            else:
                status = "pending"
            stages.append({"n": n, "label": label, "status": status, "detail": self.details.get(n, "")})
        out = {"id": self.id, "state": self.state, "stages": stages, "error": self.error,
               "elapsed": round((self.t1 or time.time()) - self.t0, 1)}
        if self.state == "done":
            out["files"] = {f: f"jobs/{self.id}/{f}" for f in RESULT_FILES if (self.dir / f).exists()}
        if self.state == "error":
            out["log"] = self.tail[-15:]
        return out


def pipeline_command(video: Path, job_dir: Path, opts: dict) -> list[str]:
    cmd = [sys.executable, "-P", "-m", "vid3d.cli", "process", str(video), "--out", str(job_dir)]
    for key, flag in (("camera_height", "--camera-height"), ("ceiling_height", "--ceiling-height"), ("fov", "--fov")):
        if opts.get(key) is not None:
            cmd += [flag, str(opts[key])]
    return cmd


class Jobs:
    """Runs one pipeline at a time (it needs most of the machine's memory)."""

    def __init__(self, root: Path, command=pipeline_command):
        self.root, self.command = root, command
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def busy(self) -> bool:
        return any(j.state == "running" for j in self.jobs.values())

    def start(self, job: Job, video: Path, opts: dict) -> None:
        env = dict(os.environ, PYTHONPATH=str(SRC_DIR), PYTHONSAFEPATH="1", PYTHONUNBUFFERED="1")
        job.proc = subprocess.Popen(self.command(video, job.dir, opts), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1, env=env, cwd=SRC_DIR,
                                    start_new_session=True)
        self.jobs[job.id] = job
        threading.Thread(target=self._watch, args=(job,), daemon=True).start()

    def _watch(self, job: Job) -> None:
        for line in job.proc.stdout:
            job.feed(line.rstrip("\n"))
        code = job.proc.wait()
        if job.state == "cancelled":
            pass
        elif code == 0 and all((job.dir / f).exists() for f in ("cloud.ply", "scene.json")):
            job.state = "done"
        else:
            job.state = "error"
            job.error = job.error or "Processing stopped unexpectedly. The details below may help."
        job.t1 = time.time()

    def cancel(self, job: Job) -> bool:
        if job.state != "running" or job.proc is None:
            return False
        job.state = "cancelled"
        try:
            os.killpg(job.proc.pid, signal.SIGTERM)  # the pipeline and its camera-solve child
        except ProcessLookupError:
            pass
        return True


# ---------- http ----------

class ViewHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the viewer at / and, for `vid3d view`, one run folder at /run/."""

    mode = "view"

    def __init__(self, *a, run_dir: Path | None = None, **kw):
        self.run_dir = run_dir
        super().__init__(*a, directory=str(VIEWER_DIR), **kw)

    # -- safety --
    def _host_ok(self) -> bool:
        # Block DNS rebinding: a web page on evil.com that re-points its name at
        # 127.0.0.1 still sends "Host: evil.com", so only accept local names.
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def send_head(self):
        if not self._host_ok():
            self.send_error(421, "Misdirected Request")
            return None
        return super().send_head()

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/health":
            if not self._host_ok():
                return self._json(421, {"error": "Misdirected request."})
            return self._json(200, {"mode": self.mode})
        super().do_GET()

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/run/") and self.run_dir:
            target = (self.run_dir / clean[len("/run/"):]).resolve()
            if self.run_dir.resolve() in target.parents:
                return str(target)
            return str(self.run_dir / "__forbidden__")
        return super().translate_path(path)

    def log_message(self, *a):
        pass


class ServeHandler(ViewHandler):
    """Adds upload, progress and cancel on top of the viewer."""

    mode = "local"
    JOB_FILE = re.compile(r"^/jobs/([0-9a-f]{12})/([a-z.]+)$")

    def __init__(self, *a, jobs: Jobs, **kw):
        self.jobs = jobs
        super().__init__(*a, run_dir=None, **kw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/jobs/"):
            if not self._host_ok():
                return self._json(421, {"error": "Misdirected request."})
            job = self.jobs.jobs.get(path.rsplit("/", 1)[-1])
            return self._json(200, job.snapshot()) if job else self._json(404, {"error": "No such job."})
        super().do_GET()

    def translate_path(self, path):
        m = self.JOB_FILE.match(path.split("?", 1)[0])
        if m and m.group(2) in RESULT_FILES:
            return str(self.jobs.root / m.group(1) / m.group(2))
        return super().translate_path(path)

    def do_POST(self):
        port = self.server.server_address[1]
        if not self._host_ok():
            return self._json(421, {"error": "Misdirected request."})
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            return self._json(403, {"error": "Requests from other sites are not allowed."})
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        if parts == ["api", "jobs"]:
            return self._upload(parse_qs(url.query))
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
            job = self.jobs.jobs.get(parts[2])
            if job is None:
                return self._json(404, {"error": "No such job."})
            return self._json(200, {"cancelled": self.jobs.cancel(job)})
        self._json(404, {"error": "Not found."})

    def _upload(self, q: dict) -> None:
        if self.headers.get("Content-Type") != "application/octet-stream":
            return self._json(415, {"error": "Send the video as application/octet-stream."})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json(411, {"error": "The upload size is missing."})
        if length <= 0:
            return self._json(400, {"error": "That file is empty."})
        if length > MAX_UPLOAD:
            return self._json(413, {"error": "That video is bigger than 2 GB. Trim it or lower the resolution."})
        ext = Path(q.get("name", ["video.mp4"])[0]).suffix.lower()
        if ext not in VIDEO_EXT:
            return self._json(400, {"error": "Please drop a video file (.mp4, .mov, .m4v, .webm, .avi or .mkv)."})
        opts = {}
        for key, (lo, hi) in LIMITS.items():
            if key in q and q[key][0] != "":
                try:
                    opts[key] = float(q[key][0])
                except ValueError:
                    return self._json(400, {"error": f"{key.replace('_', ' ').capitalize()} must be a number."})
                if not lo <= opts[key] <= hi:
                    return self._json(400, {"error": f"{key.replace('_', ' ').capitalize()} must be between {lo} and {hi}."})
        with self.jobs.lock:
            if self.jobs.busy():
                return self._json(409, {"error": "Another video is still being processed. Wait for it or cancel it."})
            job_id = uuid.uuid4().hex[:12]  # also the folder name, so /jobs/<id>/... maps straight to disk
            job = Job(job_id, self.jobs.root / job_id)
            job.dir.mkdir(parents=True)
            video = job.dir / f"video{ext}"
            left = length
            with open(video, "wb") as f:
                while left:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left:
                video.unlink()
                return self._json(400, {"error": "The upload was cut off. Please try again."})
            self.jobs.start(job, video, opts)
        self._json(202, {"id": job.id})
