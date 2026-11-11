import functools
import http.server
import json
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from vid3d import server
from vid3d.server import Job, Jobs, ServeHandler, ViewHandler

# ---------- progress parsing (lines copied from a real run) ----------

REAL_LOG = """[1/6] extracting ~50 sharp frames
      50 frames kept
[2/6] solving camera path with COLMAP (separate process)
[sfm] extracting features
[sfm] matching all frame pairs (1225)
[sfm] solving camera poses
[sfm] {'frames_total': 50, 'frames_registered': 50, 'sparse_points': 9000}
      50/50 frames placed
[3/6] AI depth on 50 frames
      device: mps
      1/50
      2/50
[4/6] fusing into one point cloud
      96,191 points
[5/6] finding the floor and real-world scale
[6/6] floor plan + export""".splitlines()


def test_job_reports_each_stage_with_real_counts():
    job = Job("a" * 12, None)
    for line in REAL_LOG[:12]:
        job.feed(line)
    snap = {s["n"]: s for s in job.snapshot()["stages"]}
    assert [snap[n]["status"] for n in range(1, 7)] == ["done", "done", "running", "pending", "pending", "pending"]
    assert snap[1]["detail"] == "50 frames kept"
    assert snap[2]["detail"] == "50 of 50 frames placed"
    assert snap[3]["detail"] == "frame 2 of 50"
    for line in REAL_LOG[12:]:
        job.feed(line)
    snap = {s["n"]: s for s in job.snapshot()["stages"]}
    assert snap[4]["detail"] == "96,191 points"
    assert snap[6]["status"] == "running"


def test_job_keeps_the_pipeline_error_message():
    job = Job("a" * 12, None)
    job.feed("[1/6] extracting ~80 sharp frames")
    job.feed("error: The video is only 1.0 seconds long.")
    assert job.error == "The video is only 1.0 seconds long."


# ---------- running jobs (fake pipeline, so these take a moment, not minutes) ----------

def fake(script):
    return lambda video, job_dir, opts: [sys.executable, "-c", script.replace("DIR", str(job_dir))]


OK = ("import pathlib,sys;d=pathlib.Path('DIR');print('[1/6] go',flush=True);"
      "[(d/f).write_bytes(b'x') for f in ('cloud.ply','scene.json','floorplan.png')]")
FAIL = "import sys;print('[1/6] go',flush=True);print('error: nope, try a longer video');sys.exit(2)"
SLOW = "import time;print('[1/6] go',flush=True);time.sleep(30)"


def wait_for(job, states, timeout=10):
    end = time.time() + timeout
    while time.time() < end and job.state not in states:
        time.sleep(0.05)
    return job.state


def start(tmp_path, script):
    jobs = Jobs(tmp_path, command=fake(script))
    job = Job("b" * 12, tmp_path / ("b" * 12))
    job.dir.mkdir()
    jobs.start(job, job.dir / "video.mp4", {})
    return jobs, job


def test_finished_job_lists_its_files(tmp_path):
    _, job = start(tmp_path, OK)
    assert wait_for(job, {"done", "error"}) == "done"
    assert set(job.snapshot()["files"]) == {"cloud.ply", "scene.json", "floorplan.png"}


def test_failed_job_shows_the_plain_message_and_a_log(tmp_path):
    _, job = start(tmp_path, FAIL)
    assert wait_for(job, {"done", "error"}) == "error"
    snap = job.snapshot()
    assert snap["error"] == "nope, try a longer video"
    assert "error: nope, try a longer video" in snap["log"]


def test_cancel_stops_a_running_job(tmp_path):
    jobs, job = start(tmp_path, SLOW)
    time.sleep(0.3)
    assert jobs.cancel(job) is True
    assert wait_for(job, {"cancelled"}) == "cancelled"
    assert job.proc.wait(timeout=5) != 0
    assert jobs.cancel(job) is False  # nothing left to cancel


# ---------- http ----------

class Live:
    def __init__(self, handler):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.srv.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def call(self, path, method="GET", data=None, headers=None):
        h = {"Host": f"127.0.0.1:{self.port}"} | (headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def stop(self):
        self.srv.shutdown()


@pytest.fixture
def view_server(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "scene.json").write_text(json.dumps({"ok": 1}))
    (tmp_path / "secret.txt").write_text("nope")
    live = Live(functools.partial(ViewHandler, run_dir=run))
    yield live
    live.stop()


@pytest.fixture
def serve_server(tmp_path):
    jobs = Jobs(tmp_path / "jobs", command=fake(OK))
    (tmp_path / "jobs").mkdir()
    live = Live(functools.partial(ServeHandler, jobs=jobs))
    live.jobs = jobs
    yield live
    live.stop()


def test_viewer_server_serves_run_and_blocks_paths_outside_it(view_server):
    assert json.loads(view_server.call("/run/scene.json")[1]) == {"ok": 1}
    assert b"video-to-3d" in view_server.call("/index.html")[1].lower()
    assert view_server.call("/run/../secret.txt")[0] >= 400
    assert view_server.call("/run/%2e%2e/secret.txt")[0] >= 400


def test_foreign_host_header_is_refused_everywhere(view_server, serve_server):
    for live in (view_server, serve_server):
        for path in ("/run/scene.json", "/index.html", "/api/health"):
            assert live.call(path, headers={"Host": "evil.example:80"})[0] == 421
    assert serve_server.call("/api/jobs", "POST", b"x", {"Host": "evil.example:80"})[0] == 421
    assert view_server.call("/api/health", headers={"Host": f"localhost:{view_server.port}"})[0] == 200


def test_security_headers_are_sent(view_server):
    _, _, h = view_server.call("/index.html")
    assert "script-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff"


def test_health_tells_the_viewer_which_mode_it_is_in(view_server, serve_server):
    assert json.loads(view_server.call("/api/health")[1]) == {"mode": "view"}
    assert json.loads(serve_server.call("/api/health")[1]) == {"mode": "local"}


OCTET = {"Content-Type": "application/octet-stream"}


def test_upload_runs_a_job_and_serves_only_whitelisted_results(serve_server):
    code, body, _ = serve_server.call("/api/jobs?name=room.MOV&fov=80", "POST", b"fake video", OCTET)
    assert code == 202
    job_id = json.loads(body)["id"]
    wait_for(serve_server.jobs.jobs[job_id], {"done", "error"})
    snap = json.loads(serve_server.call(f"/api/jobs/{job_id}")[1])
    assert snap["state"] == "done" and snap["files"]["cloud.ply"] == f"jobs/{job_id}/cloud.ply"
    assert serve_server.call(f"/jobs/{job_id}/cloud.ply")[1] == b"x"
    assert serve_server.call(f"/jobs/{job_id}/video.mov")[0] == 404  # the original video is not exposed


@pytest.mark.parametrize("query,body,headers,code", [
    ("name=notes.txt", b"x", OCTET, 400),  # not a video
    ("name=a.mp4", b"x", {"Content-Type": "text/plain"}, 415),  # CSRF-safe content type required
    ("name=a.mp4&fov=900", b"x", OCTET, 400),
    ("name=a.mp4&camera_height=abc", b"x", OCTET, 400),
    ("name=a.mp4", b"x", OCTET | {"Origin": "https://evil.example"}, 403),
])
def test_upload_rejects_bad_requests_with_a_message(serve_server, query, body, headers, code):
    status, resp, _ = serve_server.call(f"/api/jobs?{query}", "POST", body, headers)
    assert status == code
    assert json.loads(resp)["error"]


def test_upload_rejects_an_empty_file_and_a_huge_one(serve_server, monkeypatch):
    assert serve_server.call("/api/jobs?name=a.mp4", "POST", b"", OCTET)[0] == 400
    monkeypatch.setattr(server, "MAX_UPLOAD", 3)
    assert serve_server.call("/api/jobs?name=a.mp4", "POST", b"12345", OCTET)[0] == 413


def test_only_one_video_is_processed_at_a_time(tmp_path):
    (tmp_path / "jobs").mkdir()
    jobs = Jobs(tmp_path / "jobs", command=fake(SLOW))
    live = Live(functools.partial(ServeHandler, jobs=jobs))
    try:
        first = live.call("/api/jobs?name=a.mp4", "POST", b"x", OCTET)
        assert first[0] == 202
        assert live.call("/api/jobs?name=b.mp4", "POST", b"x", OCTET)[0] == 409
        job = jobs.jobs[json.loads(first[1])["id"]]
        assert live.call(f"/api/jobs/{job.id}/cancel", "POST", b"", OCTET)[0] == 200
        assert wait_for(job, {"cancelled"}) == "cancelled"
    finally:
        live.stop()


# ---------- private files are removed when a job ends ----------

def _seed_private(job_dir):
    for name in ("frames", "work"):
        (job_dir / name).mkdir(parents=True)
        (job_dir / name / "x.bin").write_bytes(b"x")
    (job_dir / "video.mp4").write_bytes(b"x")


def _wait_finished(job, timeout=10):
    end = time.time() + timeout
    while time.time() < end and job.t1 is None:
        time.sleep(0.05)
    assert job.t1 is not None


@pytest.mark.parametrize("script,expect", [(OK, "done"), (FAIL, "error")])
def test_job_removes_frames_work_and_the_uploaded_video_when_it_ends(tmp_path, script, expect):
    jobs = Jobs(tmp_path, command=fake(script))
    job = Job("c" * 12, tmp_path / ("c" * 12))
    _seed_private(job.dir)
    jobs.start(job, job.dir / "video.mp4", {})
    _wait_finished(job)
    assert job.state == expect
    assert not (job.dir / "frames").exists() and not (job.dir / "work").exists()
    assert not (job.dir / "video.mp4").exists()


def test_cancelled_job_also_removes_private_files(tmp_path):
    jobs = Jobs(tmp_path, command=fake(SLOW))
    job = Job("d" * 12, tmp_path / ("d" * 12))
    _seed_private(job.dir)
    jobs.start(job, job.dir / "video.mp4", {})
    time.sleep(0.3)
    jobs.cancel(job)
    _wait_finished(job)
    assert not (job.dir / "frames").exists() and not (job.dir / "video.mp4").exists()
