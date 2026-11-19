# ADR-0007: Hosting: static site on Vercel (and Pages), camera solve on a CPU server (Modal first)

**Date**: 2026-11-18
**Status**: proposed (the site is deployable; no server exists)
**Deciders**: Srijjit (owner), Claude Code (implementation)

## Context

Vercel functions cap request bodies at 4.5 MB and Hobby runs at most 300 s, so frames cannot go through them. COLMAP needs a Linux CPU container. Modal advertises a monthly free credit and per-second CPU billing (search results only; its request-size limit was not found).

## Decision

Vercel serves only the static site. Frames go straight from the browser to a CPU server (`python -m vid3d.sfm_server`, image in `deploy/`, built and run on 2026-11-18, linux/amd64 only). Modal is the first choice; a Hugging Face Docker Space and Fly are fallbacks. Guards still to build: Turnstile, a spend cap, a queue.

## Alternatives Considered

### Alternative 1: ZeroGPU
- **Pros**: Free
- **Cons**: Gradio only, 5-minute daily quota, COLMAP unverified
- **Why not**: Does not fit.

### Alternative 2: Frames through Vercel functions
- **Pros**: One host
- **Cons**: 4.5 MB body cap
- **Why not**: Does not fit.

## Consequences

The site is cheap and static. The server is the only running cost and abuse surface.

### Risks

- Not built or priced: do not expose a public server before the guards exist.
