colmap-wasm 0.1.0 (BSD-3-Clause), an unofficial WebAssembly build of COLMAP 4.2.1: https://github.com/obraia/colmap-wasm (npm: colmap-wasm).
Bundled unmodified from the npm package (compare with scripts/verify_vendor.py --official). The files must keep this layout:
its worker is found at dist/worker.js and the wasm at wasm/colmap.wasm, relative to dist/index.js.
It is used only by the experimental "In this browser" camera-solve mode (viewer/js/colmap.js). See THIRD_PARTY_NOTICES.md for what the wasm contains.
