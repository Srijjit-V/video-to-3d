# Verification report

Measured on 2026-11-10 on a MacBook with an Apple M2 chip, Python 3.11, from commit history on `main`.
Everything here was actually run; anything not run is under "Not verified".

## Automated checks

| Check | Command | Result |
|---|---|---|
| Python tests | `python -m pytest -q` | **131 passed, 15 skipped** (the skipped ones are the opt-in browser and full-pipeline tests below) |
| Viewer logic | `node --test "tests/js/*.test.mjs"` | **16 passed** |
| Viewer in real Chrome (Playwright) | `VID3D_UI=1 python -m pytest -q tests/test_ui.py` | **12 passed, 1 skipped** (the skipped one drops a video and needs the full pipeline) |
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

## Not verified

- **Real phone footage.** Every accuracy number is from the synthetic room. The scale prior (8% when assumed) is a judgement, not a measurement. See [BENCHMARK.md](BENCHMARK.md) for the protocol.
- Rooms with mirrors, glass, moving people, very dark or blank surfaces; non-rectangular rooms beyond one synthetic L-shape; ceilings (the sample's ceiling is not detected, so no height is reported).
- Operating systems other than macOS on Apple silicon; CUDA.
- Browsers other than desktop Chrome and Chrome emulating a phone; real touch devices.
- CI: the workflow ran green on GitHub for commits 4d2b203 and d2c0c56 (checked through the public Actions API); later commits were still running when this was written.
- Vercel: not deployed. The Vercel connector refused project creation and the Vercel CLI is not installed. GitHub Pages is the live host.
- Vulnerabilities inside OpenCV, FFmpeg, COLMAP or PyTorch beyond what `pip-audit` reports.
