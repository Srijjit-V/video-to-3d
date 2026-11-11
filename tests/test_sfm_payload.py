"""The sfm payload is the seam between 'camera poses' and everything after it (browser, server or CLI)."""

import numpy as np
import pytest

from vid3d.sfm_payload import MAX_OBS_PER_FRAME, payload_to_npz


def make(n=3, k1=0.0):
    frames = []
    for i in range(n):
        frames.append({"name": f"frame_{i:04d}.jpg", "R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0.1 * i, 0, 0],
                       "obs": [[10.5, 20.5, 2.0], [30.5, 40.5, 3.0]]})
    return {"version": 1, "camera": {"width": 640, "height": 480, "focal": 475.0, "cx": 320.0, "cy": 240.0, "k1": k1},
            "frames_total": n + 1, "reprojection_error_px": 0.4, "frames": frames}


def test_payload_becomes_the_npz_the_pipeline_reads(tmp_path):
    stats = payload_to_npz(make(), tmp_path)
    d = np.load(tmp_path / "sfm.npz")
    assert list(d["names"]) == ["frame_0000.jpg", "frame_0001.jpg", "frame_0002.jpg"]
    assert d["K"].shape == (3, 3, 3) and d["K"][0, 0, 0] == 475.0 and d["K"][0, 0, 2] == 320.0
    assert d["R"].shape == (3, 3, 3) and d["t"].shape == (3, 3)
    assert list(d["obs_offsets"]) == [0, 2, 4, 6] and d["obs"].shape == (6, 3)
    assert stats == {"frames_total": 4, "frames_registered": 3, "reprojection_error_px": 0.4}


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(version=2),
    lambda p: p["camera"].update(focal=float("nan")),
    lambda p: p["camera"].update(focal=-1),
    lambda p: p["frames"][0].update(R=[1, 0, 0]),
    lambda p: p["frames"][0].update(name="../evil.jpg"),
    lambda p: p["frames"][0]["obs"].append([1, 2]),
    lambda p: p["frames"][0].update(obs=[[1, 2, 3]] * (MAX_OBS_PER_FRAME + 1)),
    lambda p: p.update(frames=[]),
    lambda p: p["frames"][0].update(t=[0, 0, float("inf")]),
])
def test_untrusted_payloads_are_refused_before_anything_is_written(tmp_path, mutate):
    p = make()
    mutate(p)
    with pytest.raises(ValueError):
        payload_to_npz(p, tmp_path)
    assert not (tmp_path / "sfm.npz").exists()


def test_behind_camera_points_are_dropped(tmp_path):
    p = make(1)
    p["frames"][0]["obs"] = [[1.5, 2.5, -1.0], [3.5, 4.5, 2.0]]
    payload_to_npz(p, tmp_path)
    assert np.load(tmp_path / "sfm.npz")["obs"].shape == (1, 3)
