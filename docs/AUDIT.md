# Audit

Whole-repo audit of video-to-3d at the start of the hardening pass (version 0.1.0, 18 commits, 71 Python tests).
Every item was **verified against the code before it went on this list**; items that turned out to be fine are in
the last section. The **Status** line of each finding is updated as the fix lands (fix and test in the same commit).

**What this repo does and the load assumed.** It turns a phone walkthrough video of a room into a measurable 3D point cloud,
a room-size estimate and a floor plan. It is run by one person on their own computer (`vid3d process`, or `vid3d serve`
on `127.0.0.1`), and the viewer is also published as a static site that never receives a video.
The video is **untrusted input** (a file from a phone, possibly from someone else); so is anything dropped into the viewer.

## Must fix

1. **No limit on the length, size or frame count of the video before it is decoded**
   - **What this is:** `extract_frames` opens the file with OpenCV and decodes every frame.
   - **Problem:** Only a minimum (3 s) and the 2 GB upload cap exist. An 8K clip of an hour, or a file whose header claims
     a huge size, pins the CPU and fills memory. The header numbers can also lie, so they cannot be the only guard.
   - **Fix:** read the header first and refuse above 300 s, 8.3 million pixels per frame (4K) or 20,000 frames, with a plain message;
     also stop while decoding if the real frame count passes the limit. Test: a video over each limit is refused before decoding.
   - **If we skip it:** one bad file can freeze the machine running `vid3d serve`.
   - **Status:** fixed (`frames.py` limits; tests in `tests/test_depth_frames_cli.py`)

2. **`scene.json` stores the full local path of the video**
   - **What this is:** `"video": str(video)`.
   - **Problem:** In `serve` mode that is an absolute path such as `/Users/<name>/Documents/...`. The file is meant to be shared
     (dropped into the hosted viewer, attached to a bug report), so it leaks the username and folder layout.
   - **Fix:** store only the file name. Test: no `/` or `\` in the field, whatever path is given.
   - **If we skip it:** every shared scene discloses where the owner keeps their files.
   - **Status:** fixed (`video_label` in `pipeline.py`; test with POSIX, Windows and relative paths)

3. **Private intermediates of a home video are kept forever**
   - **What this is:** after a run, `frames/` (a photo of the user's room every ~0.4 s), `work/` (COLMAP's feature database)
     and, in `serve` mode, the uploaded original video all stay on disk.
   - **Problem:** Phone videos carry GPS position and device metadata. OpenCV re-encodes the frames without EXIF (checked: 0 tags),
     but the uploaded original still has it, and the frames show the inside of a home.
   - **Fix:** delete `frames/`, `work/` and the uploaded copy when the job ends (success, error or cancel); keep only `cloud.ply`,
     `scene.json` and `floorplan.png`. `--keep-intermediate` turns this off for debugging. The user's own input file is never deleted.
   - **If we skip it:** the tool quietly builds an archive of the inside of the user's home, with location data.
   - **Status:** open

4. **The depth model is downloaded with no pinned revision**
   - **What this is:** `from_pretrained("depth-anything/Depth-Anything-V2-Small-hf")`.
   - **Problem:** The default is "latest". Whoever controls that repo name can change the weights, or pickled code, under every user.
   - **Fix:** pin the exact commit hash and load safetensors only (no pickle). Test: the revision is a 40-character hash and is
     passed to both `from_pretrained` calls.
   - **If we skip it:** a supply-chain attack on the model repository runs on the user's machine.
   - **Status:** open

## Should fix

5. **No integrity hash for the bundled three.js**
   - **What this is:** `viewer/vendor/three/` is bundled (not a CDN) and the CSP only allows same-origin scripts.
   - **Problem:** Nothing detects a modified or corrupted copy.
   - **Fix:** a `modulepreload` link with a SHA-384 `integrity` attribute, a script that checks the vendored file against the
     hash of the official npm package, and a test that fails when the two disagree.
   - **If we skip it:** a tampered vendor file would run unnoticed.
   - **Status:** open

6. **Local server: no socket timeout, no retention limit, thin path-traversal tests**
   - **What this is:** `ServeHandler` and `ViewHandler`.
   - **Problem:** A client that opens a connection and stalls holds a thread forever; finished jobs pile up on disk;
     traversal is tested for `/run/` but not for `/jobs/`.
   - **Fix:** a 60 s socket timeout; keep only the 20 newest finished jobs; tests for encoded, doubled and backslash traversal on `/jobs/`.
   - **If we skip it:** slow-client stalls and a disk that fills up over weeks of use.
   - **Status:** open

7. **No lockfile, no dependency audit, no CI, no SECURITY.md**
   - **Problem:** installs are not reproducible and known-vulnerable dependencies would go unnoticed.
   - **Fix:** hash-pinned `requirements/*.txt`, `pip-audit` in CI, a GitHub Actions workflow, and `docs/SECURITY.md` with a threat model.
   - **If we skip it:** "it worked on my machine" and silent CVEs.
   - **Status:** open

8. **No linter and no type checker**
   - **Fix:** ruff (lint and format check) and mypy on `src/`, both in CI.
   - **If we skip it:** style drift and a class of type bugs reach main.
   - **Status:** open

9. **L-shaped (non-rectangular) rooms get an overestimated area with no warning**
   - **What this is:** the room is always the bounding rectangle of the wall points.
   - **Problem:** an L-shaped room of 30 m² is reported as, say, 42 m², with full confidence.
   - **Fix:** rasterise the wall outline, fill the inside, and compare it to the rectangle; below 88% filled the room is flagged and the
     rectangle area is labelled an upper bound. Test: an L-shaped cloud is flagged and a box is not.
   - **If we skip it:** wrong areas that look precise.
   - **Status:** open

10. **The wall extent uses a fixed 30% histogram threshold**
    - **Problem:** furniture, a door recess or an uneven point density can move which bins count as "the wall", and so the size.
    - **Fix:** measure the sensitivity (thresholds from 15% to 45%, two trimming rules) and report it as part of the uncertainty range
      (see `docs/MATH.md`). Test: the range contains the truth for a box with furniture.
    - **If we skip it:** a single number hides an uncertainty of several centimetres.
    - **Status:** open

11. **The floor finder and ceiling check are tested only on a clean synthetic box**
    - **Fix:** add adversarial clouds: a large tabletop above the floor, a dense shelf band, noise, a tilted camera path,
      a partly visible ceiling, and stray points through a doorway.
    - **If we skip it:** real rooms are not boxes; failures would show up only on the first real video.
    - **Status:** open

12. **One global scale is applied to everything**
    - **What this is:** `s = h / h_raw`, one number for the whole model.
    - **Problem:** a rigid reconstruction has one scale in theory, but drift, or a phone raised and lowered during the walk, breaks that.
    - **Fix:** compare the height of every camera above the fitted floor; a large spread lowers the confidence and is reported.
    - **If we skip it:** a stretched model is trusted as much as a good one.
    - **Status:** open

## Nice to have

13. **A regression test that the bundled sample scenes stay tracked in git.** The `.gitignore` is fine today (verified), but
    `samples/` and `runs/` are ignored one folder away from `viewer/sample/`. **Status:** open
14. **A range and a confidence score for every dimension** (new math, see Step 2 of the work plan and `docs/MATH.md`). **Status:** open
15. **Export the floor plan as SVG and JSON; a before/after calibration readout.** **Status:** open

## Verified fine (items that were suspected and are not problems)

- **three.js is not loaded from a CDN.** It is bundled in `viewer/vendor/three/` (fixed earlier). Only the integrity hash was missing (item 5).
- **A Content-Security-Policy exists** in both `server.py` and `vercel.json` (`script-src 'self'`, no inline scripts or styles).
- **Upload cap, one job at a time, safe names, host check and origin check on POST** exist in `server.py` and have tests.
  Upload size is capped at 2 GB; names are generated hex ids plus a whitelisted extension.
- **Frames carry no EXIF.** They are re-encoded by OpenCV (checked with Pillow: 0 tags).
- **The sample scene is not hidden by `.gitignore`** (`git check-ignore` is silent; the three files are tracked).

## Verdict

Healthy prototype with a correct core, but not safe to point at a stranger's video or to publish scenes from, until items 1 to 4 are fixed.
Fix 1 to 4 first, then 6 to 8, then the correctness items 9 to 12.

## Not checked

- Real phone footage (only a synthetic room has been measured), other operating systems, and GPU or CUDA paths.
- Vulnerabilities inside OpenCV, FFmpeg or COLMAP themselves (only `pip-audit` coverage from item 7).
- The behaviour of the Depth Anything weights on adversarial images.
- Browsers other than Chrome (and Chrome emulating a phone).
