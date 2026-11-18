# Architecture Decision Records

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [0001](0001-sfm-payload-is-the-seam.md) | The camera-pose payload is the seam between solving and measuring | accepted | 2026-11-11 |
| [0002](0002-hybrid-camera-solve-default.md) | Hybrid mode (server solves the camera path) is the default; colmap-wasm stays experimental | accepted | 2026-11-11 |
| [0003](0003-typescript-port-with-golden-tests.md) | Measuring runs in the browser as a TypeScript port, checked against Python by golden vectors | accepted | 2026-11-12 |
| [0004](0004-ai-runtime-from-cdn-with-hash-check.md) | The AI runtime loads from a CDN and is hash-checked in the browser before it runs | accepted | 2026-11-12 |
| [0005](0005-front-end-stack.md) | Front-end stack: keep static ES modules and CSS tokens for now; React, Vite, TypeScript and Tailwind proposed | proposed | 2026-11-18 |
| [0006](0006-ecc-selective-project-scoped.md) | ECC is adopted selectively, scoped to this project, without hooks | accepted | 2026-11-18 |
| [0007](0007-hosting-vercel-static-modal-cpu.md) | Hosting: static site on Vercel (and Pages), camera solve on a CPU server (Modal first) | proposed | 2026-11-18 |

Backfilled records carry the date the decision was made. Format: [template.md](template.md).
