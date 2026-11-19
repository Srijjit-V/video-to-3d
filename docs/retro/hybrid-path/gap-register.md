# Gap register: the hybrid path

Current phase: 6 (closure verified 2026-11-18). Perimeter and method: [baseline-audit.md](baseline-audit.md). Severity: P0 security exposure or data loss, P1 correctness, P2 practice and observability, P3 selection and cleanup. Effort: S under a session, M a few, L needs its own plan.

| ID | Axis | Gap | Evidence (before the fix) | Forward fix | Sev | Eff | Status |
|----|------|-----|---------------------------|-------------|-----|-----|--------|
| G-001 | practice | `Content-Length: -1` passed the size cap and `read(-1)` read until the client stopped: unbounded memory | `sfm_server.py` `_handle`: only `length > max_body` was checked | refuse `length <= 0` (411); test `test_a_missing_negative_or_nonsense_content_length_is_refused_at_once` failed first | P1 | S | done |
| G-002 | practice | A few KB of JPEG header could claim 60000 x 60000 px; `cv2.imdecode` allocated it before the size check | `read_frames` decoded, then checked `img.shape` | `jpeg_dims()` reads the header and refuses before decoding; non-JPEG refused; tests with a decode that fails if called | P1 | S | done |
| G-003 | practice | Client read an unbounded answer and error body; a non-JSON answer raised a raw `ValueError` | `sfm_client.py` `r.read()`, `e.read()` | cap answer at 5 MB and error body at 100 KB; plain message for non-JSON; 2 tests failed first | P2 | S | done |
| G-004 | practice | Unexpected server error returned 500 and logged nothing | `do_POST` `except Exception` | log the exception type only to stderr; test checks the type is logged and no detail leaks | P2 | S | done |
| G-005 | missing feature | No `Permissions-Policy` | `vercel.json` header list | camera, microphone, geolocation, payment, usb, interest-cohort off; `tests/test_hosting_headers.py` | P3 | S | done |
| G-006 | selection | Third-party Actions referenced by movable tags | `.github/workflows/*.yml` `uses: ...@v4` | pinned to commit SHAs (each verified to be a commit through the GitHub API); regression test | P3 | S | done |
| G-007 | missing feature | Server image never built; `pycolmap` has no Linux arm64 wheel so it cannot build on an Apple-silicon Docker | build failed: "No matching distribution found for pycolmap>=4" | `FROM --platform=linux/amd64`, `.dockerignore`; built (726 MB), runs as UID 10001, no torch, solved the synthetic room through it: 4.05 x 5.0 m, temp folder empty afterwards | P2 | M | done |
| G-008 | thinking | Mermaid diagrams never rendered | n/a | all 6 render with mermaid-cli 12.2.0 (GitHub's own renderer not checked) | P3 | S | done |
| G-009 | missing feature | Rate limit keyed on the socket address: behind a proxy every client looks the same | `sfm_server.py` `client = self.client_address[0]` | needs a deployment decision (trusted proxy header allow-list) | P2 | M | open (deferred until a host exists) |
| G-010 | missing feature | No bot protection (Turnstile), spend cap or job queue | [ADR-0007](../../adr/0007-hosting-vercel-static-modal-cpu.md) | needs accounts and a host | P2 | L | open (needs the owner) |
| G-011 | practice | Frame picking runs on the main thread with a `<video>` element, not a worker or WebCodecs | `viewer/js/hybrid.js` | move to a worker / Mediabunny | P3 | M | open |
| G-012 | practice | A hostile server could return 400 frames x 50,000 observations (20 M numbers) | `validatePayload` caps | bounded in practice by the 5 MB answer cap (G-003) | P3 | S | done (by G-003) |
| G-013 | thinking | The 90% range does not model the camera solver's run-to-run variation; in 1 of 6 browser runs the long side was 11% off | `docs/VERIFICATION.md` (six runs) | needs many real rooms to calibrate; documented | P1 | L | wont-fix for now: reason: no real-room data exists yet; stated in README and VERIFICATION |

## Closure (Phase 6)
Re-audit of the same perimeter after the fixes: 10 of 13 rows done, 2 open and waiting on a host or the owner (G-009, G-010), 1 open and small (G-011), 1 wont-fix with a recorded reason (G-013). Verified with `verification-loop`: ruff, mypy, the Python, Node and browser suites and CI (see [VERIFICATION.md](../../VERIFICATION.md)).
