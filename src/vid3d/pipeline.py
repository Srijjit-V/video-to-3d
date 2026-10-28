"""End-to-end: video -> metric point cloud + room estimate + floor plan."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from . import floorplan
from .depth import DepthModel, align_disparity, metric_depth
from .frames import extract_frames
from .geometry import View, backproject, find_floor, floor_frame, fuse, yaw_align

DEFAULT_CAMERA_HEIGHT_M = 1.45  # typical height of a phone held while walking


def log(msg: str) -> None:
    print(msg, flush=True)


def load_views(npz_path: Path):
    d = np.load(npz_path)
    views, obs = [], []
    for i, name in enumerate(d["names"]):
        w, h = d["size"][i]
        views.append(View(str(name), d["K"][i], d["R"][i], d["t"][i], int(w), int(h)))
        a, b = d["obs_offsets"][i], d["obs_offsets"][i + 1]
        obs.append(d["obs"][a:b])
    return views, list(d["k1"]), obs, d["sparse_xyz"], d["sparse_rgb"]


def write_ply(path: Path, pts: np.ndarray, rgb: np.ndarray) -> None:
    rec = np.empty(len(pts), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                    ("r", "u1"), ("g", "u1"), ("b", "u1")])
    rec["x"], rec["y"], rec["z"] = pts.T
    rec["r"], rec["g"], rec["b"] = rgb.T
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(pts)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode())
        f.write(rec.tobytes())


def process(video: Path, out: Path, n_frames: int = 80, camera_height: float | None = None,
            ceiling_height: float | None = None, stride: int = 4, fov: float = 70.0) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    frames_dir, work = out / "frames", out / "work"

    log(f"[1/6] extracting ~{n_frames} sharp frames")
    extract_frames(video, frames_dir, target=n_frames)

    log("[2/6] solving camera path with COLMAP (separate process)")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    subprocess.run([sys.executable, "-m", "vid3d.sfm", str(frames_dir), str(work), str(fov)],
                   check=True, env=env)
    sfm_stats = json.loads((work / "sfm_stats.json").read_text())
    views, k1s, obs, sparse_xyz, sparse_rgb = load_views(work / "sfm.npz")

    log(f"[3/6] AI depth on {len(views)} frames")
    model = DepthModel()
    log(f"      device: {model.device}")
    all_p, all_c, all_f, fits = [], [], [], []
    for i, (v, k1, o) in enumerate(zip(views, k1s, obs)):
        rgb = cv2.cvtColor(cv2.imread(str(frames_dir / v.name)), cv2.COLOR_BGR2RGB)
        disp = model.disparity(rgb)
        u = np.clip(o[:, 0].astype(int), 0, disp.shape[1] - 1)
        vv = np.clip(o[:, 1].astype(int), 0, disp.shape[0] - 1)
        fit = align_disparity(disp[vv, u], o[:, 2])
        if fit is None:
            continue
        a, b, inl = fit
        z = o[:, 2]
        depth = metric_depth(disp, a, b, 0.5 * z.min(), 2.0 * np.percentile(z, 98))
        p, c = backproject(v, depth, rgb, stride=stride, k1=k1)
        all_p.append(p)
        all_c.append(c)
        all_f.append(np.full(len(p), i, np.int32))
        fits.append(inl)
        if (i + 1) % 10 == 0:
            log(f"      {i + 1}/{len(views)}")
    del model
    if not all_p:
        raise RuntimeError("Depth alignment failed on every frame.")

    log("[4/6] fusing into one point cloud")
    P, C, F = np.concatenate(all_p), np.concatenate(all_c), np.concatenate(all_f)
    median_z = float(np.median(np.concatenate([o[:, 2] for o in obs])))
    P, C = fuse(P, C, F, voxel=median_z / 200, min_views=2)
    log(f"      {len(P):,} points")

    log("[5/6] finding the floor and real-world scale")
    cams = np.array([v.center for v in views])
    up_hint = np.mean([v.up for v in views], 0)
    floor = find_floor(P, cams, up_hint)
    Rw, origin = floor_frame(floor, cams)
    if ceiling_height and floor.ceiling_height_raw:
        scale, method = ceiling_height / floor.ceiling_height_raw, f"ceiling height = {ceiling_height} m"
    else:
        h = camera_height or DEFAULT_CAMERA_HEIGHT_M
        scale, method = h / floor.cam_height_raw, f"camera held at ~{h} m above floor"
        if ceiling_height:
            method += " (ceiling not detected, so --ceiling-height was ignored)"

    def to_metric(X):
        return ((X - origin) @ Rw.T) * scale

    P, cams_m = to_metric(P), to_metric(cams)
    room_h = floor.ceiling_height_raw * scale if floor.ceiling_height_raw else None

    # Rotate around the vertical axis so walls line up with x/z.
    yaw = floorplan.dominant_yaw(P, room_h)
    P[:, [0, 2]] = yaw_align(P[:, [0, 2]], -yaw)
    cams_m[:, [0, 2]] = yaw_align(cams_m[:, [0, 2]], -yaw)

    log("[6/6] floor plan + export")
    room = floorplan.analyze(P, room_h) or {"incomplete": True, "reason": "Too few wall points to measure the room."}
    floorplan.render(P, C, cams_m, room, room_h, out / "floorplan.png")
    write_ply(out / "cloud.ply", P, C)

    scene = {
        "video": str(video),
        "scale_method": method,
        "frames_extracted": sfm_stats["frames_total"],
        "frames_registered": sfm_stats["frames_registered"],
        "frames_with_depth": len(fits),
        "sfm_reprojection_error_px": round(sfm_stats["reprojection_error_px"], 3),
        "mean_depth_fit_inliers": round(float(np.mean(fits)), 3),
        "points": int(len(P)),
        "cameras": np.round(cams_m, 3).tolist(),
        "room": room,
        "seconds": round(time.time() - t0, 1),
    }
    scene["warnings"] = quality_warnings(scene)
    (out / "scene.json").write_text(json.dumps(scene, indent=2))
    log(f"done in {scene['seconds']} s -> {out}")
    if room.get("length_m"):
        log(f"room ≈ {room['length_m']} x {room['width_m']} m"
            + (f", height {room['height_m']} m" if room.get("height_m") else "")
            + f", area ≈ {room['area_m2']} m² ({room['area_ft2']} ft²)")
    for w in scene["warnings"]:
        log(f"warning: {w}")
    return scene


def quality_warnings(scene: dict) -> list[str]:
    """Plain-language reasons the numbers may be off."""
    w = []
    placed = scene["frames_registered"] / max(1, scene["frames_extracted"])
    if placed < 0.8:
        w.append(f"Only {scene['frames_registered']} of {scene['frames_extracted']} frames could be placed; "
                 "parts of the room may be missing. Try a slower, steadier video.")
    if scene["frames_with_depth"] < 0.7 * scene["frames_registered"]:
        w.append("AI depth could not be matched on many frames; the model may be patchy.")
    if scene["room"].get("incomplete"):
        w.append(scene["room"]["reason"])
    if "camera held" in scene["scale_method"]:
        w.append("Real-world scale is a guess from typical phone height (about ±5–10%). "
                 "Use --camera-height, --ceiling-height or calibrate in the viewer to tighten it.")
    return w
