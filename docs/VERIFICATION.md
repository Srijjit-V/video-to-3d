# Verification report

Measured on 2026-11-10 on a MacBook with an Apple M2 chip, Python 3.11, from commit history on `main`.
Everything here was actually run; anything not run is under "Not verified".

## Automated checks

| Check | Command | Result |
|---|---|---|
| Python tests | `python -m pytest -q` | **131 passed, 16 skipped** (the skipped ones are the opt-in browser and full-pipeline tests below) |
| Viewer logic | `node --test "tests/js/*.test.mjs"` | **16 passed** |
| Viewer in real Chrome (Playwright) | `VID3D_UI=1 python -m pytest -q tests/test_ui.py` | **13 passed, 1 skipped** (the skipped one drops a video and needs the full pipeline) |
| Lint | `ruff check .` (pyflakes, pycodestyle, bugbear, pyupgrade, bandit rules, import order) | clean |
| Types | `mypy` on `src/vid3d` | clean, 12 files |
| Dependency audit | `pip-audit -r requirements/lock-py311.txt --no-deps --disable-pip` | no known vulnerabilities |
| Bundled three.js | `python scripts/verify_vendor.py` | hashes match; `three.module.min.js` is byte-identical to the npm package `three@0.160.0` |

Test files by count: server 30, uncertainty 17, depth/frames/cli/privacy 21, floorplan 16, geometry 14, design contrast 23, colour 8, vendor integrity and tracked samples 3, UI 13 (opt-in), end-to-end 1 (opt-in).
CI (`.github/workflows/ci.yml`) runs the same lint, types, vendor check, tests, Playwright viewer tests and the audit on every push.

## End-to-end accuracy (synthetic room only)

`scripts/make_synthetic_room.py` renders a 5.0 x 4.0 x 2.6 m room with the camera at 1.5 m and a 0.9 x 2.03 m door. The whole pipeline was run on it twice:

| Scale source | Measured | Truth | Error (L, W, area) | 90% range for the area | Contains truth? | Confidence |
|---|---|---|---|---|---|---|
| `--camera-height 1.5` (the true height) | 4.05 x 5.00 m, 20.25 m² | 4.0 x 5.0, 20 m² | +1.3%, 0%, +1.3% | 18.1 to 22.2 m² | yes | high (90/100) |
| default (assumes 1.45 m) | 3.90 x 4.85 m, 18.91 m² | 4.0 x 5.0, 20 m² | -2.5%, -3.0%, -5.5% | 13.9 to 24.4 m² | yes | low (45/100) |

Length and width ranges also contained the truth in both runs. The error with the default is what the maths predicts: the phone was 3.3% higher than assumed,
so lengths come out 3.3% short and area 6.5% short.
The confidence is "low" for the default run mostly because the range is wide (+-27% on area), which is the honest answer when the scale is a guess.

The camera solver is not fully deterministic: repeated runs on this video differ by a few percent. One run per setting is reported above; it is not a distribution.

## The two bundled demo scans

| Scene | What it is | What the program says |
|---|---|---|
| `viewer/sample` | the first run above | size 4.05 x 5.0 m, high confidence, no warnings |
| `viewer/sample-bad` | the same cloud with the far 45% removed, then re-analysed with the real code (not a separate video) | "at least 4.05 x 2.73 m", area "at least 9.8 m²", confidence low (35/100), warning that a wall was never filmed |

## What the tests prove, and what they do not

- Range logic: a unit test asserts the 90% range contains the truth for phones really held at 1.3, 1.45, 1.5 and 1.6 m while 1.45 m is assumed, that the area range is 1.7 to 2.3 times as wide (relatively) as the length range, and that better scale sources give narrower ranges.
  It is a test of the model on a synthetic cloud, not a calibration against real rooms.
- Floor and ceiling finding: 8 adversarial synthetic rooms (tabletop, sofa top, noise, sparse floor, wrong up hint, doorway strays, partial ceiling, mezzanine). All passed.
- Security fixes each have a test that fails without the fix (video limits, file name only, deleted private files, pinned model, integrity hash, traversal cases, socket timeout, job pruning).

## Phase 0 spike: running parts of the pipeline in the browser (2026-11-11)

Measured once, on one machine (MacBook, Apple GPU, 8 GB, Chrome 157 headed, WebGPU available), with the synthetic room.
Scripts: `scripts/spike/depth_spike.py`, `colmap_spike.py`, `gate.py`. One run each; these are first measurements, not benchmarks.

| What | Result |
|---|---|
| Depth Anything V2 Small, q4f16 ONNX (`onnx-community/depth-anything-v2-small`, transformers.js 4.3.2) | file 19.1 MB (`Content-Length` 19,126,267) |
| Depth, WebGPU, 640 x 480 frame | load 5.3 s; frames 2254 (first), 374, 355, 649 ms |
| Depth, WASM, same frame | load 1.0 s; frames 6580, 5893, 6126, 6170 ms (about 6 s per frame, so 60 frames is about 6 minutes) |
| colmap-wasm 0.1.0 (BSD-3, unofficial COLMAP 4.2.1 build, 7.2 MB package), 60 frames 640 x 480, **all pairs** (default) | 139 s (mapping 130 s), 60 of 60 placed, **but the camera path did not match pycolmap's** (similarity-fit residual 3.0 units on a 7-unit path) and the room came out 1.25 x 2.65 m for a 4 x 5 m room. **Fails the gate.** |
| colmap-wasm, same frames, **sequential pairs** (window 8, loop) | 24 s (features 5.2 s, matching 0.9 s, mapping 18 s), 60 of 60 placed, focal 457.1 px (pycolmap: 456.6) |
| Room size from those poses, rest of the Python pipeline, true camera height 1.5 m | 4.0 x 5.0 m (0.0%, 0.0%), area range 18.0 to 22.2 m² contains the true 20 m² |
| Same, default 1.45 m assumed | 3.9 x 4.85 m (-2.5%, -3.0%), area -5.4%, range 13.9 to 24.4 m² contains truth |

What this says: depth runs in the browser (WebGPU about 0.4 s per frame after warm-up; WASM is about 15 times slower).
colmap-wasm is accurate enough **only with sequential pairing**; with its default all-pairs matching it failed on this video. So the browser camera solver is
usable for walkthrough video with that setting, and Hybrid (server) stays the safer default until more rooms are tried.
The poses were fed to the Python stages through the new sfm payload (`src/vid3d/sfm_payload.py`, `process(..., sfm_payload=...)`), the seam the browser and server modes will share.
`k1` is 0 for colmap-wasm (it estimates a SIMPLE_PINHOLE camera, no lens distortion).

Not tested: Safari, any phone browser, WebGPU-less machines, other GPUs, more than one room, depth quality of the q4f16 model compared with the PyTorch model (only speed and size were measured).
The Modal limits and prices below are from search results, not from reading Modal's own docs; the request-body limit was not found. Check before relying on them.

## Not verified

- **Real phone footage.** Every accuracy number is from the synthetic room. The scale prior (8% when assumed) is a judgement, not a measurement. See [BENCHMARK.md](BENCHMARK.md) for the protocol.
- Rooms with mirrors, glass, moving people, very dark or blank surfaces; non-rectangular rooms beyond one synthetic L-shape; ceilings (the sample's ceiling is not detected, so no height is reported).
- Operating systems other than macOS on Apple silicon; CUDA.
- Browsers other than desktop Chrome and Chrome emulating a phone; real touch devices.
- CI: the workflow ran green on GitHub for commits 4d2b203 and d2c0c56 (checked through the public Actions API); later commits were still running when this was written.
- Vercel: not deployed. The Vercel connector refused project creation and the Vercel CLI is not installed. GitHub Pages is the live host.
- Vulnerabilities inside OpenCV, FFmpeg, COLMAP or PyTorch beyond what `pip-audit` reports.
