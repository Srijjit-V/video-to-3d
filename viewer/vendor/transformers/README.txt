Bundled here (compare with scripts/verify_vendor.py --official):

  ort-wasm-simd-threaded.asyncify.mjs     onnxruntime-web 1.31.0-dev.20260914-8d85527a0, dist/ (the loader this build of transformers.js needs)

NOT bundled, loaded from https://cdn.jsdelivr.net at exact versions (the page downloads each file and checks its SHA-384 against HASHES.json before running it; see fetchVerified in viewer/js/depth.js):

  transformers.min.js                     @huggingface/transformers 4.3.2 (Apache-2.0). It cannot be committed: GitHub's secret scanner flags a
                                          32-character constant inside it as a "Mistral AI API key" (a false positive: the file is byte for byte the
                                          npm package). Its SHA-384 is recorded in HASHES.json.
  ort-wasm-simd-threaded.asyncify.wasm    onnxruntime-web, 27 MB, too large for the repository. SHA-384 recorded in HASHES.json.

CI runs scripts/verify_vendor.py --official, which downloads the npm packages and fails if either recorded hash no longer matches, so a changed
published file would be noticed in CI, not in the browser.
The depth model (onnx-community/depth-anything-v2-small, q4f16) comes from huggingface.co at a pinned revision.
