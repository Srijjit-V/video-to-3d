import numpy as np

from vid3d.geometry import View, backproject, find_floor, fuse, undistort_radial


def random_rotation(seed):
    q = np.random.default_rng(seed).normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def test_find_floor_recovers_up_and_heights_in_arbitrary_frame(room):
    # Put the room in a random pose and scale, like a raw COLMAP solve.
    R, s, shift = random_rotation(3), 0.37, np.array([4.0, -2.0, 7.0])
    cams_true = np.c_[np.linspace(1.5, 3.5, 30), np.full(30, 1.5), np.linspace(1.5, 2.5, 30)]
    to_raw = lambda p: (p @ R.T) * s + shift
    up_true = R @ np.array([0, 1.0, 0])
    noisy_hint = up_true + np.array([0.1, -0.05, 0.08])  # cameras are pitched, hint is off

    f = find_floor(to_raw(room), to_raw(cams_true), noisy_hint)
    assert np.degrees(np.arccos(f.up @ up_true)) < 1.0
    assert abs(f.cam_height_raw / s - 1.5) < 0.03
    assert f.ceiling_height_raw is not None
    assert abs(f.ceiling_height_raw / s - 2.6) < 0.05


def test_ceiling_not_reported_when_not_seen(room):
    no_ceiling = room[room[:, 1] < 2.0]  # walls only up to 2 m, no ceiling
    cams = np.c_[np.full(10, 2.5), np.full(10, 1.5), np.linspace(1.5, 2.5, 10)]
    f = find_floor(no_ceiling, cams, np.array([0, 1.0, 0]))
    assert f.ceiling_height_raw is None


def test_band_of_wall_texture_is_not_a_ceiling(room):
    # Regression: a stripe of wall detail at one height was once reported as the ceiling.
    walls = room[room[:, 1] < 2.55]
    on_wall = np.isclose(walls[:, 0], 0, atol=0.03) | np.isclose(walls[:, 0], 5, atol=0.03) | \
        np.isclose(walls[:, 2], 0, atol=0.03) | np.isclose(walls[:, 2], 4, atol=0.03)
    band = walls[on_wall & (np.abs(walls[:, 1] - 2.0) < 0.15)]
    pts = np.concatenate([walls] + [band] * 8)  # dense horizontal stripe at 2 m
    cams = np.c_[np.full(10, 2.5), np.full(10, 1.5), np.linspace(1.5, 2.5, 10)]
    f = find_floor(pts, cams, np.array([0, 1.0, 0]))
    assert f.ceiling_height_raw is None


def project(view: View, X: np.ndarray):
    """World points -> pixel coords and camera depth (test oracle for backproject)."""
    Xc = X @ view.R.T + view.t
    return (Xc @ view.K.T)[:, :2] / Xc[:, 2:3], Xc[:, 2]


def test_backproject_then_project_round_trip():
    K = np.array([[500.0, 0, 320], [0, 500, 240], [0, 0, 1]])
    v = View("a", K, random_rotation(1), np.array([0.1, -0.2, 0.3]), 640, 480)
    depth = np.full((480, 640), 2.0, np.float32)
    rgb = np.zeros((480, 640, 3), np.uint8)
    pts, _ = backproject(v, depth, rgb, stride=40)
    uv, z = project(v, pts)
    vs, us = np.mgrid[0:480:40, 0:640:40]
    assert np.allclose(z, 2.0, atol=1e-4)
    assert np.allclose(uv, np.c_[us.ravel() + 0.5, vs.ravel() + 0.5], atol=1e-3)


def test_undistort_radial_inverts_the_distortion():
    xu = np.random.default_rng(0).uniform(-0.6, 0.6, (100, 2))
    k1 = -0.08
    xd = xu * (1 + k1 * (xu**2).sum(1, keepdims=True))
    assert np.allclose(undistort_radial(xd, k1), xu, atol=1e-5)


def test_fuse_drops_points_seen_by_only_one_frame():
    good = np.zeros((10, 3))
    lone = np.full((5, 3), 10.0)
    P = np.concatenate([good, lone]).astype(np.float32)
    C = np.full((15, 3), 100, np.uint8)
    F = np.r_[np.arange(10) % 2, np.zeros(5)].astype(np.int32)
    out, _ = fuse(P, C, F, voxel=0.5, min_views=2)
    assert len(out) == 1 and np.allclose(out[0], 0)
