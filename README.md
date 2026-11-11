<div align="center">

<img src="docs/logo.svg" alt="video-to-3d logo" width="120">

# video-to-3d

**Walk through a room with your phone. Get a 3D model you can measure, with honest error ranges.**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)
![COLMAP](https://img.shields.io/badge/COLMAP-SfM-555)
![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)
![three.js](https://img.shields.io/badge/three.js-r160-000000?logo=threedotjs&logoColor=white)
![CI](https://github.com/Srijjit-V/video-to-3d/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)

Free and open source. Runs on a laptop: no LiDAR, no cloud, no API keys.
A phone video becomes a metric point cloud, a room size **with a 90% range and a confidence score**, a floor plan, the room's colours and a browser viewer.

[Live viewer and demo](https://srijjit-v.github.io/video-to-3d/) · [Run it on your video](#run-it-on-your-video) · [Architecture](#architecture) · [Engineering](#engineering-highlights) · [Verification](#verification-and-limits)

</div>

> [!IMPORTANT]
> **The hosted page cannot process a video.** Reconstruction needs COLMAP and an AI model, so it runs on **your own computer**
> (`vid3d serve`). The hosted viewer is a static site: it opens the bundled demo scans and any `cloud.ply` + `scene.json` you drop on it. Files stay in your browser.
>
> **Accuracy is only measured on a synthetic room.** Real-phone accuracy has not been measured yet ([protocol](docs/BENCHMARK.md)).
> The error ranges come from a documented model ([docs/MATH.md](docs/MATH.md)), not from real-room statistics.

<p align="center"><img src="docs/screenshots/desktop-scene.png" alt="The viewer showing the sample room with its palette and measurements" width="760"></p>

## What it does

Film a slow walk around a room. video-to-3d finds where the phone was, estimates the distance of every pixel, fuses it all into a coloured 3D point cloud, finds the floor and sets the real-world scale,
then measures the room. It tells you **how far to trust the numbers**: "4.0 m (3.8 to 4.2 m), confidence high", or, when a wall was never filmed, "at least 2.7 m, confidence low".

You get a 3D viewer with a ruler, a colour picker, colour-by-height, a calibration tool, the room's palette and a floor plan.
Your video never leaves your computer, and the photos made from it are deleted when the run ends.

## Try it

Open the [live viewer](https://srijjit-v.github.io/video-to-3d/) and press **Run the demo**. Two scans are bundled (about 4 MB together):

| Scan | What it shows | What you should see |
|---|---|---|
| **Good scan** (synthetic 5.0 x 4.0 m room with a door) | the guided demo: size, measure the door, calibrate, top-down, pick a wall colour, colour by height | size about 4.05 x 5.0 m, area range 18.1 to 22.2 m², confidence **high**, door about 2.03 m |
| **Bad capture** (same room, the walk stopped before the far wall) | how the program behaves when the video cannot support a size | "at least 4.05 x 2.73 m", open-ended area range, confidence **low**, a warning that a wall was never filmed |

## Run it on your video

**You need:** Python 3.11 (tested on a MacBook with an Apple M2 chip; other machines are untested), about 2 GB of disk, and internet once for a ~100 MB AI model.

1. **Film.** Walk slowly around the room for 10 to 30 seconds, keep the floor and corners in view, end where you started. `.mp4`, `.mov`, `.m4v`, `.webm`, `.avi`, `.mkv` all work. Limits: 300 s, 4K, 20,000 frames.
2. **Install once.**
   ```bash
   git clone https://github.com/Srijjit-V/video-to-3d.git
   cd video-to-3d
   python3.11 -m venv .venv && .venv/bin/pip install -e .
   ```
3. **Run.** The easy way, drop your video on a page:
   ```bash
   .venv/bin/vid3d serve
   ```
   Or on the command line:
   ```bash
   .venv/bin/vid3d process my_room.mp4     # writes runs/my_room/
   .venv/bin/vid3d view runs/my_room       # opens it in your browser
   ```

Results in `runs/my_room/`: `cloud.ply` (opens in MeshLab, CloudCompare, Blender), `scene.json` (size, ranges, confidence, colours, warnings) and `floorplan.png`.
If you know how high you held the phone, add `--camera-height 1.5`; if the ceiling is in view, `--ceiling-height 2.44`. Both tighten the range.
Reproducible install: `pip install --require-hashes -r requirements/lock-py311.txt`.

| What you see | What it means | What to do |
|---|---|---|
| "The video is only 1.0 seconds long" | too short to work out depth | film at least 3 seconds (10 to 30 is best) |
| "Only 20 of 80 frames could be placed" | the camera path failed for most of the video | walk slower, avoid blank walls, keep detail in view |
| "A wall looks like it was never filmed" | the walk stopped before a wall | walk so every wall appears at some point |
| "Real-world scale is a guess" | no camera or ceiling height given | calibrate on a door in the viewer, or pass `--camera-height` |
| "already exists. Remove it…" | `--out` has an old `frames/` or `work/` folder | choose another `--out`, or delete the folder |

## How it works (in plain words)

Your eyes judge distance because each sees a slightly different picture. A walk-through video is the same trick with hundreds of "eyes" along your path.
It keeps the sharpest ~80 frames, works out where the phone was for each (COLMAP), has an AI guess the distance of every pixel and corrects it with the exact distances COLMAP knows,
merges everything into one cloud (a point survives only if two frames agree), finds the floor, and turns arbitrary units into metres by assuming (or being told) how high the phone was.
The full derivation, with worked numbers, is in [docs/MATH.md](docs/MATH.md).

## Architecture

```mermaid
flowchart LR
    V[/"video"/] --> S1["1 sharp frames"] --> S2["2 camera path<br/>COLMAP"] --> S3["3 AI depth<br/>+ robust fit"] --> S4["4 fuse<br/>2+ views agree"]
    S4 --> S5["5 floor + scale"] --> S6["6 walls, floor plan,<br/>ranges, confidence"]
    S6 --> O[("cloud.ply<br/>scene.json<br/>floorplan.png")] --> W["Static viewer<br/>(three.js)"]
```

More diagrams (data flow, upload sequence with progress events, trust boundaries): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Engineering highlights

| Concern | Implementation |
|---|---|
| Honest numbers | Monte Carlo over scale error, floor fit and wall detection gives a 90% range per dimension; a 0 to 100 confidence with reasons in words; "at least" ranges when a wall is missing; L-shaped rooms flagged |
| Robust depth | per-frame affine fit `1/z = a d + b`, Theil-Sen start then IRLS with MAD, flying-pixel filter, multi-view voxel agreement |
| Floor and ceiling | lowest dense height layer, RANSAC + SVD re-levelling, interior-fraction ceiling test; 8 adversarial test rooms |
| Privacy | video, frames and COLMAP files deleted when a run ends (success, error, cancel); scene.json stores only the file name; nothing uploaded in hosted mode |
| Untrusted input | duration, resolution and frame-count limits before and during decode; 2 GB upload cap, extension allow-list, server-made file names |
| Local server | `127.0.0.1` only, Host allow-list (DNS rebinding), Origin check, one job at a time, socket timeout, job pruning, traversal tests, CSP |
| Supply chain | model pinned to a commit and loaded as safetensors; three.js bundled with a SHA-384 integrity hash checked against the npm package; hash-pinned lockfile; `pip-audit` in CI |
| Quality gates | ruff (with security rules), mypy, 130 Python tests, 11 viewer-logic tests, 12 real-browser tests, GitHub Actions on every push |
| Accessible UI | keyboard-complete, screen-reader labels, tested contrast (23 checks), phone layout verified, strict CSP with no inline script |

## Explore the code

- [`src/vid3d/pipeline.py`](src/vid3d/pipeline.py): the six stages, outputs, warnings
- [`src/vid3d/depth.py`](src/vid3d/depth.py), [`geometry.py`](src/vid3d/geometry.py), [`floorplan.py`](src/vid3d/floorplan.py): the maths
- [`src/vid3d/uncertainty.py`](src/vid3d/uncertainty.py): ranges and confidence
- [`src/vid3d/server.py`](src/vid3d/server.py): the local server and its checks
- [`viewer/`](viewer/): the static viewer; [`DESIGN.md`](DESIGN.md) is its design language
- [`docs/`](docs/): [AUDIT](docs/AUDIT.md) · [MATH](docs/MATH.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [SECURITY](docs/SECURITY.md) · [VERIFICATION](docs/VERIFICATION.md) · [BENCHMARK](docs/BENCHMARK.md) · [RESEARCH](docs/RESEARCH.md)

## Local API (`vid3d serve`)

| Method and path | Purpose |
|---|---|
| `POST /api/jobs?camera_height=&ceiling_height=&fov=` | upload a video (`application/octet-stream`); returns `202 {id}`; `409` if a job is running |
| `GET /api/jobs/{id}` | state, six stages with details like "frame 12 of 58", error text, elapsed time |
| `POST /api/jobs/{id}/cancel` | stop the job and delete its private files |
| `GET /jobs/{id}/cloud.ply` · `scene.json` · `floorplan.png` | the three result files (nothing else is served) |
| `GET /api/health` | `{"mode": "local"}`; the static site has no such endpoint, which is how the viewer knows it is hosted |

## Verification and limits

Measured on 2026-11-10 (details in [docs/VERIFICATION.md](docs/VERIFICATION.md)):

- **130** Python tests pass (15 opt-in skipped); **11** Node tests; **12** browser tests; ruff, mypy and `pip-audit` clean.
- Synthetic 5.0 x 4.0 m room: with the true camera height, 4.05 x 5.00 m (+1.3%, 0%) and the area range 18.1 to 22.2 m² contained the true 20 m²;
  with the default 1.45 m assumed, 3.90 x 4.85 m (-2.5%, -3.0%) and the range 13.9 to 24.4 m² contained it too.
- One run per setting; the camera solver varies by a few percent between runs.

**Not claimed:** accuracy on real phone video (not measured); that the 90% ranges are calibrated on real rooms; results for mirrors, glass, moving people or very dark rooms;
non-rectangular rooms beyond flagging them; anything on Windows, Linux or CUDA; a CI run on GitHub (written and run locally, not yet seen green there).

## Deploy the viewer

The viewer is static. `vercel.json` sets the output folder to `viewer` with no build and a strict CSP; `.github/workflows/pages.yml` publishes the same folder to GitHub Pages (live link above).

```bash
npx vercel login
npx vercel deploy --prod --yes      # run inside this folder
```

Nothing that needs COLMAP or PyTorch runs on the host.

## License and credits

[MIT](LICENSE). Depth Anything V2 **Small** is Apache 2.0; COLMAP is BSD.
Built on [COLMAP / pycolmap](https://colmap.github.io/), [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2), [OpenCV](https://opencv.org/), [three.js](https://threejs.org/), [PyTorch](https://pytorch.org/), [Transformers](https://github.com/huggingface/transformers).
