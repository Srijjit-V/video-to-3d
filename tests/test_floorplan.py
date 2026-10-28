import numpy as np
import pytest

from vid3d import floorplan
from vid3d.geometry import yaw_align


@pytest.mark.parametrize("angle", [0.0, 10.0, 23.0, 61.0])
def test_dominant_yaw_finds_wall_direction(room, angle):
    pts = room.copy()
    pts[:, [0, 2]] = yaw_align(pts[:, [0, 2]], angle)
    yaw = floorplan.dominant_yaw(pts, 2.6)
    # Walls repeat every 90 degrees, so compare modulo 90.
    diff = (yaw - angle + 45) % 90 - 45
    assert abs(diff) < 0.5


def test_analyze_measures_box_room(room):
    r = floorplan.analyze(room, 2.6)
    assert abs(r["length_m"] - 5.0) < 0.1
    assert abs(r["width_m"] - 4.0) < 0.1
    assert abs(r["area_m2"] - 20.0) < 1.0
    assert r["area_ft2"] == pytest.approx(r["area_m2"] * 10.7639, rel=0.01)


def test_analyze_flags_room_when_opposite_wall_missing(room):
    one_side = room[room[:, 2] < 0.3]  # only the z=0 wall strip
    r = floorplan.analyze(one_side, 2.6)
    assert r.get("incomplete") is True
    assert "length_m" not in r


def test_render_writes_png(room, tmp_path):
    r = floorplan.analyze(room, 2.6)
    cams = np.c_[np.linspace(1, 4, 20), np.full(20, 1.5), np.full(20, 2.0)]
    colors = np.full((len(room), 3), 128, np.uint8)
    out = tmp_path / "plan.png"
    floorplan.render(room, colors, cams, r, 2.6, out)
    assert out.stat().st_size > 1000
