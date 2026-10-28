# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- `vid3d process`: video → sharp frames → COLMAP camera path → Depth Anything V2 depth → fused metric point cloud, room size/area estimate and floor-plan PNG.
- Floor and ceiling detection from horizontal point layers; scale from assumed or given camera height, or known ceiling height.
- Automatic wall alignment and wall-to-wall room measurement.
- Quality warnings (few frames placed, missing walls, guessed scale) in output and viewer.
- All-pairs frame matching for ≤150 frames (closes loops, prevents drift) and automatic retry when the camera solve stalls.
- `vid3d view`: local three.js viewer with point measuring (m and ft/in), scale calibration, top-down view and floor plan.
- Synthetic known-size room generator for accuracy checks; unit tests.

### Docs
- New README with logo, quick start and roadmap.
- `docs/RESEARCH.md`: review of open-source 3D reconstruction work (Depth Anything 3, MapAnything, MoGe-2, SpatialLM, Gaussian splatting on Mac) and free GPU options.

### Fixed
- Short clips no longer keep up to twice the requested frames (which could skip all-pairs matching and stretch the room).

### Removed
- Unused `visible_floor_m2` output and unused sparse-point export.

### Security
- Viewer escapes all text from scene.json before inserting it into the page.
- Viewer server only answers requests addressed to 127.0.0.1/localhost (blocks DNS rebinding).
- Camera-solve subprocess runs with Python safe-path mode so stray files in the current folder can't be imported.
