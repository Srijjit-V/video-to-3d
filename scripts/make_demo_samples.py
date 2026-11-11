"""Build the two bundled demo scenes the viewer shows in "Run the demo".

    python scripts/make_demo_samples.py runs/demo_good

* viewer/sample/      the synthetic 5.0 x 4.0 x 2.6 m room, exactly as the pipeline produced it (plus the demo truth).
* viewer/sample-bad/  the same scene with the far wall and floor removed, as if the walk never turned around.
                      It is derived from the first one by cutting the point cloud and re-running the real analysis
                      (room, ranges, confidence, warnings, floor plan), so the warnings you see are what the program
                      really says about an incomplete capture. It is not a separate video.

Both stay under 5 MB so the hosted page loads quickly.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vid3d import floorplan, uncertainty  # noqa: E402
from vid3d.pipeline import quality_warnings, write_ply  # noqa: E402

KEEP_FRACTION = 0.55  # share of the room (along its long axis) that the "bad" walk covered


def read_ply(path: Path):
    raw = path.read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    header = raw[:end].decode().splitlines()
    n = int(next(line.split()[2] for line in header if line.startswith("element vertex")))
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")]
    if any("views" in line for line in header):
        fields.append(("views", "u1"))
    rec = np.frombuffer(raw[end:], dtype=fields, count=n)
    pts = np.stack([rec["x"], rec["y"], rec["z"]], 1).astype(np.float32)
    rgb = np.stack([rec["r"], rec["g"], rec["b"]], 1)
    return pts, rgb, (rec["views"].copy() if "views" in rec.dtype.names else None)


def describe(scene: dict, kind: str, truth: dict, note: str) -> None:
    scene["demo"] = {"kind": kind, "truth": truth, "note": note}


def main(run: Path) -> None:
    truth = json.loads((ROOT / "samples" / "synthetic_room.truth.json").read_text())
    good = json.loads((run / "scene.json").read_text())
    pts, rgb, views = read_ply(run / "cloud.ply")

    # ---- good sample: copy, add the demo truth ----
    out = ROOT / "viewer" / "sample"
    out.mkdir(exist_ok=True)
    for f in ("cloud.ply", "floorplan.png"):
        shutil.copy(run / f, out / f)
    describe(good, "good", truth, "Synthetic 5.0 x 4.0 x 2.6 m room, camera at 1.5 m, with a 0.9 x 2.03 m door.")
    (out / "scene.json").write_text(json.dumps(good, indent=2))

    # ---- bad sample: cut the far part of the long axis and re-run the real analysis ----
    room = good["room"]
    x0, z0, x1, z1 = room["rect_m"]
    axis = 2 if (z1 - z0) >= (x1 - x0) else 0
    lo, hi = (z0, z1) if axis == 2 else (x0, x1)
    cut = lo + KEEP_FRACTION * (hi - lo)
    keep = pts[:, axis] < cut
    bad_pts, bad_rgb = pts[keep], rgb[keep]
    bad_views = views[keep] if views is not None else None
    cams = np.array(good["cameras"])
    cams = cams[cams[:, axis] < cut]

    room_h = good["room"].get("height_m")
    bad_room = floorplan.analyze(bad_pts, room_h) or {"incomplete": True, "reason": "Too few wall points to measure."}
    method = good["scale_method"]
    sigma = good["uncertainty"]["scale_sigma_rel"]
    est = uncertainty.estimate(bad_pts, room_h, method, floor_sigma_rel=min(sigma, 0.02), seed=0)
    ranges = est["ranges"]
    half = uncertainty.area_half_width_rel(ranges)
    bad = dict(good)
    bad.update(
        video="synthetic_room_one_side_only (derived from the sample)",
        points=int(len(bad_pts)),
        cameras=np.round(cams, 3).tolist(),
        room=bad_room,
        uncertainty=est,
        palette=floorplan.palette(bad_pts, bad_rgb, bad_room, room_h),
    )
    bad["confidence"] = uncertainty.confidence(method, 1.0, bad_room, half, False)
    bad["warnings"] = quality_warnings(bad)
    describe(bad, "bad", truth, "The same room, but the walk stopped before the far wall: part of the room was never filmed.")

    out = ROOT / "viewer" / "sample-bad"
    out.mkdir(exist_ok=True)
    write_ply(out / "cloud.ply", bad_pts, bad_rgb, bad_views)
    floorplan.render(bad_pts, bad_rgb, cams, bad_room, room_h, out / "floorplan.png")
    (out / "scene.json").write_text(json.dumps(bad, indent=2))

    for name in ("sample", "sample-bad"):
        total = sum(f.stat().st_size for f in (ROOT / "viewer" / name).iterdir())
        print(f"{name}: {total / 1e6:.2f} MB")
    print("bad room:", {k: bad_room.get(k) for k in ("incomplete", "missing_wall", "wall_support", "length_m", "width_m",
                                                      "area_m2", "at_least_m")})
    print("bad ranges:", ranges, "confidence:", bad["confidence"]["label"], bad["confidence"]["score"])
    print("warnings:", *bad["warnings"], sep="\n  ")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "runs/demo_good"))
