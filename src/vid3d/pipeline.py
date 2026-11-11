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

from . import color, floorplan, uncertainty
from .depth import DepthModel, align_disparity, metric_depth
from .frames import extract_frames
from .geometry import View, backproject, find_floor, floor_frame, fuse, yaw_align
from .privacy import check_private_dirs, clean_intermediates
from .sfm_payload import load_payload, payload_to_npz

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
    return views, list(d["k1"]), obs


def write_ply(path: Path, pts: np.ndarray, rgb: np.ndarray, views: np.ndarray | None = None) -> None:
    """Binary little-endian PLY; `views` (frames that saw each point) is written as an extra property."""
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")]
    if views is not None:
        fields.append(("views", "u1"))
    rec = np.empty(len(pts), dtype=fields)
    rec["x"], rec["y"], rec["z"] = pts.T
    rec["r"], rec["g"], rec["b"] = rgb.T
    if views is not None:
        rec["views"] = views
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(pts)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        + ("property uchar views\n" if views is not None else "")
        + "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode())
        f.write(rec.tobytes())


def video_label(video: Path) -> str:
    """Only the file name goes into scene.json: a full path would leak the user's folders when it is shared."""
    return str(video).replace("\\", "/").rsplit("/", 1)[-1]


def process(video: Path, out: Path, n_frames: int = 80, camera_height: float | None = None,
            ceiling_height: float | None = None, stride: int = 4, fov: float = 70.0,
            keep_intermediate: bool = False, sfm_payload: Path | None = None) -> dict:
    """Run the six stages. The frames and COLMAP work folder are deleted at the end (success or
    failure) unless keep_intermediate is set: they are photos of the user's room."""
    out.mkdir(parents=True, exist_ok=True)
    check_private_dirs(out, keep_intermediate)
    try:
        return _process(video, out, n_frames, camera_height, ceiling_height, stride, fov, sfm_payload)
    finally:
        if not keep_intermediate:
            left = clean_intermediates(out)
            if left:
                log(f"warning: could not delete {', '.join(left)} in {out}; they contain photos of your room. "
                    "Delete them yourself.")


def _process(video: Path, out: Path, n_frames: int, camera_height: float | None,
             ceiling_height: float | None, stride: int, fov: float, sfm_payload: Path | None = None) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    frames_dir, work = out / "frames", out / "work"

    log(f"[1/6] extracting ~{n_frames} sharp frames")
    kept = extract_frames(video, frames_dir, target=n_frames)
    log(f"      {len(kept)} frames kept")

    if sfm_payload is not None:
        log("[2/6] camera path supplied as an sfm payload (solved elsewhere)")
        try:
            sfm_stats = payload_to_npz(load_payload(sfm_payload), work)
        except (ValueError, OSError) as e:
            raise RuntimeError(f"The camera-path payload was refused: {e}") from e
        (work / "sfm_stats.json").write_text(json.dumps(sfm_stats))
    else:
        log("[2/6] solving camera path with COLMAP (separate process)")
        # -P / PYTHONSAFEPATH: don't add the current folder to the import path, so a
        # stray file there (e.g. a "numpy.py") can't be imported in place of the real one.
        src_dir = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(src_dir), PYTHONSAFEPATH="1")
        # fixed argument list (interpreter, -m module, our own folders); no shell, no user text
        cmd = [sys.executable, "-P", "-m", "vid3d.sfm", str(frames_dir.resolve()), str(work.resolve()), str(fov)]
        sfm = subprocess.run(cmd, env=env, cwd=src_dir, stderr=subprocess.PIPE, text=True)  # noqa: S603
        if sfm.returncode != 0:
            # sfm.py exits 3 with an "error:" line when it has a message meant for people.
            said = [l[6:] for l in sfm.stderr.splitlines() if l.startswith("error: ")]
            raise RuntimeError(said[-1] if said else "The camera-path step crashed. Try a different video.")
        sfm_stats = json.loads((work / "sfm_stats.json").read_text())
    views, k1s, obs = load_views(work / "sfm.npz")
    log(f"      {sfm_stats['frames_registered']}/{sfm_stats['frames_total']} frames placed")

    log(f"[3/6] AI depth on {len(views)} frames")
    model = DepthModel()
    log(f"      device: {model.device}")
    all_p, all_c, all_f, fits = [], [], [], []

    def read(v):
        img = cv2.imread(str(frames_dir / v.name))
        if img is None:
            raise RuntimeError(f"Frame {v.name} could not be read back; the frames folder was changed during the run.")
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    gains = color.exposure_gains([color.frame_luma(read(v)) for v in views])
    for i, (v, k1, o, gain) in enumerate(zip(views, k1s, obs, gains, strict=True)):
        rgb = read(v)
        disp = model.disparity(rgb)  # depth uses the untouched frame
        u = np.clip(o[:, 0].astype(int), 0, disp.shape[1] - 1)
        vv = np.clip(o[:, 1].astype(int), 0, disp.shape[0] - 1)
        fit = align_disparity(disp[vv, u], o[:, 2])
        if fit is None:
            continue
        a, b, inl = fit
        z = o[:, 2]
        depth = metric_depth(disp, a, b, 0.5 * z.min(), 2.0 * np.percentile(z, 98))
        p, c = backproject(v, depth, color.normalize_frame(rgb, gain), stride=stride, k1=k1)
        all_p.append(p)
        all_c.append(c)
        all_f.append(np.full(len(p), i, np.int32))
        fits.append(inl)
        log(f"      {i + 1}/{len(views)}")
    del model
    if not all_p:
        raise RuntimeError("The AI depth could not be matched to the camera path on any frame. "
                           "Try a video with more texture and steady lighting.")

    log("[4/6] fusing into one point cloud")
    P, C, F = np.concatenate(all_p), np.concatenate(all_c), np.concatenate(all_f)
    median_z = float(np.median(np.concatenate([o[:, 2] for o in obs])))
    P, C, V = fuse(P, C, F, voxel=median_z / 200, min_views=2)
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
        method = f"camera height given: {h} m" if camera_height else f"camera held at ~{h} m above floor (assumed)"
        scale = h / floor.cam_height_raw
        if ceiling_height:
            method += " (ceiling not detected, so --ceiling-height was ignored)"

    def to_metric(X):
        return ((X - origin) @ Rw.T) * scale

    floor_sigma = uncertainty.floor_sigma_rel(find_floor, P, cams, up_hint)  # on the raw cloud, before scaling
    P, cams_m = to_metric(P), to_metric(cams)
    cam_height = uncertainty.camera_height_consistency(cams_m[:, 1])
    room_h = floor.ceiling_height_raw * scale if floor.ceiling_height_raw else None

    # Rotate around the vertical axis so walls line up with x/z.
    yaw = floorplan.dominant_yaw(P, room_h)
    P[:, [0, 2]] = yaw_align(P[:, [0, 2]], -yaw)
    cams_m[:, [0, 2]] = yaw_align(cams_m[:, [0, 2]], -yaw)

    log("[6/6] floor plan + export")
    room = floorplan.analyze(P, room_h) or {"incomplete": True, "reason": "Too few wall points to measure the room."}
    floorplan.render(P, C, cams_m, room, room_h, out / "floorplan.png")
    write_ply(out / "cloud.ply", P, C, V)

    scene = {
        "video": video_label(video),
        "scale_method": method,
        "frames_extracted": sfm_stats["frames_total"],
        "frames_registered": sfm_stats["frames_registered"],
        "frames_with_depth": len(fits),
        "sfm_reprojection_error_px": round(sfm_stats["reprojection_error_px"], 3),
        "mean_depth_fit_inliers": round(float(np.mean(fits)), 3),
        "points": int(len(P)),
        "cameras": np.round(cams_m, 3).tolist(),
        "room": room,
        "palette": floorplan.palette(P, C, room, room_h),
        "seconds": round(time.time() - t0, 1),
    }
    scene["camera_height"] = cam_height
    scene["uncertainty"] = uncertainty.estimate(P, room_h, method, floor_sigma)
    half_width = uncertainty.area_half_width_rel(scene["uncertainty"]["ranges"])
    scene["confidence"] = uncertainty.confidence(
        method, sfm_stats["frames_registered"] / max(1, sfm_stats["frames_total"]), room, half_width,
        cam_height["inconsistent"])
    scene["warnings"] = quality_warnings(scene)
    (out / "scene.json").write_text(json.dumps(scene, indent=2))
    log(f"done in {scene['seconds']} s -> {out}")
    if rg := scene["uncertainty"]["ranges"]:
        fmt = uncertainty.format_range
        log(f"range (90%): {fmt(rg['length_m'], 'm')} x {fmt(rg['width_m'], 'm')}, area {fmt(rg['area_m2'], 'm²')}; "
            f"confidence {scene['confidence']['label']} ({scene['confidence']['score']}/100)")
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
    if scene.get("camera_height", {}).get("inconsistent"):
        w.append("The phone height changed a lot during the walk, so a single scale may not fit the whole room. "
                 "Hold the phone at one height.")
    if scene["room"].get("missing_wall"):
        w.append("One wall looks like it was never filmed, so the room may be bigger than measured. "
                 "Walk so every wall appears at some point.")
    elif scene["room"].get("rectangular") is False:
        w.append("The room outline is not a simple rectangle (an L-shaped room, or a wall that was only partly "
                 "captured). The area shown is the bounding rectangle, so the real floor area is smaller.")
    if "(assumed)" in scene["scale_method"]:
        w.append("Real-world scale is a guess from typical phone height (about ±5–10%). "
                 "Use --camera-height, --ceiling-height or calibrate in the viewer to tighten it.")
    return w
