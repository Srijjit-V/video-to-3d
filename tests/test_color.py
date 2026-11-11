import numpy as np
import pytest

from vid3d import color, floorplan
from vid3d.geometry import fuse
from vid3d.pipeline import write_ply


def solid(rgb, n=400):
    return np.tile(np.array(rgb, np.uint8), (n, 1))


def test_dominant_colors_finds_each_colour_and_its_share():
    pts = np.concatenate([solid((200, 30, 30), 600), solid((30, 30, 200), 200)])
    out = color.dominant_colors(pts, k=2)
    assert [c["hex"] for c in out] == ["#c81e1e", "#1e1ec8"]
    assert out[0]["share"] == pytest.approx(0.75, abs=0.01)
    assert sum(c["share"] for c in out) == pytest.approx(1.0, abs=0.01)


def test_dominant_colors_empty_when_too_few_points():
    assert color.dominant_colors(solid((1, 2, 3), 10)) == []


def room_cloud():
    """Box room: blue floor, cream walls, white ceiling, y up, 5 x 4 x 2.6 m."""
    rng = np.random.default_rng(0)
    pts, cols = [], []

    def add(p, c):
        pts.append(p)
        cols.append(np.tile(np.array(c, np.uint8), (len(p), 1)))

    xs, zs, ys = rng.uniform(0, 5, 3000), rng.uniform(0, 4, 3000), rng.uniform(0.3, 2.4, 3000)
    add(np.c_[xs, np.zeros(3000), zs], (40, 70, 160))  # floor
    add(np.c_[xs, np.full(3000, 2.6), zs], (250, 250, 250))  # ceiling
    add(np.c_[np.zeros(3000), ys, zs], (240, 225, 190))  # wall x=0
    add(np.c_[np.full(3000, 5.0), ys, zs], (240, 225, 190))  # wall x=5
    return np.concatenate(pts), np.concatenate(cols)


def test_palette_reports_wall_floor_and_ceiling_colours():
    P, C = room_cloud()
    room = {"rect_m": [0.0, 0.0, 5.0, 4.0]}
    pal = floorplan.palette(P, C, room, 2.6)
    assert pal["walls"][0]["hex"] == "#f0e1be"
    assert pal["floor"][0]["hex"] == "#2846a0"
    assert pal["ceiling"][0]["hex"] == "#fafafa"


def test_palette_has_no_ceiling_when_it_was_not_seen():
    P, C = room_cloud()
    pal = floorplan.palette(P, C, {"rect_m": [0.0, 0.0, 5.0, 4.0]}, None)
    assert pal["ceiling"] == []


def test_exposure_gains_even_out_frames_and_stay_gentle():
    gains = color.exposure_gains([60.0, 120.0, 180.0, 120.0])
    even = [l * g for l, g in zip([60.0, 120.0, 180.0, 120.0], gains, strict=True)]
    assert max(even) - min(even) < 180 - 60  # closer together than before
    assert all(color.GAIN_LIMITS[0] <= g <= color.GAIN_LIMITS[1] for g in gains)


def test_exposure_lifts_a_dark_clip():
    gains = color.exposure_gains([50.0, 52.0, 48.0])
    assert all(g > 1.2 for g in gains)


def test_normalize_frame_stretches_a_washed_out_frame_only():
    washed = np.random.default_rng(0).integers(110, 150, (50, 50, 3), dtype=np.uint8)
    out = color.normalize_frame(washed, 1.0)
    assert np.ptp(out.mean(axis=2)) > np.ptp(washed.mean(axis=2))
    contrasty = np.random.default_rng(1).integers(0, 256, (50, 50, 3), dtype=np.uint8)
    assert np.array_equal(color.normalize_frame(contrasty, 1.0), contrasty)


def test_view_count_survives_fusion_and_is_written_to_the_ply(tmp_path):
    P = np.concatenate([np.zeros((6, 3)), np.full((3, 3), 5.0)]).astype(np.float32)
    C = np.full((9, 3), 90, np.uint8)
    F = np.array([0, 1, 2, 0, 1, 2, 0, 1, 1], np.int32)  # first voxel: frames 0,1,2; second: 0,1
    pts, cols, views = fuse(P, C, F, voxel=1.0, min_views=2)
    assert sorted(views.tolist()) == [2, 3]
    path = tmp_path / "c.ply"
    write_ply(path, pts, cols, views)
    head, body = path.read_bytes().split(b"end_header\n", 1)
    assert b"property uchar views" in head
    assert len(body) == len(pts) * 16  # 3 floats + 3 colour bytes + 1 views byte
    assert body[15::16] == bytes(views[i] for i in range(len(pts)))
