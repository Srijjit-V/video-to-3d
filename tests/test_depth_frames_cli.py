
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


@pytest.mark.parametrize("total,target", [(120, 20), (159, 80)])
def test_extract_frames_never_exceeds_target(tmp_path, total, target):
    # 159 frames / target 80 used to keep all 159 (window rounded down to 1),
    # pushing past the all-pairs matching limit.
    video = tmp_path / "v.mp4"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 30, (160, 120))
    rng = np.random.default_rng(0)
    for _ in range(total):
        vw.write(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    vw.release()
    frames = extract_frames(video, tmp_path / "frames", target=target)
    assert 0.6 * target <= len(frames) <= target


def test_extract_frames_refuses_a_too_short_clip_in_plain_words(tmp_path):
    video = tmp_path / "short.mp4"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 30, (160, 120))
    for _ in range(30):  # one second
        vw.write(np.zeros((120, 160, 3), np.uint8))
    vw.release()
    with pytest.raises(RuntimeError, match="only 1.0 seconds long"):
        extract_frames(video, tmp_path / "frames", target=20)


def test_extract_frames_says_so_when_the_file_is_not_a_video(tmp_path):
    bad = tmp_path / "notes.mp4"
    bad.write_text("not a video")
    with pytest.raises(RuntimeError, match="could not be opened as a video"):
        extract_frames(bad, tmp_path / "frames")


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
    scene["scale_method"] = "camera held at ~1.45 m above floor (assumed)"
    assert any("Real-world scale" in x for x in quality_warnings(scene))
    scene["scale_method"] = "camera height given: 1.5 m"
    assert not any("Real-world scale" in x for x in quality_warnings(scene))



def _write_video(path, n, fps, size):
    w, h = size
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for _ in range(n):
        vw.write(np.zeros((h, w, 3), np.uint8))
    vw.release()


def test_extract_frames_refuses_a_video_that_is_too_long(tmp_path):
    video = tmp_path / "long.mp4"
    _write_video(video, 310, 1, (16, 16))  # 310 seconds
    with pytest.raises(RuntimeError, match="longer than"):
        extract_frames(video, tmp_path / "frames")
    assert not list((tmp_path / "frames").glob("*.jpg"))


def test_extract_frames_refuses_frames_bigger_than_4k(tmp_path):
    video = tmp_path / "huge.mp4"
    _write_video(video, 100, 30, (3840, 2200))  # 8.45 million pixels
    with pytest.raises(RuntimeError, match="too large"):
        extract_frames(video, tmp_path / "frames")


def test_extract_frames_stops_when_the_real_frame_count_passes_the_limit(tmp_path, monkeypatch):
    # The header can lie, so the decode loop has its own guard.
    from vid3d import frames

    video = tmp_path / "v.mp4"
    _write_video(video, 120, 30, (64, 48))
    monkeypatch.setattr(frames, "MAX_FRAMES", 50)

    real_capture = cv2.VideoCapture

    class LyingCapture:  # header says 0 frames, like a damaged or hostile file
        def __init__(self, path):
            self._cap = real_capture(path)

        def get(self, prop):
            return 0.0

        def __getattr__(self, name):
            return getattr(self._cap, name)

    monkeypatch.setattr(frames.cv2, "VideoCapture", LyingCapture)
    with pytest.raises(RuntimeError, match="more than 50 frames"):
        extract_frames(video, tmp_path / "frames")


@pytest.mark.parametrize("given", ["/Users/someone/Documents/home/room.mp4", "C:\\Users\\someone\\room.mp4",
                                   "runs/web/uploads/a1b2.mp4", "room.mp4"])
def test_scene_records_only_the_video_file_name(given):
    from pathlib import Path
    from vid3d.pipeline import video_label

    label = video_label(Path(given))
    assert label.endswith("room.mp4") or label.endswith("a1b2.mp4")
    assert "/" not in label and "\\" not in label and "someone" not in label


def test_clean_intermediates_removes_frames_and_work_but_keeps_results(tmp_path):
    from vid3d.pipeline import clean_intermediates

    for d in ("frames", "work"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "a.jpg").write_bytes(b"x")
    (tmp_path / "scene.json").write_text("{}")
    clean_intermediates(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scene.json"]


def test_depth_model_is_pinned_to_a_commit_and_safetensors(monkeypatch):
    import re
    from vid3d import depth

    assert re.fullmatch(r"[0-9a-f]{40}", depth.MODEL_REVISION)
    seen = []

    class Fake:
        def to(self, _):
            return self

        def eval(self):
            return self

    def fake_from_pretrained(cls, name, **kw):
        seen.append((name, kw))
        return Fake()

    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    monkeypatch.setattr(AutoImageProcessor, "from_pretrained", classmethod(fake_from_pretrained))
    monkeypatch.setattr(AutoModelForDepthEstimation, "from_pretrained", classmethod(fake_from_pretrained))
    depth.DepthModel(device="cpu")
    assert len(seen) == 2
    assert all(kw.get("revision") == depth.MODEL_REVISION for _, kw in seen)
    assert seen[1][1].get("use_safetensors") is True
