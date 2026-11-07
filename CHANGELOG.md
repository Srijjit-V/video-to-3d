# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Web viewer rebuilt as a standalone static site (`viewer/`, three.js bundled, no build step): landing with explanation and repo link, drag-and-drop, bundled sample room, phone layout, keyboard shortcuts.
- `vid3d serve`: drop a video in the browser; live six-stage progress from the real pipeline log (frame counts, elapsed time), cancel, advanced options (camera height, ceiling height, field of view), plain-language errors.
- Hosted mode: says honestly it can't process videos; opens the sample room or a dropped `cloud.ply` + `scene.json` (+ `floorplan.png`) entirely in the browser.
- Colour: colour picker (RGB, hex, swatch), colour by true colour / height / distance from camera path / frames that saw each point, room palette card (k-means on wall, floor and ceiling points, saved in `scene.json`).
- `cloud.ply` gets a `views` property (how many frames saw each point).
- Gentle exposure and contrast normalisation across frames before colours are fused.
- `DESIGN.md` (from the Intern Break Space design system), `vercel.json` and a GitHub Pages workflow.
- Tests: palette, view count, exposure, server (host/origin checks, uploads, jobs), Node tests for the viewer logic, contrast check, opt-in Playwright UI tests.
- `vid3d process`: video → sharp frames → COLMAP camera path → Depth Anything V2 depth → fused metric point cloud, room size/area estimate and floor-plan PNG.
- Floor and ceiling detection from horizontal point layers; scale from assumed or given camera height, or known ceiling height.
- Automatic wall alignment and wall-to-wall room measurement.
- Quality warnings (few frames placed, missing walls, guessed scale) in output and viewer.
- All-pairs frame matching for ≤150 frames (closes loops, prevents drift) and automatic retry when the camera solve stalls.
- `vid3d view`: local three.js viewer with point measuring (m and ft/in), scale calibration, top-down view and floor plan.
- Synthetic known-size room generator for accuracy checks; unit tests.

### Docs
- MIT license.
- New README with logo, quick start and roadmap.
- `docs/RESEARCH.md`: review of open-source 3D reconstruction work (Depth Anything 3, MapAnything, MoGe-2, SpatialLM, Gaussian splatting on Mac) and free GPU options.

### Fixed
- A blurry or sparse wall opposite a dense one no longer makes the room 'not measurable'; the trimmed spread is used when the wall peaks don't span it.
- The 'scale is a guess' warning no longer shows when you gave the camera height.
- Short clips no longer keep up to twice the requested frames (which could skip all-pairs matching and stretch the room).

### Removed
- Unused `visible_floor_m2` output and unused sparse-point export.

### Security
- Viewer escapes all text from scene.json before inserting it into the page.
- Viewer server only answers requests addressed to 127.0.0.1/localhost (blocks DNS rebinding).
- Camera-solve subprocess runs with Python safe-path mode so stray files in the current folder can't be imported.
