import json
import threading
import urllib.error
import urllib.request

import cv2
import numpy as np
import pytest

from vid3d.depth import align_disparity, metric_depth
from vid3d.frames import extract_frames
from vid3d.pipeline import quality_warnings, write_ply


def test_align_disparity_recovers_fit_despite_outliers():
    rng = np.random.default_rng(0)
    z = rng.uniform(0.5, 5.0, 300)
    a, b = 0.8, 0.05
    disp = (1 / z - b) / a
    disp[:30] += rng.uniform(1, 3, 30)  # 10% bad matches
    fit = align_disparity(disp, z)
    assert fit is not None
    assert fit[0] == pytest.approx(a, rel=0.01)
    assert fit[1] == pytest.approx(b, abs=0.01)


def test_align_disparity_rejects_too_few_points():
    assert align_disparity(np.ones(5), np.ones(5)) is None


def test_metric_depth_masks_out_of_range():
    disp = np.full((20, 20), 1.0, np.float32)
    d = metric_depth(disp, 0.5, 0.0, 0.1, 10.0)  # 1/(0.5*1) = 2 m
    assert np.nanmax(np.abs(d - 2.0)) < 1e-5
    assert np.isnan(metric_depth(disp, 0.5, 0.0, 3.0, 10.0)).all()


def test_extract_frames_keeps_requested_count(tmp_path):
    video = tmp_path / "v.mp4"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 30, (160, 120))
    rng = np.random.default_rng(0)
    for _ in range(120):
        vw.write(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    vw.release()
    frames = extract_frames(video, tmp_path / "frames", target=20)
    assert 18 <= len(frames) <= 22


def test_write_ply_header_and_size(tmp_path):
    p = tmp_path / "c.ply"
    write_ply(p, np.zeros((7, 3), np.float32), np.zeros((7, 3), np.uint8))
    data = p.read_bytes()
    assert b"element vertex 7" in data
    assert len(data.split(b"end_header\n", 1)[1]) == 7 * 15


def test_quality_warnings_flag_few_frames():
    scene = {"frames_registered": 10, "frames_extracted": 60, "frames_with_depth": 10,
             "room": {}, "scale_method": "ceiling height = 2.6 m"}
    w = quality_warnings(scene)
    assert any("10 of 60" in x for x in w)
    assert not any("Real-world scale" in x for x in w)


def test_viewer_server_blocks_paths_outside_run(tmp_path):
    from vid3d import cli
    import functools
    import http.server

    run = tmp_path / "run"
    run.mkdir()
    (run / "scene.json").write_text(json.dumps({"ok": 1}))
    (tmp_path / "secret.txt").write_text("nope")
    handler = functools.partial(cli._Handler, run_dir=run)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert json.load(urllib.request.urlopen(base + "/run/scene.json")) == {"ok": 1}
        assert b"vid3d" in urllib.request.urlopen(base + "/index.html").read()
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/run/../secret.txt")
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/run/%2e%2e/secret.txt")
    finally:
        srv.shutdown()
