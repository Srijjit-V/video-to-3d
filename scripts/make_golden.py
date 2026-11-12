"""Golden test vectors: run the Python reference implementation on fixed inputs and save inputs + outputs as JSON.

The TypeScript port (ts/src, built to viewer/js/core) must reproduce them within the tolerances in tests/js/golden.test.mjs.
Run: .venv/bin/python scripts/make_golden.py     (rewrites tests/golden/golden.json; review the diff)
"""

import json
from pathlib import Path

import numpy as np

from vid3d import color, depth, floorplan, geometry, uncertainty
from vid3d.pipeline import load_views  # noqa: F401  (documents where View comes from)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "golden" / "golden.json"


def clean(x, nd=6):
    """JSON-safe: numpy -> lists, NaN -> null, floats rounded."""
    if isinstance(x, np.ndarray):
        return clean(x.tolist(), nd)
    if isinstance(x, dict):
        return {k: clean(v, nd) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [clean(v, nd) for v in x]
    if isinstance(x, np.generic):
        return clean(x.item(), nd)
    if isinstance(x, float):
        return None if not np.isfinite(x) else round(x, nd)
    return x


def read_ply(path):
    raw = path.read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    n = int(raw[:end].split(b"element vertex ")[1].split(b"\n")[0])
    rec = np.frombuffer(raw[end:], dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1"), ("v", "u1")], count=n)
    return np.stack([rec["x"], rec["y"], rec["z"]], 1).astype(np.float64), np.stack([rec["r"], rec["g"], rec["b"]], 1)


def main():
    g = {}
    rng = np.random.default_rng(42)

    # --- A. robust disparity fit
    d = rng.uniform(0.2, 1.0, 300)
    z = 1 / (0.7 * d + 0.2) + rng.normal(0, 0.01, 300)
    bad = rng.choice(300, 30, replace=False)
    z[bad] *= rng.uniform(0.4, 2.5, 30)
    a, b, inl = depth.align_disparity(d, z)
    g["align"] = {"disp": d, "z": z, "a": a, "b": b, "inliers": inl}

    # --- B. metric depth + flying-pixel filter
    h, w = 40, 50
    disp = np.linspace(0.3, 1.0, w)[None, :] * np.ones((h, 1)) + rng.normal(0, 0.003, (h, w))
    disp[:, 25:] += 0.5  # a depth edge in the middle
    md = depth.metric_depth(disp.astype(np.float32), 0.8, 0.1, 0.4, 6.0)
    g["metric"] = {"h": h, "w": w, "disp": disp.astype(np.float32), "a": 0.8, "b": 0.1, "zmin": 0.4, "zmax": 6.0, "depth": md}

    # --- C. back-projection with lens distortion
    R = np.array([[0.9, -0.1, 0.42], [0.1, 0.99, 0.0], [-0.42, 0.04, 0.9]])
    q, _ = np.linalg.qr(R)
    t = np.array([0.3, -1.2, 2.0])
    K = np.array([[400.0, 0, 320], [0, 400.0, 240], [0, 0, 1]])
    view = geometry.View("f", K, q, t, 640, 480)
    dh, dw = 24, 32
    dep = rng.uniform(1.0, 4.0, (dh, dw)).astype(np.float32)
    dep[3:6, 4:9] = np.nan
    rgb = rng.integers(0, 255, (dh, dw, 3), dtype=np.uint8)
    bp, bc = geometry.backproject(view, dep, rgb, stride=4, k1=-0.05)
    g["backproject"] = {"K": K, "R": q, "t": t, "h": dh, "w": dw, "depth": dep, "rgb": rgb, "k1": -0.05, "stride": 4,
                        "points": bp, "colors": bc}

    # --- D. voxel fusion (frame ids sorted, as the pipeline produces them)
    pts = np.concatenate([rng.normal(c, 0.15, (60, 3)) for c in ([0, 0, 0], [1, 0, 0], [0, 1, 1])] * 2)
    frames = np.repeat([0, 1, 2, 3, 4, 5], 60)
    col = rng.integers(0, 255, (len(pts), 3), dtype=np.uint8)
    fp, fc, fv = geometry.fuse(pts, col, frames, voxel=0.25, min_views=2)
    g["fuse"] = {"points": pts, "colors": col, "frames": frames, "voxel": 0.25, "min_views": 2, "out_points": fp, "out_colors": fc, "out_views": fv}

    # --- E. floor + ceiling + scale frame on a raw (tilted, unscaled) copy of the sample room
    P, C = read_ply(ROOT / "viewer" / "sample" / "cloud.ply")
    sc = json.loads((ROOT / "viewer" / "sample" / "scene.json").read_text())
    cams = np.array(sc["cameras"], float)
    sel = np.random.default_rng(1).choice(len(P), 9000, replace=False)
    Ps, Cs = P[sel], C[sel]
    th = np.radians(25)
    Rr = np.array([[1, 0, 0], [0, np.cos(th), -np.sin(th)], [0, np.sin(th), np.cos(th)]])
    Rr = Rr @ np.array([[np.cos(0.7), 0, np.sin(0.7)], [0, 1, 0], [-np.sin(0.7), 0, np.cos(0.7)]])
    s_raw = 0.27
    raw = (Ps @ Rr.T) * s_raw + np.array([1.0, -2.0, 0.5])
    raw_cams = (cams @ Rr.T) * s_raw + np.array([1.0, -2.0, 0.5])
    up_hint = Rr @ np.array([0.03, 1.0, -0.02])
    fl = geometry.find_floor(raw, raw_cams, up_hint)
    Rw, origin = geometry.floor_frame(fl, raw_cams)
    g["floor"] = {"points": raw, "cams": raw_cams, "up_hint": up_hint, "up": fl.up, "floor_d": fl.floor_d,
                  "cam_height_raw": fl.cam_height_raw, "ceiling_height_raw": fl.ceiling_height_raw, "Rw": Rw, "origin": origin}
    # same idea with a real ceiling: a box room 4 x 5 x 2.6 m, tilted and scaled
    r2 = np.random.default_rng(7)
    def plane(n, f):
        return np.array([f(r2.uniform(0, 1), r2.uniform(0, 1)) for _ in range(n)])
    box = np.concatenate([
        plane(3000, lambda u, v: [u * 4, 0.0, v * 5]),            # floor
        plane(3000, lambda u, v: [u * 4, 2.6, v * 5]),            # ceiling
        plane(1200, lambda u, v: [0.0, v * 2.6, u * 5]), plane(1200, lambda u, v: [4.0, v * 2.6, u * 5]),
        plane(1200, lambda u, v: [u * 4, v * 2.6, 0.0]), plane(1200, lambda u, v: [u * 4, v * 2.6, 5.0]),
    ]) + r2.normal(0, 0.01, (10800, 3))
    ang = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    box_cams = np.stack([2 + 1.0 * np.cos(ang), np.full(40, 1.5), 2.5 + 1.2 * np.sin(ang)], 1)
    Rb = Rr
    braw, bcams = (box @ Rb.T) * 0.31 + [0.5, 0.2, -1.0], (box_cams @ Rb.T) * 0.31 + [0.5, 0.2, -1.0]
    bup = Rb @ np.array([0.02, 1.0, 0.03])
    bf = geometry.find_floor(braw, bcams, bup)
    g["floor_ceiling"] = {"points": braw, "cams": bcams, "up_hint": bup, "up": bf.up, "cam_height_raw": bf.cam_height_raw,
                          "ceiling_height_raw": bf.ceiling_height_raw, "true_ratio": 2.6 / 1.5}
    ys = geometry.yaw_align(np.array([[1.0, 2.0], [-3.0, 0.5]]), 17.0)
    g["yaw_align"] = {"xz": [[1.0, 2.0], [-3.0, 0.5]], "deg": 17.0, "out": ys}

    # --- F. floor plan on the metric sample (floor at y=0), and the yaw finder on a rotated copy
    Pm = Ps.copy()
    room = floorplan.analyze(Pm, None)
    xz = floorplan.wall_points(Pm, None)
    g["floorplan"] = {"points": Pm, "room": room, "wall_xz_count": len(xz),
                      "extent_x": floorplan._extent(xz[:, 0]), "extent_z": floorplan._extent(xz[:, 1]),
                      "extent_x_20": floorplan._extent(xz[:, 0], 0.2),
                      "sides": floorplan.side_support(xz, room["rect_m"]), "support": floorplan.wall_support(xz, room["rect_m"])}
    rot = Pm.copy()
    rot[:, [0, 2]] = geometry.yaw_align(rot[:, [0, 2]], 23.0)
    g["yaw"] = {"points": rot, "deg": floorplan.dominant_yaw(rot, None)}
    # an L-shaped room and one with a missing wall, to cover the flags
    lroom = Pm[~((Pm[:, 0] > 0.3) & (Pm[:, 2] > 0.2))]
    lr = floorplan.analyze(lroom, None)
    g["floorplan_l"] = {"points": lroom, "room": lr}

    # --- G. uncertainty and confidence
    ue = uncertainty.estimate(Pm, None, "camera held at ~1.45 m above floor (assumed)", 0.01)
    g["uncertainty"] = {"points": Pm, "method": "camera held at ~1.45 m above floor (assumed)", "floor_sigma": 0.01, "estimate": ue}
    g["height_consistency"] = {"heights": [1.45, 1.5, 1.4, 1.62, 1.3], "out": uncertainty.camera_height_consistency(np.array([1.45, 1.5, 1.4, 1.62, 1.3]))}
    conf_cases = []
    for method, share, rm, hw, inc in (
        ("camera held at ~1.45 m above floor (assumed)", 0.9, {"rectangular": True}, 0.18, False),
        ("camera height given: 1.5 m", 0.7, {"missing_wall": True}, None, True),
        ("ceiling height = 2.44 m", 1.0, {"rectangular": False}, 0.3, False),
        ("camera height given: 1.5 m", 0.95, {"incomplete": True}, None, False),
    ):
        conf_cases.append({"method": method, "share": share, "room": rm, "hw": hw, "inc": inc,
                           "out": uncertainty.confidence(method, share, rm, hw, inc)})
    g["confidence"] = conf_cases

    # --- H. colour
    lumas = [60.0, 100.0, 130.0, 200.0, 20.0]
    g["exposure"] = {"lumas": lumas, "gains": color.exposure_gains(lumas)}
    img = rng.integers(60, 120, (12, 16, 3), dtype=np.uint8)
    g["normalize"] = {"h": 12, "w": 16, "rgb": img, "gain": 1.2, "out": color.normalize_frame(img, 1.2)}
    cols = np.concatenate([np.tile([200, 60, 40], (300, 1)), np.tile([30, 90, 160], (200, 1)), np.tile([230, 230, 220], (100, 1))])
    cols = np.clip(cols + rng.integers(-6, 7, cols.shape), 0, 255).astype(np.uint8)
    g["dominant"] = {"rgb": cols, "out": color.dominant_colors(cols)}
    g["palette"] = {"points": Pm, "colors": Cs, "room": room, "out": floorplan.palette(Pm, Cs, room, None)}

    OUT.write_text(json.dumps(clean(g), separators=(",", ":")))
    print(OUT, f"{OUT.stat().st_size / 1e3:.0f} KB")
    print("floor:", fl.cam_height_raw, fl.ceiling_height_raw, "room:", room["length_m"], room["width_m"], "yaw:", g["yaw"]["deg"])


if __name__ == "__main__":
    main()
