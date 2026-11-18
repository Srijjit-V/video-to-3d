# ADR-0001: The camera-pose payload is the seam between solving and measuring

**Date**: 2026-11-11
**Status**: accepted (backfilled: decided and built 2026-11-11)
**Deciders**: Srijjit (owner), Claude Code (implementation)

## Context

Everything before camera poses needs only frames; everything after needs only the frames plus a little sparse camera data. COLMAP is the heavy, native-only step. The browser, a server and the Python CLI all need to plug in at the same point.

## Decision

We pass a small, versioned, validated JSON payload (`src/vid3d/sfm_payload.py`): one shared camera (focal, centre, k1) and per frame R, t and sparse observations (u, v, z). It is checked on both sides (sizes, finite numbers, file-name pattern, depth > 0).

## Alternatives Considered

### Alternative 1: Share the whole COLMAP sparse model
- **Pros**: Complete, standard
- **Cons**: Large, needs COLMAP readers in the browser
- **Why not**: The browser needs only poses and per-frame depths.

### Alternative 2: Solve in the browser only
- **Pros**: No server
- **Cons**: colmap-wasm missed the accuracy gate with its default pairing (ADR-0002)
- **Why not**: Too fragile to be the only path.

## Consequences

Any solver can be swapped in; the payload is under 1 MB for 80 frames. The payload is untrusted input everywhere it is read.

### Risks

- A format change needs a version bump and both implementations updated; tests cover the validators.
