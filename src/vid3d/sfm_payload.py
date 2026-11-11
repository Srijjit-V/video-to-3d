"""The sfm payload: camera poses plus sparse per-frame observations, as small JSON.

It is the seam of the pipeline. Whoever solves the camera path (pycolmap in a subprocess, a server, or
colmap-wasm in the browser) hands over this payload; everything after it needs only the frames and it.
The payload comes from outside the process, so it is validated before use.

    {"version": 1,
     "camera": {"width", "height", "focal", "cx", "cy", "k1"},      # one shared camera, pixels
     "frames_total": int, "reprojection_error_px": float,
     "frames": [{"name": "frame_0000.jpg", "R": [9 floats, row-major world->camera],
                 "t": [3 floats], "obs": [[u, v, z], ...]}]}        # z = depth along the optical axis
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

VERSION = 1
MAX_FRAMES = 400
MAX_OBS_PER_FRAME = 50_000
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}\.jpg$")


def _nums(values, n: int, what: str) -> list[float]:
    if not isinstance(values, list) or len(values) != n or not all(
            isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in values):
        raise ValueError(f"{what} must be {n} finite numbers")
    return [float(v) for v in values]


def validate(p: dict) -> None:
    if not isinstance(p, dict) or p.get("version") != VERSION:
        raise ValueError(f"unsupported sfm payload version (expected {VERSION})")
    cam = p.get("camera")
    if not isinstance(cam, dict):
        raise ValueError("camera is missing")
    c = _nums([cam.get(k) for k in ("width", "height", "focal", "cx", "cy", "k1")], 6, "camera")
    if min(c[0], c[1], c[2]) <= 0:
        raise ValueError("camera size and focal length must be positive")
    frames = p.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError(f"frames must hold 1 to {MAX_FRAMES} entries")
    for f in frames:
        if not isinstance(f, dict) or not _NAME.match(str(f.get("name", ""))):
            raise ValueError("frame names must look like frame_0000.jpg")
        _nums(f.get("R"), 9, "R")
        _nums(f.get("t"), 3, "t")
        obs = f.get("obs")
        if not isinstance(obs, list) or len(obs) > MAX_OBS_PER_FRAME:
            raise ValueError(f"obs must be a list of at most {MAX_OBS_PER_FRAME} points")
        for o in obs:
            _nums(o, 3, "an observation")
    _nums([p.get("reprojection_error_px", 0.0)], 1, "reprojection_error_px")
    if not isinstance(p.get("frames_total"), int) or p["frames_total"] < len(frames):
        raise ValueError("frames_total must be at least the number of placed frames")


def payload_to_npz(p: dict, work_dir: Path) -> dict:
    """Validate, then write work/sfm.npz (what the depth stage reads). Returns the stats the pipeline logs."""
    validate(p)
    cam = p["camera"]
    names, Ks, k1s, Rs, ts, sizes, obs = [], [], [], [], [], [], []
    for f in sorted(p["frames"], key=lambda f: f["name"]):
        o = np.asarray(f["obs"], np.float64).reshape(-1, 3)
        o = o[o[:, 2] > 0]  # points behind the camera are not usable
        names.append(f["name"])
        Ks.append([[cam["focal"], 0, cam["cx"]], [0, cam["focal"], cam["cy"]], [0, 0, 1]])
        k1s.append(cam["k1"])
        Rs.append(np.asarray(f["R"]).reshape(3, 3))
        ts.append(f["t"])
        sizes.append([cam["width"], cam["height"]])
        obs.append(o)
    work_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        work_dir / "sfm.npz",
        names=np.array(names), K=np.array(Ks), k1=np.array(k1s), R=np.array(Rs), t=np.array(ts),
        size=np.array(sizes), obs=np.concatenate(obs).astype(np.float32),
        obs_offsets=np.cumsum([0] + [len(o) for o in obs]),
    )
    return {"frames_total": p["frames_total"], "frames_registered": len(names),
            "reprojection_error_px": float(p.get("reprojection_error_px", 0.0))}


def load_payload(path: Path) -> dict:
    return json.loads(Path(path).read_text())
