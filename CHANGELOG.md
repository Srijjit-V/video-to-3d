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
