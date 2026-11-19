# Status

Updated 2026-11-18. Verified numbers live in [VERIFICATION.md](VERIFICATION.md); this page says what is healthy, blocked or intentionally removed.

## Health
| Area | State |
|---|---|
| Python pipeline, CLI, local server | working; 201 tests pass |
| Browser measuring (TypeScript port, browser depth) | working end to end in Chrome with a camera-solve server; 56 Node tests, golden vectors match Python |
| Viewer (demo, colours, export, themes) | working; 19 browser tests, 48 contrast checks across both themes |
| CI | green on the last code commit (see VERIFICATION.md for the one unexplained earlier failure) |
| Accuracy | measured only on a synthetic room (browser path: 2 to 3% high on average, one run 7% high); **real phone video has not been tested** |

## Blocked or waiting on the owner
- **Vercel deploy**: needs `npx vercel login` (the CLI is logged out here). GitHub Pages is live.
- **Public camera-solve server**: none exists (the Docker image builds and works, see VERIFICATION.md). Needs a Modal account and spend cap, Turnstile, a queue. Do not expose `vid3d.sfm_server` publicly before those ([ADR-0007](adr/0007-hosting-vercel-static-modal-cpu.md)).
- **Front-end stack**: React/Vite/Tailwind is proposed, not decided ([ADR-0005](adr/0005-front-end-stack.md)).
- **Real-phone benchmark**: needs footage and tape-measured rooms ([BENCHMARK.md](BENCHMARK.md)).

## Not built
Safari and phone-browser tests of the upload flow (only the page and demo were run in WebKit), HEVC video test, resume after a dropped connection, Mediabunny/WebCodecs decoding (frames come from a `<video>` element on the main thread).

## Open audit rows
See [retro/hybrid-path/gap-register.md](retro/hybrid-path/gap-register.md): G-009 proxy-aware rate limit, G-010 bot protection / spend cap / queue, G-011 frame picking off the main thread; G-013 (range vs solver variance) is wont-fix until real-room data exists.

## Delete zone (do not recreate without a new ADR)
| Path or idea | Why removed | Replacement |
|---|---|---|
| Bundled `viewer/vendor/transformers/transformers.min.js` | GitHub push protection flagged a constant inside it as an API key (false positive) | Loaded from jsDelivr at an exact version and SHA-384 checked in the browser ([ADR-0004](adr/0004-ai-runtime-from-cdn-with-hash-check.md)) |
| Camera-path-only result screen (`#hybrid-result`) | The flow now continues to a measured scene | `measureOnDevice` in `viewer/js/app.js` |
| `video/*` in the file input's `accept` list | A MIME wildcard must be expanded through the OS and was suspected of delaying the chooser (the intermittent CI failure was most likely a test race, fixed in the test; 8 of 8 later local runs passed, which is evidence, not proof) | Explicit extensions |
