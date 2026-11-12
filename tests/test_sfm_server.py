"""The Hybrid-mode server: frames in, a small sfm payload out. Tests use a fake solver, plus one opt-in real run."""

import http.client
import io
import json
import os
import threading
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from vid3d.sfm_payload import npz_to_payload, payload_to_npz, validate
from vid3d.sfm_server import Limits, make_server

ROOT = Path(__file__).resolve().parents[1]


def jpeg(w=320, h=240, seed=0, exif=False, smooth=False):
    img = np.random.default_rng(seed).integers(0, 255, (h, w, 3), dtype=np.uint8)
    if smooth:  # a gradient compresses to a few KB, so a big picture still fits under the byte cap
        img = np.tile(np.linspace(0, 255, w, dtype=np.uint8)[None, :, None], (h, 1, 3))
    ok, buf = cv2.imencode(".jpg", img)
    data = buf.tobytes()
    if exif:  # splice a fake APP1/Exif segment (with a GPS-looking marker) right after the SOI marker
        seg = b"Exif\x00\x00GPSLatitudeRef" + b"\x00" * 8
        data = data[:2] + b"\xff\xe1" + (len(seg) + 2).to_bytes(2, "big") + seg + data[2:]
    return data


def make_zip(n=4, **kw):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for i in range(n):
            z.writestr(f"f{i}.jpg", jpeg(seed=i, **kw))
    return b.getvalue()


def fake_runner(frames_dir: Path, work: Path, fov: float) -> dict:
    names = sorted(p.name for p in frames_dir.glob("*.jpg"))
    return {"version": 1, "camera": {"width": 320, "height": 240, "focal": 300.0, "cx": 160.0, "cy": 120.0, "k1": 0.0},
            "frames_total": len(names), "reprojection_error_px": 0.3,
            "frames": [{"name": n, "R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0], "obs": [[1.5, 2.5, 2.0]]} for n in names]}


@pytest.fixture
def server(tmp_path):
    seen = {}

    def runner(frames_dir, work, fov):
        seen["files"] = sorted(p.name for p in frames_dir.iterdir())
        seen["dir"] = frames_dir
        seen["bytes"] = (frames_dir / seen["files"][0]).read_bytes()
        return fake_runner(frames_dir, work, fov)

    srv = make_server("127.0.0.1", 0, runner=runner, allowed_origins={"https://app.example"},
                      limits=Limits(max_frames=10, max_body=2_000_000, min_interval_s=0.0), tmp_root=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, seen, tmp_path
    srv.shutdown()


def post(srv, body, headers=None, path="/v1/sfm"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=300)
    h = {"Content-Type": "application/zip", **(headers or {})}
    c.request("POST", path, body=body, headers=h)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_frames_in_payload_out_and_nothing_left_behind(server):
    srv, seen, tmp = server
    status, _, body = post(srv, make_zip(4))
    assert status == 200
    p = json.loads(body)
    validate(p)
    assert [f["name"] for f in p["frames"]] == [f"frame_{i:04d}.jpg" for i in range(4)]  # server-made names
    assert list(tmp.iterdir()) == []  # the frames were deleted


def test_exif_and_gps_are_stripped_before_solving(server):
    srv, seen, _ = server
    assert b"GPSLatitudeRef" in jpeg(exif=True)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(3):
            zf.writestr(f"a{i}.jpg", jpeg(seed=i, exif=True))
    assert post(srv, z.getvalue())[0] == 200
    assert b"GPSLatitudeRef" not in seen["bytes"] and b"Exif" not in seen["bytes"]


@pytest.mark.parametrize("case", ["too_many", "not_zip", "not_jpeg", "traversal_name_is_ignored", "huge_image", "too_few"])
def test_bad_uploads_are_refused_in_plain_words(server, case):
    srv, _, tmp = server
    if case == "too_many":
        body = make_zip(11)
    elif case == "not_zip":
        body = b"hello"
    elif case == "not_jpeg":
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for i in range(3):
                z.writestr(f"x{i}.jpg", b"not an image")
        body = b.getvalue()
    elif case == "traversal_name_is_ignored":
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for i in range(3):
                z.writestr(f"../../evil{i}.jpg", jpeg(seed=i))
        body = b.getvalue()
    elif case == "huge_image":
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for i in range(3):
                z.writestr(f"h{i}.jpg", jpeg(w=3000, h=2000, seed=i, smooth=True))
        body = b.getvalue()
    else:
        body = make_zip(2)
    status, _, resp = post(srv, body)
    if case == "traversal_name_is_ignored":
        assert status == 200 and not list(tmp.iterdir()) and not (tmp.parent / "evil0.jpg").exists()
        return
    assert status == 400 and json.loads(resp)["error"]
    assert list(tmp.iterdir()) == []


def test_body_over_the_cap_is_refused_before_reading(server):
    srv, _, _ = server
    status, _, resp = post(srv, b"x" * 2_100_000)
    assert status == 413 and "too large" in json.loads(resp)["error"].lower()


def test_origin_is_checked_and_allowed_origin_gets_cors(server):
    srv, _, _ = server
    assert post(srv, make_zip(3), {"Origin": "https://evil.example"})[0] == 403
    status, hdr, _ = post(srv, make_zip(3), {"Origin": "https://app.example"})
    assert status == 200 and hdr["Access-Control-Allow-Origin"] == "https://app.example"
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    c.request("OPTIONS", "/v1/sfm", headers={"Origin": "https://app.example", "Access-Control-Request-Method": "POST"})
    r = c.getresponse()
    assert r.status == 204 and r.getheader("Access-Control-Allow-Origin") == "https://app.example"
    c.request("OPTIONS", "/v1/sfm", headers={"Origin": "https://evil.example"})
    assert c.getresponse().status == 403


def test_one_job_at_a_time_says_busy(tmp_path):
    gate, started = threading.Event(), threading.Event()

    def slow(frames_dir, work, fov):
        started.set()
        gate.wait(10)
        return fake_runner(frames_dir, work, fov)

    srv = make_server("127.0.0.1", 0, runner=slow, limits=Limits(min_interval_s=0.0), tmp_root=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    first = {}
    t = threading.Thread(target=lambda: first.update(r=post(srv, make_zip(3))))
    t.start()
    assert started.wait(10)
    status, hdr, body = post(srv, make_zip(3))
    assert status == 503 and "busy" in json.loads(body)["error"].lower() and "Retry-After" in hdr
    gate.set()
    t.join(10)
    assert first["r"][0] == 200
    srv.shutdown()


def test_per_client_rate_limit(tmp_path):
    srv = make_server("127.0.0.1", 0, runner=fake_runner, limits=Limits(min_interval_s=60.0), tmp_root=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    assert post(srv, make_zip(3))[0] == 200
    status, hdr, _ = post(srv, make_zip(3))
    assert status == 429 and "Retry-After" in hdr
    srv.shutdown()


def test_solver_failure_message_reaches_the_client_and_files_are_deleted(tmp_path):
    def boom(frames_dir, work, fov):
        raise RuntimeError("COLMAP only placed 3 of 10 frames. Try a steadier video.")

    srv = make_server("127.0.0.1", 0, runner=boom, limits=Limits(min_interval_s=0.0), tmp_root=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    status, _, body = post(srv, make_zip(3))
    assert status == 422 and "placed 3 of 10" in json.loads(body)["error"]
    assert list(tmp_path.iterdir()) == []
    srv.shutdown()


def test_unknown_paths_and_health(server):
    srv, _, _ = server
    assert post(srv, b"", path="/v1/other")[0] == 404
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    c.request("GET", "/v1/health")
    r = c.getresponse()
    assert r.status == 200 and json.loads(r.read())["mode"] == "sfm-server"


def test_npz_to_payload_round_trips(tmp_path):
    p = fake_runner(Path("."), tmp_path, 70)  # no frames on disk: build a payload by hand instead
    p["frames"] = [{"name": f"frame_{i:04d}.jpg", "R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0.1 * i, 0, 0],
                    "obs": [[10.5, 20.5, 2.0], [30.5, 40.5, 3.0]]} for i in range(3)]
    p["frames_total"] = 4
    stats = payload_to_npz(p, tmp_path)
    q = npz_to_payload(tmp_path / "sfm.npz", stats)
    validate(q)
    assert [f["name"] for f in q["frames"]] == [f["name"] for f in p["frames"]]
    assert np.allclose(q["frames"][1]["t"], [0.1, 0, 0]) and q["frames"][2]["obs"][1] == [30.5, 40.5, 3.0]
    assert q["camera"]["focal"] == 300.0 and q["frames_total"] == 4


@pytest.mark.skipif(os.environ.get("VID3D_E2E") != "1", reason="set VID3D_E2E=1 (runs real COLMAP, about 10 s)")
def test_real_colmap_on_the_synthetic_room(tmp_path):
    from vid3d.frames import extract_frames
    from vid3d.sfm_server import default_runner

    frames = extract_frames(ROOT / "samples" / "synthetic_room.mp4", tmp_path / "f", target=40)
    srv = make_server("127.0.0.1", 0, runner=default_runner, limits=Limits(min_interval_s=0.0), tmp_root=tmp_path / "t")
    (tmp_path / "t").mkdir()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for f in frames:
            z.writestr(f.name, f.read_bytes())
    status, _, body = post(srv, b.getvalue())
    srv.shutdown()
    assert status == 200
    p = json.loads(body)
    validate(p)
    assert len(p["frames"]) >= 0.8 * len(frames) and len(json.dumps(p)) < 1_500_000


def test_client_sends_frames_and_gets_a_valid_payload(server, tmp_path):
    from vid3d.sfm_client import solve_remote

    srv, _, _ = server
    d = tmp_path / "frames"
    d.mkdir()
    for i in range(4):
        (d / f"frame_{i:04d}.jpg").write_bytes(jpeg(seed=i))
    p = solve_remote(d, f"http://127.0.0.1:{srv.server_address[1]}", 70.0)
    validate(p)
    assert len(p["frames"]) == 4


def test_client_reports_the_servers_plain_message_and_refuses_odd_urls(server, tmp_path):
    from vid3d.sfm_client import solve_remote

    srv, _, _ = server
    d = tmp_path / "frames"
    d.mkdir()
    (d / "frame_0000.jpg").write_bytes(jpeg())
    with pytest.raises(RuntimeError, match="at least 3"):
        solve_remote(d, f"http://127.0.0.1:{srv.server_address[1]}", 70.0)
    for bad in ("file:///etc/passwd", "ftp://x", "javascript:alert(1)", ""):
        with pytest.raises(ValueError):
            solve_remote(d, bad, 70.0)
