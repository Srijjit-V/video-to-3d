# ADR-0004: The AI runtime loads from a CDN and is hash-checked in the browser before it runs

**Date**: 2026-11-12
**Status**: accepted (backfilled)
**Deciders**: Srijjit (owner), Claude Code (implementation)

## Context

transformers.js and the ONNX Runtime wasm (27 MB) are needed for browser depth. The wasm is too large to commit. GitHub's secret scanner blocked the push of `transformers.min.js` because a constant inside it looks like a Mistral API key (a false positive; the file is byte for byte the npm package).

## Decision

Both files load from jsDelivr at exact versions. The page downloads each, checks its SHA-384 against `viewer/vendor/transformers/HASHES.json` (same origin as the page), and refuses to run it on a mismatch (`fetchVerified` in `viewer/js/depth.js`). CI compares the recorded hashes with the npm packages. The small ONNX loader is bundled.

## Alternatives Considered

### Alternative 1: Bundle everything
- **Pros**: No CDN
- **Cons**: Blocked by push protection; 27 MB wasm
- **Why not**: Not possible without bypassing the scanner.

### Alternative 2: Load from the CDN unchecked
- **Pros**: Simplest
- **Cons**: A changed CDN file would run
- **Why not**: Flagged in review; the check is cheap.

### Alternative 3: Allow the secret in GitHub
- **Pros**: Keeps the vendored file
- **Cons**: An approval that did not take effect after three tries
- **Why not**: Gave up a bundled copy instead.

## Consequences

Integrity at load time; the CSP needs `blob:` in `script-src` and no CDN there. The hashes file shares an origin with the page, so a compromised site is not covered.

### Risks

- The wasm comes from a `-dev` ONNX Runtime build because transformers.js 4.3.2 depends on it.
