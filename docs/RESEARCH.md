# Research: what others have built, and what we can use

Checked 2026-10-28. Licenses and sizes were read from each project's official
GitHub page. Re-check before shipping anything commercial, since they change.

## Where we are today

Our pipeline: COLMAP finds the camera path → Depth Anything **V2** gives depth per
frame → we fuse it → scale comes from a **guessed camera height (1.45 m)**.

The weak spots, in order of impact:

1. **Scale is a guess** (±5–10%). This is the biggest accuracy problem.
2. **COLMAP is slow and fragile**: ~100 s of matching for 90 frames, and it can
   stall on fast turns or blank walls.
3. **Room shape is a bounding box**: no doors, windows or L-shaped rooms.
4. **Output is a point cloud**, not a photo-real model.

## What's out there

| Project | What it gives | License (weights) | Fits an 8 GB Mac? | Use for |
|---|---|---|---|---|
| [Depth Anything 3](https://github.com/ByteDance-Seed/depth-anything-3) — DA3-SMALL 0.08B / DA3-BASE 0.12B | Camera poses + depth from many images in one pass; video mode | **Apache 2.0** | Likely (small models) | Replace COLMAP + DA2 |
| Depth Anything 3 — DA3METRIC-LARGE 0.35B | Depth in **real metres** from one image (`metric = focal × output / 300`) | **Apache 2.0** | Likely | **Fix the scale guess** |
| Depth Anything 3 — Nested Giant-Large 1.40B | Poses + depth already in metres | CC BY-NC (non-commercial) | No | Best quality, research only |
| [MapAnything](https://github.com/facebookresearch/map-anything) (Meta) | Poses + depth + metric scale factor from images | `map-anything-apache` = **Apache 2.0**; default = non-commercial | Unknown size; CUDA-oriented | Strong alternative on a free GPU |
| [MoGe-2](https://github.com/microsoft/MoGe) (Microsoft) | Metric point map + camera FOV from one image; ViT-S is only 35M params | Code MIT; weight license not stated | **No**: repo says macOS isn't supported | Skip for now |
| [SpatialLM](https://github.com/manycore-research/SpatialLM) | Turns a point cloud into **walls, doors, windows** and furniture boxes | Encoder weights **CC BY-NC** (non-commercial) | No (needs CUDA builds) | Better floor plans, non-commercial only |
| Gaussian splatting on Mac: [OpenSplat](https://radiancefields.com/opensplat-3dgs-now-on-mac), [msplat](https://pypi.org/project/msplat/), [MetalSplat](https://radiancefields.com/metalsplat-v0.3.0-trains-3dgs-and-2dgs-on-apple-silicon), [CorbeauSplat](https://radiancefields.com/platforms/corbeausplat) | Photo-real 3D from our existing COLMAP output | MIT / open | **Yes**, Metal | Photo-real viewer |
| VGGT-SLAM 2.0, ScaRF-SLAM ([paper](https://arxiv.org/pdf/2606.00307)) | Feed-forward models + SLAM, keeps scale consistent on long videos | Research code | GPU | Long or multi-room videos, later |

## Recommendations (ranked)

### 1. Use DA3METRIC to remove the scale guess — biggest win, small change
- Run DA3METRIC-LARGE on the frames we already have. It predicts depth in metres.
- Compare its metric depth with our COLMAP depths at the same pixels. The median
  ratio is the real-world scale, replacing the 1.45 m camera-height guess.
- Keep the camera-height method as a fallback and as a cross-check: if the two
  disagree by more than ~10%, warn.
- Apache 2.0, so commercial use is fine. **Check first:** that it installs and runs on
  Apple Silicon (the repo lists `xformers`, which is CUDA-oriented; the Hugging Face
  weights may load without it).

### 2. Try DA3-SMALL/BASE instead of COLMAP — faster, more robust
- One model pass gives camera poses and depth for a whole clip, with a video mode.
- Could cut the ~2–3 minute run and remove the "only 11/90 frames placed" failures.
- Keep COLMAP as a fallback until DA3 matches it on the synthetic test (the e2e
  test already measures this).

### 3. Photo-real view with Gaussian splatting — nice to have
- We already produce COLMAP camera poses, which is exactly what splat trainers need.
- Add `vid3d export-colmap` → train with OpenSplat or msplat on the Mac (Metal) → show
  in the browser with a splat viewer. Measuring stays on the point cloud.

### 4. Doors, windows, L-shaped rooms with SpatialLM — research only
- Very good fit for floor plans, but the weights are **non-commercial** and it needs
  an NVIDIA GPU. Fine for experiments on a free GPU; not for a product.

## Free ways to run the bigger models

Everything in the current pipeline already runs free on your Mac. For models
too big for 8 GB:

| Option | What you get free | Good for |
|---|---|---|
| [Kaggle Notebooks](https://www.kaggle.com/code) | ~30 GPU hours/week (P100/T4), 12 h sessions | Running MapAnything / DA3-Giant / SpatialLM on a video |
| Google Colab (free) | T4 GPU, 12 h sessions, no published quota | Same, quick experiments |
| Hugging Face ZeroGPU Spaces | ~5 min GPU/day per signed-in user, Gradio only | A public web demo |
| Lightning AI (free tier) | Monthly credits (amount varies) | Longer runs |

Quotas come from third-party summaries and change often; check each site's
account page. No paid APIs are needed for any recommendation above.

## Sources

- MapAnything: [repo](https://github.com/facebookresearch/map-anything), [paper](https://arxiv.org/pdf/2509.13414)
- Depth Anything 3: [repo](https://github.com/ByteDance-Seed/depth-anything-3), [DA3METRIC-LARGE card](https://huggingface.co/APaul1/DA3METRIC-LARGE)
- MoGe-2: [repo](https://github.com/microsoft/MoGe), [paper](https://arxiv.org/pdf/2507.02546)
- SpatialLM: [repo](https://github.com/manycore-research/SpatialLM)
- VGGT-SLAM 2.0: [paper](https://arxiv.org/pdf/2601.19887); ScaRF-SLAM: [paper](https://arxiv.org/pdf/2606.00307)
- Splatting on Mac: [OpenSplat](https://radiancefields.com/opensplat-3dgs-now-on-mac), [msplat](https://pypi.org/project/msplat/), [MetalSplat](https://radiancefields.com/metalsplat-v0.3.0-trains-3dgs-and-2dgs-on-apple-silicon), [CorbeauSplat](https://radiancefields.com/platforms/corbeausplat), [Splat Apple](https://github.com/ghif/splat-apple)
- Free GPUs: [gpuperhour.com](https://gpuperhour.com/blog/free-cloud-gpus-and-credits), [aimultiple.com](https://aimultiple.com/free-cloud-gpu)
