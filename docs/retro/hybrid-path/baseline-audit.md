# Baseline audit: the hybrid path (2026-11-18)

Method: ECC `brownfield-retrospective`, run inline (no subagents), through the python-reviewer, security-reviewer and silent-failure-hunter lenses. Nothing was fixed while this was written; findings went to [gap-register.md](gap-register.md).

## Perimeter
Slice: the code added after the first audit ([../../AUDIT.md](../../AUDIT.md)): `src/vid3d/sfm_server.py`, `sfm_client.py`, `sfm_payload.py`; `viewer/js/app.js` (hybrid flow), `hybrid.js`, `depth.js`, `zip.js`, `frames.js`; `ts/src/pipeline.ts`, `scene-worker.ts`; `vercel.json`, `.github/workflows/`, `deploy/`. About 1,500 lines. Entry points: `POST /v1/sfm`, `solve_remote`, the page's `startHybrid`. Blast radius: whoever runs the server, and the owner of any frames sent to it.

## Snapshot
- Tests (before the fixes): 185 Python (20 opt-in skipped), 53 Node, 17 browser (1 skipped); CI green on `ef33a2f`.
- `pip-audit` on the hash-pinned lockfile: no known vulnerabilities. `npm audit`: 0.
- TODO/FIXME/HACK in the slice: none.
- Swallowed errors in the slice: 12 `catch`/`except` sites. Benign (storage blocked, no WebGPU, floor not found on a random subset) except one: the server's catch-all `except Exception` returned a generic 500 and logged nothing (G-004).
- Docker image: written, never built. Mermaid: never rendered. Actions: referenced by tag.

## Findings by lens (each with where)
- Hostile client: `sfm_server.py` `_handle` accepted `Content-Length: -1` and called `rfile.read(-1)` (reads until the client stops, G-001). `read_frames` decoded a JPEG before checking the size its header claims (G-002).
- Untrusted server: `sfm_client.py` read the whole answer and the whole error body with no cap, and let a non-JSON answer escape as a raw `ValueError` (G-003).
- Silent failure: see G-004.
- Config: `vercel.json` had no `Permissions-Policy` (G-005); workflow actions pinned by tag (G-006).
- Deployment: image never built (G-007); diagrams never rendered (G-008).
- Practice and missing features (known, deferred): rate limit keyed on the socket address (G-009); no bot protection, spend cap or queue (G-010); frame picking on the main thread (G-011); the 90% range does not model solver variance (G-013).
