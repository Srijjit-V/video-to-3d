"""Stage 2: solve where the camera was for every frame (COLMAP Structure-from-Motion).

Run as its own process (`python -m vid3d.sfm FRAMES WORK`): pycolmap and torch
bundle conflicting OpenMP runtimes and abort if loaded together.
Output: WORK/sfm.npz, readable without pycolmap.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np


GOOD_FRACTION = 0.8  # below this share of frames placed, try harder
MIN_FRACTION = 0.5  # below this, refuse: measurements would be unreliable
EXHAUSTIVE_MAX_FRAMES = 150  # ~100 s for 90 frames on an M2; grows with frames squared


def focal_factor(fov_deg: float) -> float:
    """COLMAP's starting focal length, as a fraction of the image's long side."""
    import math

    return 0.5 / math.tan(math.radians(fov_deg) / 2)


def run_sfm(frames_dir: Path, work_dir: Path, fov_deg: float = 70.0) -> dict:
    import pycolmap

    work_dir.mkdir(parents=True, exist_ok=True)
    db = work_dir / "colmap.db"
    sparse = work_dir / "sparse"
    if db.exists():
        db.unlink()
    shutil.rmtree(sparse, ignore_errors=True)
    sparse.mkdir()

    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_RADIAL"
    # Phone video is ~65-75 deg wide across the long side. Without a sane starting
    # guess COLMAP can drift to a wildly wrong focal length on flat walls.
    reader.default_focal_length_factor = focal_factor(fov_deg)
    extract = pycolmap.FeatureExtractionOptions()
    extract.max_image_size = 1600
    extract.sift.max_num_features = 8000
    extract.sift.peak_threshold = 0.004  # more features on low-texture surfaces
    print("[sfm] extracting features", flush=True)
    pycolmap.extract_features(db, frames_dir, camera_mode=pycolmap.CameraMode.SINGLE,
                              reader_options=reader, extraction_options=extract)

    pairing = pycolmap.SequentialPairingOptions()
    pairing.overlap = 12
    pairing.quadratic_overlap = True
    n_frames = len(list(frames_dir.glob("*.jpg")))
    exhaustive = n_frames <= EXHAUSTIVE_MAX_FRAMES
    if exhaustive:
        # Matching every pair ties the end of a walk back to its start (loop
        # closure). Neighbour-only matching lets small errors pile up, which
        # bends walls and stretches the room.
        print(f"[sfm] matching all frame pairs ({n_frames * (n_frames - 1) // 2})", flush=True)
        pycolmap.match_exhaustive(db)
    else:
        print("[sfm] matching neighbouring frames", flush=True)
        pycolmap.match_sequential(db, pairing_options=pairing)

    def solve(seed: int):
        out = sparse / f"try{seed}"
        out.mkdir(parents=True, exist_ok=True)
        opts = pycolmap.IncrementalPipelineOptions()
        opts.multiple_models = False
        opts.random_seed = seed
        recs = pycolmap.incremental_mapping(db, frames_dir, out, options=opts)
        return max(recs.values(), key=lambda r: r.num_reg_images()) if recs else None

    def count(r):
        return r.num_reg_images() if r is not None else 0

    print("[sfm] solving camera poses", flush=True)
    rec = solve(1)
    # The solve can stall partway on a fast turn. If too few frames got placed,
    # match every frame against every other (finds overlaps across the loop) and retry.
    if count(rec) < GOOD_FRACTION * n_frames:
        print(f"[sfm] only {count(rec)}/{n_frames} frames placed; retrying", flush=True)
        if not exhaustive:
            pycolmap.match_exhaustive(db)
        for seed in (2, 3):
            cand = solve(seed)
            if count(cand) > count(rec):
                rec = cand
            if count(rec) >= GOOD_FRACTION * n_frames:
                break
    if count(rec) < MIN_FRACTION * n_frames:
        raise RuntimeError(
            f"COLMAP only placed {count(rec)} of {n_frames} frames, too few for a reliable model. "
            "Try a slower, steadier video, turning gradually, with the floor and room corners in view."
        )

    names, Ks, k1s, Rs, ts, sizes, obs = [], [], [], [], [], [], []
    for image in sorted(rec.images.values(), key=lambda im: im.name):
        if not image.has_pose:
            continue
        cam = image.camera
        f, cx, cy, k1 = cam.params[:4]
        pose = image.cam_from_world().matrix()
        R, t = pose[:, :3], pose[:, 3]
        uv, z = [], []
        for p2d in image.points2D:
            if p2d.has_point3D():
                X = rec.points3D[p2d.point3D_id].xyz
                zc = (R @ X + t)[2]
                if zc > 0:
                    uv.append(p2d.xy)
                    z.append(zc)
        names.append(image.name)
        Ks.append([[f, 0, cx], [0, f, cy], [0, 0, 1]])
        k1s.append(k1)
        Rs.append(R)
        ts.append(t)
        sizes.append([cam.width, cam.height])
        obs.append(np.concatenate([np.asarray(uv).reshape(-1, 2), np.asarray(z).reshape(-1, 1)], 1))

    pts = np.array([p.xyz for p in rec.points3D.values()], np.float32)
    cols = np.array([p.color for p in rec.points3D.values()], np.uint8)
    offsets = np.cumsum([0] + [len(o) for o in obs])
    np.savez_compressed(
        work_dir / "sfm.npz",
        names=np.array(names), K=np.array(Ks), k1=np.array(k1s), R=np.array(Rs), t=np.array(ts),
        size=np.array(sizes), obs=np.concatenate(obs).astype(np.float32), obs_offsets=offsets,
        sparse_xyz=pts, sparse_rgb=cols,
    )
    stats = {
        "frames_total": len(list(frames_dir.glob("*.jpg"))),
        "frames_registered": len(names),
        "sparse_points": len(pts),
        "reprojection_error_px": float(rec.compute_mean_reprojection_error()),
    }
    (work_dir / "sfm_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"[sfm] {stats}", flush=True)
    return stats


if __name__ == "__main__":
    run_sfm(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 70.0)
