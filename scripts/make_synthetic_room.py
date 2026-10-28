"""Render a walkthrough video of a textured box room with KNOWN size.

Used to check how accurate the pipeline's measurements are.
    python scripts/make_synthetic_room.py --out samples/synthetic_room.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

PX_PER_M = 160


def texture(w_m: float, h_m: float, seed: int, base, kind: str) -> np.ndarray:
    """Procedural texture: tinted multi-scale noise + 'posters'/'furniture' blocks."""
    rng = np.random.default_rng(seed)
    W, H = int(w_m * PX_PER_M), int(h_m * PX_PER_M)
    img = np.zeros((H, W, 3), np.float32)
    for scale, amp in [(64, 40), (16, 22), (4, 12), (1, 8)]:
        small = rng.normal(0, 1, (max(2, H // scale), max(2, W // scale), 3)).astype(np.float32)
        img += amp * cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
    img += np.array(base, np.float32)
    if kind == "floor":  # planks
        for y in range(0, H, int(0.18 * PX_PER_M)):
            cv2.line(img, (0, y), (W, y), (40, 50, 70), 2)
    n_blocks = {"wall": 14, "floor": 6, "ceiling": 3}[kind]
    for _ in range(n_blocks):
        bw, bh = rng.integers(PX_PER_M // 4, PX_PER_M), rng.integers(PX_PER_M // 4, PX_PER_M)
        x, y = rng.integers(0, max(1, W - bw)), rng.integers(0, max(1, H - bh))
        col = rng.integers(30, 230, 3).tolist()
        cv2.rectangle(img, (int(x), int(y)), (int(x + bw), int(y + bh)), col, -1)
        cv2.rectangle(img, (int(x), int(y)), (int(x + bw), int(y + bh)), (20, 20, 20), 3)
        for _ in range(4):  # inner detail so SIFT finds corners
            cx, cy = int(x + rng.integers(0, bw)), int(y + rng.integers(0, bh))
            cv2.circle(img, (cx, cy), int(rng.integers(4, 18)), rng.integers(0, 255, 3).tolist(), -1)
    return np.clip(img, 0, 255).astype(np.uint8)


def render_video(out: Path, L=5.0, W=4.0, H=2.6, cam_h=1.5, frames=180, size=(640, 480), fov=70, ss=2):
    faces = {  # (axis, side): texture, (u-axis, v-axis), shading
        (0, 0): (texture(W, H, 1, (150, 160, 175), "wall"), (2, 1), 0.85),
        (0, 1): (texture(W, H, 2, (175, 150, 140), "wall"), (2, 1), 0.95),
        (2, 0): (texture(L, H, 3, (140, 175, 150), "wall"), (0, 1), 1.0),
        (2, 1): (texture(L, H, 4, (170, 170, 140), "wall"), (0, 1), 0.8),
        (1, 0): (texture(L, W, 5, (60, 95, 140), "floor"), (0, 2), 0.7),
        (1, 1): (texture(L, W, 6, (215, 215, 215), "ceiling"), (0, 2), 1.05),
    }
    bounds = np.array([[0, 0, 0], [L, H, W]], np.float64)
    w, h = size[0] * ss, size[1] * ss
    f = (w / 2) / np.tan(np.radians(fov / 2))
    vs, us = np.mgrid[0:h, 0:w]
    rays_cam = np.stack([(us + 0.5 - w / 2) / f, (vs + 0.5 - h / 2) / f, np.ones_like(us, float)], -1).reshape(-1, 3)
    rays_cam /= np.linalg.norm(rays_cam, axis=1, keepdims=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 30, size)
    center = np.array([L / 2, 0, W / 2])
    for k in range(frames):
        a = 2 * np.pi * k / frames
        C = center + np.array([1.1 * np.cos(a), cam_h + 0.02 * np.sin(5 * a), 0.8 * np.sin(a)])
        yaw = a + np.radians(40)  # look outward, rotated off the radius
        pitch = np.radians(-14)
        fwd = np.array([np.cos(yaw) * np.cos(pitch), np.sin(pitch), np.sin(yaw) * np.cos(pitch)])
        right = np.cross([0, -1, 0], fwd)
        right /= np.linalg.norm(right)
        down = np.cross(fwd, right)
        D = rays_cam @ np.stack([right, down, fwd])  # world ray directions

        with np.errstate(divide="ignore", invalid="ignore"):
            tb = np.where(D > 0, (bounds[1] - C) / D, (bounds[0] - C) / D)
        tb[~np.isfinite(tb)] = np.inf
        axis = np.argmin(tb, 1)
        t = tb[np.arange(len(tb)), axis]
        P = C + D * t[:, None]
        side = (D[np.arange(len(D)), axis] > 0).astype(int)

        img = np.zeros((len(D), 3), np.float32)
        for (ax, sd), (tex, (ua, va), shade) in faces.items():
            m = (axis == ax) & (side == sd)
            if not m.any():
                continue
            u = np.clip((P[m, ua] * PX_PER_M).astype(int), 0, tex.shape[1] - 1)
            v = np.clip(((P[m, va] if va != 1 else H - P[m, va]) * PX_PER_M).astype(int), 0, tex.shape[0] - 1)
            img[m] = tex[v, u] * shade * (1.0 / (1 + 0.04 * t[m, None]))
        frame = np.clip(img, 0, 255).astype(np.uint8).reshape(h, w, 3)
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        vw.write(frame)
    vw.release()
    truth = {"length_m": L, "width_m": W, "height_m": H, "camera_height_m": cam_h,
             "area_m2": L * W, "area_ft2": round(L * W * 10.7639, 1)}
    out.with_suffix(".truth.json").write_text(json.dumps(truth, indent=2))
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("samples/synthetic_room.mp4"))
    ap.add_argument("--frames", type=int, default=180)
    a = ap.parse_args()
    print(render_video(a.out, frames=a.frames))
