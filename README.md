<p align="center">
  <img src="docs/logo.svg" alt="video-to-3d logo" width="160">
</p>

<h1 align="center">video-to-3d</h1>

<p align="center">
  <b>Walk through a room with your phone. Get a 3D model you can measure.</b><br>
  Free, open source, runs on a laptop. No LiDAR, no cloud, no API keys.
</p>

<p align="center">
  <a href="https://srijjit-v.github.io/video-to-3d/"><b>Open the live viewer</b></a> ·
  <a href="#web-viewer">How to use it</a> ·
  <a href="DESIGN.md">Design language</a>
</p>

<p align="center">
  <img src="docs/screenshots/desktop-scene.png" alt="The viewer showing the sample room with its palette and measurements" width="760">
</p>

---

Film a slow walk around a room. `video-to-3d` turns the video into:

- a **3D point cloud** in real-world metres
- a **room estimate**: length × width, height if the ceiling is visible, area in m² and ft²
- a **top-down floor plan** image
- the room's **real colours**: every point keeps the colour from the video, and a palette card lists the dominant wall, floor and ceiling colours
- a **3D viewer** (in your browser) where you click two points to measure anything, pick a point to read its colour, recolour the cloud by height, distance or how many frames saw it, switch to top-down view, and calibrate against a known length (like a door)

Tested on an M2 MacBook Air with 8 GB of RAM. A 90-frame video takes about 3 minutes.

## Web viewer

The viewer in `viewer/` is a plain static site (no build step, no server code, three.js bundled). It runs in three ways:

| Mode | How you start it | What you can do |
|---|---|---|
| **Hosted** | open the [live page](https://srijjit-v.github.io/video-to-3d/) | Open the **sample room**, or drop a `cloud.ply` + `scene.json` (and `floorplan.png`) from your own run. Files open in your browser and are never uploaded. **It cannot process a video**: that needs COLMAP and AI models on your own computer. |
| **Local** | `.venv/bin/vid3d serve` | Drop a video on the page. It uploads to your own machine, shows live progress for all six stages with frame counts and elapsed time, can be cancelled, and opens the 3D scene when done. Camera height, ceiling height and lens field of view are under **Advanced options**. |
| **One run** | `.venv/bin/vid3d view runs/my_room` | Opens an already processed run directly. |

**How to use it**
1. Start with the sample room, or drop your own video (local mode) or files (hosted mode).
2. Drag to orbit, right-drag to pan, scroll to zoom. On a phone, drag and pinch; the **Details** button opens the panel.
3. **Measure** (`M`): click two points. **Calibrate** by typing the true length of something you measured.
4. **Pick colour** (`P`): click a point to see its RGB, hex and a swatch. Click a palette swatch to copy its hex.
5. **Colour by**: true colour, height above the floor, distance from the camera path, or how many frames saw each point (low counts are less certain).
6. `T` top-down, `R` reset view, `Esc` turns a tool off. With a tool on and the 3D view focused, **Enter** picks the point under the centre cross, so everything works from the keyboard too.

`vid3d serve` only listens on `127.0.0.1`, refuses other host names (DNS-rebinding protection) and requests from other sites, and runs one video at a time.

## How it works

```
video ─► sharp frames ─► camera path (COLMAP) ─► AI depth per frame (Depth Anything V2)
      ─► fuse into one cloud ─► find floor & scale ─► line up walls ─► floor plan + viewer
```

| Stage | What happens |
|---|---|
| 1. Frames | Keep the sharpest frame in each slice of the video |
| 2. Camera path | COLMAP works out where the camera was for every frame, matching all frame pairs so the loop closes |
| 3. Depth | AI depth per frame, fitted to COLMAP's exact points so all frames agree |
| 4. Fuse | Merge into one cloud, keeping only points that at least 2 frames agree on |
| 5. Scale | Find the floor; set metres from camera height, ceiling height, or your calibration |
| 6. Floor plan | Line walls up with the axes and measure wall to wall |

When the video can't support a measurement (too few frames placed, opposite walls
not seen), the tool says so rather than printing a wrong number.

## Quick start

```bash
git clone https://github.com/Srijjit-V/video-to-3d.git
cd video-to-3d
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/vid3d process my_room.mp4        # writes runs/my_room/
.venv/bin/vid3d view runs/my_room          # opens the viewer at http://127.0.0.1:8765
```

The first run downloads the Depth Anything V2 Small model (~100 MB) from Hugging Face.

To use the browser upload instead of the command line: `.venv/bin/vid3d serve`, then drop a video on the page.

**Options for `process`:** `--frames 80` (more = more detail, slower) ·
`--camera-height 1.5` · `--ceiling-height 2.44` · `--fov 70` (~110 for ultra-wide) ·
`--stride 4` (lower = denser cloud)

**Output folder:** `cloud.ply` (also opens in MeshLab, CloudCompare, Blender) ·
`scene.json` (room numbers, warnings, camera path) · `floorplan.png`

## Getting good numbers

**Scale.** A plain video can't tell a room from a scale model, so by default the
tool assumes you held the phone about 1.45 m off the floor (good to roughly ±5–10%).
Tighten it, from best to good:

1. Calibrate in the viewer: measure a door (about 2.03 m) and type its real length.
2. `--ceiling-height 2.44` if the ceiling is visible in the video.
3. `--camera-height 1.5` if you know how high you held the phone.

**Filming.** Walk slowly and turn gradually. Keep the floor and room corners in view.
Walk a loop back to where you started. Blank white walls, mirrors and windows are hard;
good light helps.

## Accuracy

`scripts/make_synthetic_room.py` renders a video of a 5.0 × 4.0 × 2.6 m room with the
camera at 1.5 m. An automated test runs the whole pipeline on it:

| Setting | Result |
|---|---|
| `--camera-height 1.5` (true height) | 4.0 × 5.0 m |
| default (assumes 1.45 m) | 3.85–3.9 × 4.8 m (−3 to −4%, as expected) |

That's a clean synthetic scene; real rooms are noisier. Real-phone results aren't measured yet.

Results vary a little from run to run (the camera solver is not fully deterministic), by a few percent on this scene. The bundled sample room is the first of up to three runs that landed within 6% of the true size.

## Roadmap

From [docs/RESEARCH.md](docs/RESEARCH.md), a review of current open-source work:

- [ ] **Real-world scale without guessing**: Depth Anything 3 Metric (Apache 2.0) predicts depth in metres
- [ ] **Faster, sturdier camera path**: Depth Anything 3 Small/Base estimates poses and depth in one pass
- [ ] **Photo-real view**: Gaussian splatting on the Mac (OpenSplat / msplat) from our existing camera path
- [ ] **Doors, windows, L-shaped rooms**: SpatialLM (non-commercial weights, research only)
- [ ] Real-phone accuracy benchmark

## Deploy the viewer

The viewer is static, so any static host works. `vercel.json` sets the output folder to `viewer` with no build step, and `.github/workflows/pages.yml` publishes the same folder to GitHub Pages.

```bash
npx vercel login
npx vercel deploy --prod --yes      # run inside this folder
```

For GitHub Pages: repo **Settings → Pages → Source: GitHub Actions**; the workflow then deploys on every push that changes `viewer/`.
Nothing that needs COLMAP or torch runs on the host.

## Development

```bash
.venv/bin/python -m pytest -q                                   # unit tests, ~2 s
VID3D_E2E=1 .venv/bin/python -m pytest -q tests/test_e2e.py     # full pipeline accuracy check, ~3 min
node --test "tests/js/*.test.mjs"                               # viewer logic (PLY reader, colours), ~0.2 s
VID3D_UI=1 .venv/bin/python -m pytest -q tests/test_ui.py       # drives the real UI in Chrome with Playwright
VID3D_UI=1 VID3D_E2E=1 .venv/bin/python -m pytest -q tests/test_ui.py   # also drops the synthetic video, ~4 min
.venv/bin/python scripts/make_synthetic_room.py                 # writes samples/synthetic_room.mp4
```

| Path | What's there |
|---|---|
| `src/vid3d/` | Pipeline (`frames`, `sfm`, `depth`, `geometry`, `color`, `floorplan`, `pipeline`) and the local servers (`server`, `cli`) |
| `viewer/` | The static web viewer: `index.html`, `css/`, `js/`, `vendor/three/`, `sample/` |
| `scripts/` | Synthetic test-room generator |
| `tests/` | Python unit tests, Node tests for the viewer (`tests/js`), opt-in Playwright UI and end-to-end tests |
| `docs/` | Research notes, logo, screenshots |
| `DESIGN.md` | The viewer's design language, taken from the Intern Break Space project |

## License

[MIT](LICENSE). The Depth Anything V2 **Small** model used here is Apache 2.0; COLMAP is BSD.

## Built on

[COLMAP](https://colmap.github.io/) / [pycolmap](https://github.com/colmap/pycolmap) ·
[Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) ·
[OpenCV](https://opencv.org/) · [three.js](https://threejs.org/) ·
[PyTorch](https://pytorch.org/) · [Hugging Face Transformers](https://github.com/huggingface/transformers)
