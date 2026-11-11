"""Ranges and confidence: the stated range must contain the truth, and must not be uselessly wide."""

import numpy as np
import pytest

from conftest import box_room
from vid3d import floorplan, uncertainty
from vid3d.geometry import find_floor

TRUE_L, TRUE_W, TRUE_H, TRUE_CAM = 5.0, 4.0, 2.6, 1.5


def measured(assumed_cam, room=None):
    """The room as the pipeline would report it when it assumes `assumed_cam` but the phone was at 1.5 m."""
    room = box_room(TRUE_L, TRUE_W, TRUE_H) if room is None else room
    k = assumed_cam / TRUE_CAM  # every length is off by this factor
    return room * k, TRUE_H * k


def ranges_for(assumed_cam, method, **kw):
    pts, h = measured(assumed_cam)
    return uncertainty.estimate(pts, h, method, floor_sigma_rel=0.01, seed=kw.pop("seed", 0), **kw)


@pytest.mark.parametrize("true_cam", [1.3, 1.45, 1.5, 1.6])
def test_range_contains_the_truth_when_the_height_is_only_assumed(true_cam):
    # Phone really held at true_cam; the pipeline assumed 1.45 m.
    k = 1.45 / true_cam
    pts = box_room(TRUE_L, TRUE_W, TRUE_H) * k
    est = uncertainty.estimate(pts, TRUE_H * k, "camera held at ~1.45 m above floor (assumed)",
                               floor_sigma_rel=0.01, seed=1)
    lo, hi = est["ranges"]["length_m"]
    assert lo <= TRUE_L <= hi
    lo, hi = est["ranges"]["area_m2"]
    assert lo <= TRUE_L * TRUE_W <= hi


def test_range_is_tight_when_the_camera_height_is_given_and_right():
    est = ranges_for(1.5, "camera height given: 1.5 m")
    lo, hi = est["ranges"]["length_m"]
    assert lo <= TRUE_L <= hi
    assert (hi - lo) / TRUE_L < 0.12  # a range that wide would be useless; this one is about +-5%
    alo, ahi = est["ranges"]["area_m2"]
    assert alo <= TRUE_L * TRUE_W <= ahi


def test_better_scale_sources_give_narrower_ranges():
    width = {}
    for name, method in {"assumed": "camera held at ~1.45 m above floor (assumed)",
                         "given": "camera height given: 1.5 m",
                         "ceiling": "ceiling height = 2.6 m"}.items():
        lo, hi = ranges_for(1.5, method)["ranges"]["length_m"]
        width[name] = hi - lo
    assert width["assumed"] > width["given"] > width["ceiling"]


def test_area_error_is_about_twice_the_scale_error():
    # Derived in docs/MATH.md: A = L*W, both scale with s, so dA/A ~ 2 ds/s.
    est = ranges_for(1.5, "camera held at ~1.45 m above floor (assumed)")
    rel_l = np.diff(est["ranges"]["length_m"])[0] / est["central"]["length_m"]
    rel_a = np.diff(est["ranges"]["area_m2"])[0] / est["central"]["area_m2"]
    assert 1.7 < rel_a / rel_l < 2.3


def test_same_seed_gives_the_same_numbers():
    a = ranges_for(1.5, "camera height given: 1.5 m", seed=7)
    b = ranges_for(1.5, "camera height given: 1.5 m", seed=7)
    assert a == b


def test_a_sparse_wall_widens_the_range_instead_of_hiding_the_doubt():
    # One wall (z = 4) has only ~20% of the points of the others, right at the 30% wall threshold.
    room = box_room(TRUE_L, TRUE_W, TRUE_H, step=0.05)
    rng = np.random.default_rng(3)
    far = room[:, 2] > TRUE_W - 0.15
    keep = ~far | (rng.random(len(room)) < 0.2)
    est = uncertainty.estimate(room[keep], TRUE_H, "camera height given: 1.5 m", floor_sigma_rel=0.01, seed=2)
    lo, hi = est["ranges"]["width_m"]
    assert lo <= TRUE_W <= hi


def test_floor_height_spread_is_small_for_a_clean_floor_and_larger_when_noisy():
    rng = np.random.default_rng(0)
    base = box_room(TRUE_L, TRUE_W, TRUE_H)
    cams = np.array([[2.5, 1.5, 2.0], [2.0, 1.5, 2.5], [3.0, 1.5, 1.5]])
    up = np.array([0.0, 1.0, 0.0])
    clean = uncertainty.floor_sigma_rel(find_floor, base, cams, up, draws=8, seed=0)
    noisy_pts = base + rng.normal(0, 0.06, base.shape)
    noisy = uncertainty.floor_sigma_rel(find_floor, noisy_pts, cams, up, draws=8, seed=0)
    assert 0 <= clean < 0.03
    assert noisy >= clean


@pytest.mark.parametrize("spread,expected", [(0.03, False), (0.3, True)])
def test_camera_height_consistency_flags_a_phone_that_moved_up_and_down(spread, expected):
    heights = 1.45 * (1 + np.linspace(-spread, spread, 40))
    info = uncertainty.camera_height_consistency(heights)
    assert info["inconsistent"] is expected
    assert info["median_m"] == pytest.approx(1.45, rel=0.01)


def test_confidence_is_low_for_an_unmeasurable_room_and_high_for_a_good_one():
    good = uncertainty.confidence(
        method="camera height given: 1.5 m", registered_share=1.0, room={"rectangular": True, "wall_support": 0.97},
        area_half_width_rel=0.05, height_inconsistent=False)
    meh = uncertainty.confidence(
        method="camera held at ~1.45 m above floor (assumed)", registered_share=0.9,
        room={"rectangular": True, "wall_support": 0.97}, area_half_width_rel=0.16, height_inconsistent=False)
    bad = uncertainty.confidence(
        method="camera held at ~1.45 m above floor (assumed)", registered_share=0.5,
        room={"incomplete": True}, area_half_width_rel=None, height_inconsistent=False)
    assert good["label"] == "high" and meh["label"] == "medium" and bad["label"] == "low"
    assert good["score"] > meh["score"] > bad["score"]
    assert all(isinstance(r, str) and r for r in bad["reasons"])


def test_estimate_works_on_the_real_analyze_output(monkeypatch):
    pts, h = measured(1.5)
    room = floorplan.analyze(pts, h)
    est = uncertainty.estimate(pts, h, "camera height given: 1.5 m", floor_sigma_rel=0.01, seed=0)
    assert est["central"]["length_m"] == pytest.approx(room["length_m"], abs=0.1)


def test_a_missing_wall_gives_an_at_least_range_never_a_two_sided_one():
    half = box_room(TRUE_L, TRUE_W, TRUE_H)
    half = half[half[:, 2] < 2.2]  # the far wall (z = 4) was never filmed
    est = uncertainty.estimate(half, TRUE_H, "camera height given: 1.5 m", floor_sigma_rel=0.01, seed=0)
    r = est["ranges"]
    assert r["width_m"][1] is None and r["area_m2"][1] is None  # unbounded above: the room may be bigger
    assert r["width_m"][0] < TRUE_W  # and the lower end is below the truth
    assert r["length_m"][1] is not None and r["length_m"][0] <= TRUE_L <= r["length_m"][1]
    assert est["lower_bound_only"] == ["width_m", "area_m2"]


def test_confidence_is_low_when_a_wall_is_missing_even_with_everything_else_good():
    c = uncertainty.confidence("camera height given: 1.5 m", 1.0, {"missing_wall": True, "rectangular": False},
                               0.05, False)
    assert c["label"] == "low"
    assert any("never filmed" in r for r in c["reasons"])


def test_range_helpers_handle_open_ended_ranges():
    assert uncertainty.format_range([3.8, 4.2], "m") == "3.8 to 4.2 m"
    assert uncertainty.format_range([2.7, None], "m") == "at least 2.7 m"
    assert uncertainty.area_half_width_rel({"area_m2": [18.0, 22.0]}) == pytest.approx(0.1)
    assert uncertainty.area_half_width_rel({"area_m2": [9.8, None]}) is None
    assert uncertainty.area_half_width_rel(None) is None
