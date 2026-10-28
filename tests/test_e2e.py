"""Full pipeline on the synthetic 5.0 x 4.0 m room. Slow (~3 min) and downloads the
depth model, so it only runs with VID3D_E2E=1."""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(os.environ.get("VID3D_E2E") != "1", reason="set VID3D_E2E=1 to run")


def test_synthetic_room_measures_within_6_percent(tmp_path):
    spec = importlib.util.spec_from_file_location("synth", ROOT / "scripts/make_synthetic_room.py")
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    video = tmp_path / "room.mp4"
    truth = synth.render_video(video)

    from vid3d.pipeline import process

    room = process(video, tmp_path / "run", camera_height=truth["camera_height_m"])["room"]
    got = sorted([room["length_m"], room["width_m"]])
    want = sorted([truth["length_m"], truth["width_m"]])
    for g, w in zip(got, want):
        assert abs(g - w) / w < 0.06, (got, want)
