# ADR-0002: Hybrid mode (server solves the camera path) is the default; colmap-wasm stays experimental

**Date**: 2026-11-11
**Status**: accepted (backfilled from the Phase 0 spike; updated 2026-11-19: the experimental mode is now wired in)
**Deciders**: Srijjit (owner), Claude Code (implementation)

## Context

The Phase 0 spike (docs/VERIFICATION.md) ran colmap-wasm 0.1.0 in Chrome on the synthetic room. With its default all-pairs matching it took 139 s and produced a wrong camera path (room 1.25 x 2.65 m for 4 x 5 m). With sequential pairing it took 24 s and gave 4.0 x 5.0 m (true camera height) or -5.4% area (assumed height). One room, one machine.

## Decision

The default mode sends about 80 resized JPEGs (never the video) to a CPU server running pycolmap and returns the payload. The server has no torch. colmap-wasm is an experimental mode behind an "In this browser (experimental)" option (wired in on 2026-11-19, offered only when capability detection says the browser can run it) and is not the default until it passes the 6% gate on more rooms. On the one synthetic room it measured -1% / 0%.

## Alternatives Considered

### Alternative 1: colmap-wasm as default
- **Pros**: No server, no upload
- **Cons**: Failed the gate with default settings; passed once with a different setting on one room
- **Why not**: Not enough evidence.

### Alternative 2: Upload the whole video
- **Pros**: Simplest
- **Cons**: 10x more data, more private, more cost
- **Why not**: Frames are enough.

## Consequences

Works on any laptop; frames leave the device only after a consent screen. A server is required, and none is deployed yet.

### Risks

- Cost and abuse need guards (rate limits, caps, a spend cap, bot protection), most of which are not built.
