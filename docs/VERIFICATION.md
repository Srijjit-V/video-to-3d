# Verification report

Measured on 2026-11-10 on a MacBook with an Apple M2 chip, Python 3.11, from commit history on `main`.
Everything here was actually run; anything not run is under "Not verified".

## Automated checks

| Check | Command | Result |
|---|---|---|
| Python tests | `python -m pytest -q` | **159 passed, 20 skipped** (the skipped ones are the opt-in browser and full-pipeline tests below) |
| Viewer logic | `node --test "tests/js/*.test.mjs"` | **53 passed** |
| Viewer in real Chrome (Playwright) | `VID3D_UI=1 python -m pytest -q tests/test_ui.py` | **16 passed, 1 skipped** (the skipped one drops a video and needs the full pipeline) |
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

## Hybrid server (2026-11-11)

- `tests/test_sfm_server.py` (17 tests, 18 with `VID3D_E2E=1`) and `tests/test_sfm_payload.py` (11): zip validation (count, size, resolution, same size, not a JPEG, names inside the zip never used), body cap checked before reading, Origin allow-list and CORS preflight, one job at a time (503 with Retry-After), per-client minimum interval (429), solver message passed through, temp folder always deleted, EXIF/GPS bytes gone before solving, payload round trip, client refusing non-http URLs.
- Real run: the synthetic room's frames through the server with real pycolmap (36 s test); then `vid3d process --sfm-server` end to end: 60 of 60 frames placed, 4.05 x 5.0 m, area range 18.0 to 22.3 m², confidence high. The server modules do not import torch (checked).
- **Not verified:** the Docker image (`deploy/Dockerfile.sfm`; the Docker daemon was not running here, so it was never built), any public deployment, request-size behaviour behind a real proxy or Modal, rate limits behind a proxy (the limit is per socket address; `X-Forwarded-For` is deliberately not trusted), Turnstile, spend caps.
- One full-suite run showed a single failing test that I could not identify; five full runs and six repeats of the server tests after it all passed. Treat as an unexplained flake.

## Browser upload screen (2026-11-11)

- Node tests: video limits in plain words, Laplacian sharpness, window picking, size fitting, CRC32 check value, and a zip written by `zip.js` that the system `unzip` reads back byte for byte; server-address parsing and camera centres.
- Real Chrome (Playwright, with the strict CSP from `vercel.json`): an H.264 version of the synthetic room goes through frame picking (80 frames, 4.5 MB, 5 s headless and 9 s headed on this machine), the consent screen (nothing is sent before it; the test checks no POST was made), the upload to a real camera-solve server running real COLMAP, and the returned camera path plot. Also: unreadable video, server not running, and refusing at the consent screen (nothing is sent).
- Found while testing: the repo's `samples/synthetic_room.mp4` is MPEG-4 Part 2, which Chrome cannot decode (phones record H.264 or HEVC), so the browser tests re-encode it as H.264 first. Real phone `.mov` (HEVC) in Chrome was not tested, and neither was Safari or any phone browser.
- Frame picking runs on the main thread (not in a worker as the brief asked); it takes seconds, not minutes, but the page may feel unresponsive meanwhile. It uses a `<video>` element, not Mediabunny/WebCodecs.
- The CSP now allows `media-src blob:` (to decode the chosen video locally) and `connect-src` to `http://127.0.0.1:*` and `http://localhost:*` only (a server you run yourself); a hosted server needs its address added to `vercel.json` before it can be used from the deployed page.

## TypeScript port and the browser path (2026-11-12)

- **Port:** `ts/src` builds to `viewer/js/core` (committed; CI fails if they differ). It covers the depth fit, flying-pixel filter, back-projection, voxel fusion, floor and ceiling finding, scale, yaw, floor plan, Monte Carlo ranges, confidence, exposure and colour palette. The PNG drawing was not ported (the SVG/JSON export works from `scene.json`).
- **Golden tests** (`tests/golden/golden.json`, made by `scripts/make_golden.py` from the Python code): deterministic functions match to 6 decimals (back-projection, fusion order and averages, depth filter, wall extent, side support, confidence text, exposure gains). Functions that draw random numbers use their own generator, so the tests allow: depth fit 1.5%, floor normal 0.5 degrees, camera height 2%, yaw 0.2 degrees, range ends 4% of the range width, palette shares 3% and colours 8 per channel. A second golden case has a real ceiling, found by both.
- **Whole chain, no model:** an analytic 4 x 5 x 2.6 m room rendered to depth, fake "AI" disparity with an unknown affine, and sparse points (`tests/js/helpers/synth.mjs`) comes out as exactly 4.0 x 5.0 m, area 20, rectangular, confidence high; with an assumed camera height the 90% area range contains 20 m². Hostile payloads (negative depths, NaN, wrong sizes) are refused or dropped (an automated review found the negative-depth gap; fixed with tests).
- **Real Chrome, real everything:** the H.264 synthetic room, frame picking on the device, consent, the camera-solve server with real COLMAP, the ONNX depth model (`onnx-community/depth-anything-v2-small`, q4f16, pinned revision) on WebGPU at about 0.35 s per frame, the measuring in a worker, the scene opens. 5 runs: 4.1 x 5.1 (twice), 4.05 x 5.1, 4.1 x 5.15, 4.2 x 5.35 m against a true 4.0 x 5.0 m (long side +2%, +2%, +2%, +3%, +7%). One of the runs also flagged the outline as "not a simple rectangle" (low wall support, so the area is called an upper bound and confidence came out medium) while the others did not: the verdict flags are sensitive to run-to-run differences too. The browser test therefore allows 8% and does not assert the flag. The browser path reads about 2 to 3% high on average; I did not isolate whether that comes from the quantised model, JPEG re-encoding or the camera solver.
- **Not verified:** the CPU (WASM) path end to end (about 6 s per frame measured earlier, so about 8 minutes for 80 frames; the test is skipped without WebGPU); Safari; phones; HEVC video; real rooms. transformers.js and the ONNX Runtime wasm (27 MB) load from jsDelivr at pinned versions; the page hash-checks both before running them (unit-tested, and exercised by the Chrome test) and CI compares the recorded hashes with the npm packages. The wasm comes from a `-dev` build of onnxruntime-web because transformers.js 4.3.2 depends on it.

## Not verified

- **Real phone footage.** Every accuracy number is from the synthetic room. The scale prior (8% when assumed) is a judgement, not a measurement. See [BENCHMARK.md](BENCHMARK.md) for the protocol.
- Rooms with mirrors, glass, moving people, very dark or blank surfaces; non-rectangular rooms beyond one synthetic L-shape; ceilings (the sample's ceiling is not detected, so no height is reported).
- Operating systems other than macOS on Apple silicon; CUDA.
- Browsers other than desktop Chrome and Chrome emulating a phone; real touch devices.
- CI: all four jobs (lint/types/vendor hashes, Python and Node tests, the Chrome tests, dependency audit) were green on GitHub for commit a4afc15 (2026-11-12, checked through the public Actions API). Before that, three runs failed in the Chrome job: one test (`test_keyboard_reaches_everything_and_shortcuts_work`) did not get a file chooser after Enter on the drop zone, with the page in a normal state and no errors; it passed on the next run without a code change that touches it, and **I did not find the cause** (it never failed on this Mac). The hybrid end-to-end test is skipped on CI because the runner's software GPU has no `shader-f16`. The test now reports the page state if it fails again.
- Vercel: not deployed. The Vercel connector refused project creation and the Vercel CLI is not installed. GitHub Pages is the live host.
- Vulnerabilities inside OpenCV, FFmpeg, COLMAP or PyTorch beyond what `pip-audit` reports.
