# Security

## Reporting a problem

Open a private security advisory on the repository (Security tab, "Report a vulnerability"), or an issue that
does not include exploit details. This is a one-person portfolio project: expect a reply in days, not hours.

## What is protected, and from whom

video-to-3d runs on **one person's own computer**. The video, the frames and the 3D model show the inside of someone's
home and can carry their location, so privacy is part of the threat model.

| Asset | Who could get it | How it is protected |
|---|---|---|
| The video file (may hold GPS and device metadata) | Anyone who can read the disk later; another website talking to the local server | The uploaded copy is deleted when the job ends (success, error or cancel). The server listens on `127.0.0.1` only and refuses other `Host` and `Origin` headers. |
| Frames (a photo of the room every ~0.4 s) and COLMAP's database | Same | Deleted when the run ends (`--keep-intermediate` to keep them for debugging). Only folders the run created are deleted, never symlinks. |
| `scene.json`, `cloud.ply` | Anyone it is shared with | `scene.json` holds the video **file name** only, never a path. Review a scene before you share it: the point cloud still shows the room. |
| The machine running `vid3d serve` | A malicious or broken video; a malicious web page open in the same browser | Length, size and frame-count limits before decoding. One job at a time. Idle sockets dropped after 60 s. Old jobs pruned. No shell is ever used; the pipeline is started with a fixed argument list. |
| The viewer's users | A tampered script or dependency | three.js is bundled (no CDN), checked against a SHA-384 hash in the page, and the Content-Security-Policy allows scripts from the same origin only, no inline script. |

## The hosted page's script and network policy (`vercel.json`)

`script-src 'self' 'wasm-unsafe-eval' blob:`. `'wasm-unsafe-eval'` lets the AI runtime compile WebAssembly. `blob:` is needed because the page runs the AI library from a blob it has just hash-checked, and ONNX Runtime loads its own loader through a blob URL; creating a blob already requires running script, so it adds little, but it is a loosening and is recorded here. No inline script, no `unsafe-eval`, no CDN in `script-src`.
`connect-src` allows the site itself, `blob:`, a camera-solve server on `127.0.0.1`/`localhost` (any port), `huggingface.co` and `*.hf.co` (the model, at a pinned revision; the CDN host name depends on the region, so a fixed list is not possible), and `cdn.jsdelivr.net`. `media-src blob:` decodes the chosen video locally; `worker-src 'self'`.

**AI runtime integrity.** transformers.js (4.3.2) and the ONNX Runtime wasm (27 MB, from the `-dev` build that transformers.js 4.3.2 depends on) are not bundled: transformers.js cannot be committed because GitHub's secret scanner flags a constant inside it, and the wasm is too large. They load from jsDelivr at exact versions, and **the page downloads each one, checks its SHA-384 against `viewer/vendor/transformers/HASHES.json` and refuses to run it on a mismatch** (`fetchVerified` in `viewer/js/depth.js`, with a test). CI also compares the recorded hashes with the npm packages (`scripts/verify_vendor.py --official`). The small ONNX Runtime loader is bundled. The hashes file is served by the same site as the page, so this protects against a changed CDN file, not against a compromise of the site itself.

A hosted camera-solve server must be added to `connect-src` before the deployed page can use it. The consent screen shows exactly what is sent and to which host before anything leaves the device.

## Hybrid camera-solve server (`vid3d.sfm_server`)

Separate from `vid3d serve`. It receives frames, so it is a boundary of its own: body cap checked from `Content-Length` before reading, at most 120 frames and 1280 px each, all the same size, every frame decoded and **re-encoded** (this drops EXIF and GPS), server-made file names, Origin allow-list for browsers, one job at a time, a per-client minimum interval, a 900 s solver timeout, a temp folder deleted in every case, no request logging, no stack traces to clients. The payload it returns is validated again by whoever receives it. **Not yet in place:** bot protection, a spend cap, TLS (put it behind a proxy that terminates TLS), and a hardened container image build.

## Trust boundaries

1. **Browser to local server** (`vid3d serve`): untrusted. Checks: Host allow-list (DNS rebinding), Origin check on every POST, `application/octet-stream` only, size cap (2 GB), file-extension allow-list, server-generated ids and file names (never taken from the client), only three named result files are served from a job folder.
2. **Video to decoder**: untrusted. OpenCV/FFmpeg parse it; limits are checked from the header and again while decoding. Decoder bugs themselves are out of reach of this project: keep OpenCV updated (the lockfile and `pip-audit` in CI help).
3. **Network to the model download**: pinned to one Hugging Face commit and loaded as `safetensors` (no pickle), so the download cannot run code.
4. **Dropped files in the hosted viewer**: parsed in the browser only; nothing is uploaded. The PLY and JSON readers validate sizes and counts, and values are written to the page with `textContent` or escaped.

## Not covered

- Anyone with access to your user account on the computer (they can read what you can).
- Vulnerabilities in OpenCV, FFmpeg, COLMAP, PyTorch or the browser (tracked only through `pip-audit` on the lockfile).
- Running `vid3d serve` bound to anything but `127.0.0.1`: not supported.
- Metadata inside **your original video**: the tool never modifies your file. Strip GPS before sharing the original.

## Dependency hygiene

- `requirements/lock-py311.txt` pins every Python dependency by hash; install with
  `pip install --require-hashes -r requirements/lock-py311.txt` for a reproducible environment.
- CI runs `pip-audit` on that lockfile, `ruff` (including security rules), `mypy` and the tests on every push.
