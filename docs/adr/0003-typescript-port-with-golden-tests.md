# ADR-0003: Measuring runs in the browser as a TypeScript port, checked against Python by golden vectors

**Date**: 2026-11-12
**Status**: accepted (backfilled)
**Deciders**: Srijjit (owner), Claude Code (implementation)

## Context

Depth fit, fusion, floor and scale, floor plan, ranges and palette had to run on the user's device without a Python server. Python is the reference implementation.

## Decision

`ts/src` is built by `tsc` to `viewer/js/core` (committed; CI fails if they differ). `scripts/make_golden.py` writes vectors from the Python code; `tests/js/golden.test.mjs` requires the port to match within stated tolerances, and `tests/js/pipeline.test.mjs` requires it to recover an analytic 4 x 5 m room.

## Alternatives Considered

### Alternative 1: Pyodide (Python in the browser)
- **Pros**: One implementation
- **Cons**: Large download, NumPy/OpenCV weight, slower
- **Why not**: Heavier than a port.

### Alternative 2: Keep measuring on a server
- **Pros**: Nothing to port
- **Cons**: Sends depth data off the device, needs GPU or a slow CPU server
- **Why not**: Against the privacy goal.

## Consequences

Two implementations to keep in step; the goldens are the contract. Random draws use a different generator, so some tests are statistical.

### Risks

- A change in Python needs `make_golden.py` re-run and the port updated.
