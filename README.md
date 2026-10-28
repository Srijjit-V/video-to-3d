# video-to-3d

Turn a phone walkthrough video of a room into a measurable 3D point cloud, a
rough room size (length × width, area in m² and ft²) and a top-down floor plan.
A local web viewer lets you orbit the model, click two points to measure, and
calibrate the scale against something you know.

Everything runs locally (tested on an M2 MacBook Air, 8 GB). No cloud services.

## How it works

| Stage | What happens | Tool |
|---|---|---|
| 1. Frames | Keep the sharpest frame in each slice of the video | OpenCV |
| 2. Camera path | Work out where the camera was for every frame | COLMAP (pycolmap) |
| 3. Depth | AI depth per frame, fitted to COLMAP's exact points | Depth Anything V2 Small |
| 4. Fuse | Merge into one cloud, keep only points ≥ 2 frames agree on | NumPy |
| 5. Scale | Find the floor; set metres from camera height or ceiling | NumPy |
| 6. Floor plan | Line walls up with axes, measure wall-to-wall | NumPy / OpenCV |

**Real-world scale.** A plain video can't tell a room from a scale model. By
default the tool assumes the phone was held about 1.45 m above the floor, which
is good to roughly ±5–10%. For better numbers, in order of accuracy:

1. Calibrate in the viewer: measure a door (about 2.03 m) or anything you know.
2. `--ceiling-height 2.44` (only used if the ceiling is visible in the video).
3. `--camera-height 1.5` if you know how high you held the phone.

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

The first run downloads the Depth Anything V2 Small model (~100 MB) from Hugging Face.

## Usage

```bash
.venv/bin/vid3d process my_room.mp4            # writes runs/my_room/
.venv/bin/vid3d view runs/my_room              # opens the viewer at http://127.0.0.1:8765
```

Useful options for `process`: `--frames 80` (more = more detail, slower),
`--camera-height`, `--ceiling-height`, `--fov 70` (use ~110 for ultra-wide lens),
`--stride 4` (lower = denser cloud).

Output folder: `cloud.ply` (open in MeshLab/CloudCompare/Blender too),
`scene.json` (room numbers, warnings, camera path), `floorplan.png`.

### Filming tips

- Walk slowly; turn gradually. Fast turns are where the camera solve breaks.
- Keep the floor and room corners in view; hold the phone at a steady height.
- Walk a loop that comes back to the start; it lets the solve correct drift.
- Blank white walls, mirrors and windows are hard. Good light helps.

## Accuracy check

`scripts/make_synthetic_room.py` renders a video of a 5.0 × 4.0 × 2.6 m room
with a known camera height (1.5 m):

| Setting | Result |
|---|---|
| `--camera-height 1.5` (true height) | 4.0 × 5.0 m |
| default (assumes 1.45 m) | 3.85–3.9 × 4.8 m (−3 to −4%, as expected) |

That is a clean synthetic scene; real rooms will be noisier.

## Development

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/make_synthetic_room.py   # writes samples/synthetic_room.mp4
.venv/bin/vid3d process samples/synthetic_room.mp4 --out runs/synthetic
```

## Project structure

- `src/vid3d/` — pipeline (`frames`, `sfm`, `depth`, `geometry`, `floorplan`, `pipeline`, `cli`)
- `viewer/index.html` — three.js viewer served by `vid3d view`
- `scripts/` — synthetic test-room generator
- `tests/` — unit tests (no model download or COLMAP run needed)
- `runs/`, `samples/` — generated output (gitignored)
