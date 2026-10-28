"""Point-cloud helpers: back-projection, fusion, floor finding, scale."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class View:
    name: str
    K: np.ndarray  # 3x3 intrinsics
    R: np.ndarray  # 3x3 world->camera rotation
    t: np.ndarray  # 3 world->camera translation
    width: int
    height: int

    @property
    def center(self) -> np.ndarray:
        return -self.R.T @ self.t

    @property
    def up(self) -> np.ndarray:
        """World direction of the image's 'up' (image y grows downward)."""
        return self.R.T @ np.array([0.0, -1.0, 0.0])


def project(view: View, X: np.ndarray):
    """World points -> pixel coords and camera depth."""
    Xc = X @ view.R.T + view.t
    z = Xc[:, 2]
    uv = (Xc @ view.K.T)[:, :2] / z[:, None]
    return uv, z


def undistort_radial(xy: np.ndarray, k1: float, iters: int = 6) -> np.ndarray:
    """Invert COLMAP's SIMPLE_RADIAL model on normalized coords: x_d = x_u (1 + k1 r_u^2)."""
    xu = xy.copy()
    for _ in range(iters):
        r2 = (xu**2).sum(1, keepdims=True)
        xu = xy / (1 + k1 * r2)
    return xu


def backproject(view: View, depth: np.ndarray, rgb: np.ndarray, stride: int = 4, k1: float = 0.0):
    """Dense depth map -> world points + colors (every `stride` pixels)."""
    vs, us = np.mgrid[0 : depth.shape[0] : stride, 0 : depth.shape[1] : stride]
    d = depth[vs, us]
    ok = np.isfinite(d)
    us, vs, d = us[ok], vs[ok], d[ok]
    pix = np.stack([us + 0.5, vs + 0.5, np.ones_like(d)], 1)
    norm = (pix @ np.linalg.inv(view.K).T)[:, :2]
    if k1:
        norm = undistort_radial(norm, k1)
    Xc = np.concatenate([norm, np.ones((len(d), 1))], 1) * d[:, None]
    Xw = (Xc - view.t) @ view.R
    return Xw.astype(np.float32), rgb[vs, us]


def fuse(points: np.ndarray, colors: np.ndarray, frame_ids: np.ndarray, voxel: float, min_views: int = 2):
    """Voxel-average the cloud, keeping only voxels seen from >= min_views frames.

    Requiring agreement between frames removes most single-frame depth errors.
    """
    keys = np.floor(points / voxel).astype(np.int64)
    keys -= keys.min(0)
    dims = keys.max(0) + 1
    flat = (keys[:, 0] * dims[1] + keys[:, 1]) * dims[2] + keys[:, 2]
    uniq, inv = np.unique(flat, return_inverse=True)

    n_frames = int(frame_ids.max()) + 1
    pair = np.unique(inv.astype(np.int64) * n_frames + frame_ids)
    views_per_voxel = np.bincount(pair // n_frames, minlength=len(uniq))

    cnt = np.bincount(inv, minlength=len(uniq)).astype(np.float64)
    P = np.stack([np.bincount(inv, points[:, i], len(uniq)) for i in range(3)], 1) / cnt[:, None]
    C = np.stack([np.bincount(inv, colors[:, i], len(uniq)) for i in range(3)], 1) / cnt[:, None]
    keep = views_per_voxel >= min_views
    return P[keep].astype(np.float32), C[keep].astype(np.uint8)


def ransac_plane(pts, thresh, iters=400, normal_hint=None, max_angle_deg=25.0, seed=0):
    """Best plane n·x + d = 0 (unit n). Optionally only planes near `normal_hint`."""
    rng = np.random.default_rng(seed)
    if len(pts) < 3:
        return None
    best = (None, None, 0)
    cos_lim = np.cos(np.radians(max_angle_deg))
    for _ in range(iters):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(b - a, c - a)
        nn = np.linalg.norm(n)
        if nn < 1e-12:
            continue
        n /= nn
        if normal_hint is not None:
            if np.dot(n, normal_hint) < 0:
                n = -n
            if np.dot(n, normal_hint) < cos_lim:
                continue
        d = -np.dot(n, a)
        count = int((np.abs(pts @ n + d) < thresh).sum())
        if count > best[2]:
            best = (n, d, count)
    if best[0] is None:
        return None
    n, d, _ = best
    # Least-squares refine on inliers.
    inl = pts[np.abs(pts @ n + d) < thresh]
    c = inl.mean(0)
    _, _, vt = np.linalg.svd(inl - c, full_matrices=False)
    n2 = vt[-1]
    if np.dot(n2, n) < 0:
        n2 = -n2
    return n2, -np.dot(n2, c), len(inl)


@dataclass
class FloorInfo:
    up: np.ndarray
    floor_d: float  # floor plane: up·x + floor_d = 0
    cam_height_raw: float  # median camera height above floor (reconstruction units)
    ceiling_height_raw: float | None


def _layer_peaks(h: np.ndarray, bin_w: float, min_frac: float = 0.3):
    """Heights of dense horizontal layers (floor, tabletops, ceiling) in a height histogram."""
    if len(h) < 50:
        return np.array([]), np.array([])
    bins = np.arange(h.min(), h.max() + 2 * bin_w, bin_w)
    cnt, edges = np.histogram(h, bins)
    cnt = np.convolve(cnt, [0.25, 0.5, 0.25], "same")
    is_peak = (cnt >= np.r_[cnt[1:], 0]) & (cnt >= np.r_[0, cnt[:-1]]) & (cnt >= min_frac * cnt.max())
    idx = np.nonzero(is_peak)[0]
    return edges[idx] + bin_w / 2, cnt[idx]


def _interior_fraction(layer: np.ndarray, walls: np.ndarray, up: np.ndarray, center: np.ndarray) -> float:
    """Share of `layer` points lying well inside the walls (seen from above).

    Ceiling points spread over the middle of the room; a band of wall texture
    at one height sits only at the edges.
    """
    def radial(p):
        q = p - center
        return np.linalg.norm(q - np.outer(q @ up, up), axis=1)

    if len(walls) < 20 or len(layer) == 0:
        return 0.0
    return float((radial(layer) < 0.6 * np.median(radial(walls))).mean())


def find_floor(points: np.ndarray, cam_centers: np.ndarray, up_hint: np.ndarray) -> FloorInfo:
    """Floor = lowest dense horizontal layer below the cameras.

    A plain RANSAC "biggest plane" can tilt to grab the floor plus the bottoms of
    walls. Instead: histogram point heights, take the lowest strong layer, fit a
    plane only to that layer, re-level with its normal, and repeat.
    """
    up = up_hint / np.linalg.norm(up_hint)
    h = points @ up
    extent = np.percentile(h, 99) - np.percentile(h, 1)
    bin_w = extent / 150
    d = None
    for _ in range(4):
        h = points @ up
        cam_h = float(np.median(cam_centers @ up))
        below = h < cam_h - 3 * bin_w
        peaks, _ = _layer_peaks(h[below], bin_w)
        if not len(peaks):
            raise RuntimeError("Could not find a floor. Make sure the floor is visible in the video.")
        layer = points[below & (np.abs(h - peaks.min()) < 3 * bin_w)]
        plane = ransac_plane(layer, bin_w, normal_hint=up, max_angle_deg=15)
        if plane is None:
            raise RuntimeError("Could not fit the floor plane.")
        new_up, d, _ = plane
        moved = np.degrees(np.arccos(np.clip(new_up @ up, -1, 1)))
        up = new_up
        if moved < 0.2:
            break

    cam_height = float(np.median(cam_centers @ up + d))
    if cam_height <= 0:
        raise RuntimeError("Floor detection failed (cameras below detected floor).")

    # Ceiling: highest dense layer above the cameras, if enough of it was seen.
    h = points @ up + d
    above = h > cam_height + 3 * bin_w
    ceiling = None
    floor_count = int((np.abs(h) < 2 * bin_w).sum())
    if above.sum() > 200:
        peaks, _ = _layer_peaks(h[above], bin_w, min_frac=0.5)
        if len(peaks):
            top = peaks.max()
            on_top = np.abs(h - top) < 2 * bin_w
            walls = points[np.abs(h - cam_height) < 3 * bin_w]  # eye-level ring = walls
            center = np.median(cam_centers, 0)
            # Real ceilings are >= ~2.1 m while a held phone is <= ~1.7 m.
            if top > 1.2 * cam_height and on_top.sum() > 0.1 * floor_count and \
                    _interior_fraction(points[on_top], walls, up, center) > 0.3:
                ceiling = float(top)
    return FloorInfo(up=up, floor_d=float(d), cam_height_raw=cam_height, ceiling_height_raw=ceiling)


def floor_frame(floor: FloorInfo, cam_centers: np.ndarray):
    """Rotation+origin that puts the floor at y=0 with +y up (three.js convention)."""
    y = floor.up
    # Pick x from the average camera viewing direction projected onto the floor.
    ref = np.array([1.0, 0, 0]) if abs(y[0]) < 0.9 else np.array([0, 0, 1.0])
    x = ref - y * np.dot(ref, y)
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    Rw = np.stack([x, y, z])  # rows: new axes
    c = cam_centers.mean(0)
    origin = c - y * (np.dot(y, c) + floor.floor_d)  # point on floor under the cameras
    return Rw, origin


def yaw_align(points_xz: np.ndarray, angle_deg: float):
    a = np.radians(angle_deg)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return points_xz @ R.T
