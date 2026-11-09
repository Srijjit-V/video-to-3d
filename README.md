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
  <a href="#run-it-on-your-mp4-video">Run it on your video</a> ·
  <a href="#how-it-works-the-idea-in-plain-words">How it works</a> ·
  <a href="DESIGN.md">Design language</a>
</p>

<p align="center">
  <img src="docs/screenshots/desktop-scene.png" alt="The viewer showing the sample room with its palette and measurements" width="760">
</p>

---

Film a slow walk around a room with your phone. `video-to-3d` turns that video into a 3D model you can spin around, measure and colour-pick, plus the room's size, a floor plan and its main colours.

It is free, runs on your own computer, and needs no special camera and no account.

## Run it on your mp4 video

**What you need:** a computer with **Python 3.11** (tested on a MacBook with an Apple M2 chip; other computers are untested) and about **2 GB of free disk space**. The first run also downloads a ~100 MB AI model, so you need internet that once.

### Step 1: Film the room
- Walk **slowly** around the room for **10 to 30 seconds** and turn gradually. Fast spins ruin it.
- Keep the **floor and the room's corners** in view, and walk a loop that ends where you started.
- Use good light. Blank white walls, mirrors and windows are hard for it.
- An **.mp4** or **.mov** file is fine (`.m4v`, `.webm`, `.avi` and `.mkv` work too).

### Step 2: Install it (once)
Open a terminal and run these three lines:
```bash
git clone https://github.com/Srijjit-V/video-to-3d.git
cd video-to-3d
python3.11 -m venv .venv && .venv/bin/pip install -e .
```

### Step 3: Run it on your video
**The easy way (click and drop):**
```bash
.venv/bin/vid3d serve
```
A page opens in your browser. **Drop your mp4 on it.** You see a progress list for the six steps, with a cancel button. When it finishes (about 3 minutes), the 3D room opens by itself.

**The command-line way:**
```bash
.venv/bin/vid3d process my_room.mp4     # makes the 3D model in runs/my_room/
.venv/bin/vid3d view runs/my_room       # opens it in your browser
```

That's it. In the 3D room you can drag to spin it, click **Measure** and click two points to get a real distance, and click **Pick colour** to read any colour. More on that in [Web viewer](#web-viewer).

**What you get** (in `runs/my_room/`): `cloud.ply` (the 3D dots; also opens in MeshLab, CloudCompare and Blender), `scene.json` (the room size, colours and warnings), and `floorplan.png`.

**Good to know:** it prints the room as, for example, `room ≈ 5.0 x 4.05 m, area ≈ 20.25 m²`. If you know how high you held the phone, add `--camera-height 1.5` (in metres) for a more accurate size.

## How it works (the idea in plain words)

You judge distance because **each eye sees a slightly different picture**. A walk-through video is the same trick with hundreds of "eyes" spread along your path. The program works backwards from those pictures to the shape of the room.

```
your video
   │  1. keep the sharpest pictures
   ▼
 ~80 sharp photos
   │  2. find where the phone was for each photo
   ▼
 camera path
   │  3. let an AI guess the distance of every pixel, then correct it
   ▼
 a depth for every photo
   │  4. combine them into one cloud of coloured dots
   ▼
 3D point cloud
   │  5. find the floor and set the real-world size
   │  6. straighten the walls, measure, draw the floor plan
   ▼
 size, floor plan, colours, 3D viewer
```

1. **Keep the sharpest pictures.** A video is about 30 pictures a second, and most are near-copies or blurry. It splits the video into equal slices and keeps the sharpest frame from each, about 80 in all.
2. **Work out where you were standing.** It spots the same small details (the corner of a picture frame, a spot on the floor) in several photos. Because they sit in different places in each photo, geometry reveals where the camera was and which way it pointed. This uses [COLMAP](https://colmap.github.io/), a well-known free tool. The result is your walking path (the orange loop in the viewer). It compares every photo with every other photo so the loop closes properly and the room doesn't drift out of shape.
3. **Guess how far away everything is.** An AI model ([Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2)) looks at each photo and estimates the distance of every pixel. It is good at shapes but not at true distances. Step 2 gives a few exact distances per photo, so the AI's guess is stretched to match them. The AI fills the gaps, and the geometry keeps it honest.
4. **Combine everything into one 3D cloud.** Each pixel becomes a coloured dot in space. A dot is kept only if **at least two photos agree on it**, which throws away most mistakes. Each dot keeps the real colour from your video (after evening out the brightness between photos).
5. **Find the floor and set the real size.** The floor is the big flat layer at the bottom. A plain video can't tell a big room from a small model of it, so the program assumes you held the phone about **1.45 m** above the floor. That turns the model's arbitrary units into metres. You can give it your real camera height, the ceiling height, or the length of something you know (like a door) to make it exact.
6. **Straighten the walls and measure.** It rotates the room so the walls are square, measures from wall to wall, draws the floor plan, and finds the main wall, floor and ceiling colours.

**It never pretends.** If the video can't support a measurement (too few photos matched, or only one side of the room was seen), it shows a plain-language warning instead of a wrong number.

### If something goes wrong
| What you see | What it means | What to do |
|---|---|---|
| "The video is only 1.0 seconds long" | Too short to work out depth | Film at least 3 seconds (10 to 30 is best) |
| "Only 20 of 80 frames could be placed" | The camera path couldn't be solved for most of the video | Walk slower; avoid blank walls; keep more of the room's detail in view |
| "Opposite walls were not both captured" | It saw only one side of the room | Walk so every wall appears at some point |
| The size is a few percent off | The scale is a guess from phone height | Measure a door in the viewer and type its real length, or use `--camera-height` |
| The first run is slow | It is downloading the AI model once | Wait; later runs are faster |

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

## Getting good numbers

**Scale.** By default the tool assumes the phone was about 1.45 m off the floor (good to roughly ±5 to 10%). To tighten it, from best to good:

1. Calibrate in the viewer: measure a door (about 2.03 m) and type its real length.
2. `--ceiling-height 2.44` if the ceiling is visible in the video.
3. `--camera-height 1.5` if you know how high you held the phone.

**All the options for `process`:** `--frames 80` (more = more detail, slower) · `--camera-height 1.5` · `--ceiling-height 2.44` · `--fov 70` (about 110 for an ultra-wide lens) · `--stride 4` (lower = denser cloud).

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
