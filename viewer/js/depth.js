// AI depth in the browser: Depth Anything V2 Small (q4f16 ONNX) through the bundled transformers.js, on WebGPU when
// the browser has it, otherwise WASM (about 15 times slower). Also turns the frame pictures into what core/pipeline.js needs.
import { frameLuma } from "./core/color.js";

export const MODEL = { id: "onnx-community/depth-anything-v2-small", revision: "4472b7362082ad9968fee890ca0f1e5aca36b93d", dtype: "q4f16", sizeMB: 19 };
const ORT_VERSION = "1.31.0-dev.20260914-8d85527a0";
// Both files are loaded from jsDelivr at exact versions (transformers.js cannot be bundled: GitHub's secret scanner flags a constant inside it;
// the wasm is 27 MB). Their SHA-384 hashes are recorded in vendor/transformers/HASHES.json and checked against the npm packages by
// scripts/verify_vendor.py --official. At run time the page downloads each file, checks its hash and refuses to run it on a mismatch.
const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2/dist/transformers.min.js";
const ORT_WASM_URL = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VERSION}/dist/ort-wasm-simd-threaded.asyncify.wasm`;
const abortError = () => new DOMException("Cancelled", "AbortError");

/** "sha384-<base64>" of some bytes (Subresource Integrity format). */
export async function sriOf(bytes) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-384", bytes));
  let bin = ""; for (const b of d) bin += String.fromCharCode(b);
  return "sha384-" + btoa(bin);
}

/** Downloads a file and returns its bytes only if their SHA-384 equals `expected`. Never runs or returns unverified bytes. */
export async function fetchVerified(url, expected, fetchImpl = fetch) {
  if (!expected) throw new Error("No recorded hash for a file the AI runtime needs, so it was not loaded.");
  const r = await fetchImpl(url);
  if (!r.ok) throw new Error(`Could not download a file the AI runtime needs (${r.status ?? "network error"}).`);
  const buf = await r.arrayBuffer();
  if ((await sriOf(buf)) !== expected) throw new Error("A downloaded AI runtime file does not match its recorded hash, so it was not run (the CDN file may have changed).");
  return buf;
}

/** Which device depth will run on: "webgpu" only if there is an adapter that supports 16-bit float shaders (the q4f16 model needs
 *  them; a software adapter does not), otherwise "wasm". */
export async function pickDevice(nav = navigator) {
  try {
    const adapter = nav.gpu && (await nav.gpu.requestAdapter());
    if (adapter?.features?.has("shader-f16")) return "webgpu";
  } catch { /* no WebGPU */ }
  return "wasm";
}

/** Loads the model once. onStatus gets plain-language progress. Resolves with { device, disparity(blob, w, h) }. */
export async function loadDepth({ onStatus = () => {}, device } = {}) {
  onStatus("loading the AI library");
  const hashes = await (await fetch(new URL("../vendor/transformers/HASHES.json", import.meta.url))).json();
  onStatus("loading the AI library (checking its hash)");
  const lib = await fetchVerified(TRANSFORMERS_URL, hashes["transformers.min.js"]);
  const libUrl = URL.createObjectURL(new Blob([lib], { type: "text/javascript" }));
  let mod;
  try { mod = await import(libUrl); } finally { URL.revokeObjectURL(libUrl); }
  const { pipeline, env, RawImage } = mod;
  env.allowLocalModels = false;
  env.useBrowserCache = true;
  env.backends.onnx.wasm.numThreads = 1; // multi-threading needs cross-origin isolation, which a static host cannot give
  onStatus("loading the AI runtime (27 MB, checking its hash)");
  const wasm = await fetchVerified(ORT_WASM_URL, hashes["ort-wasm-simd-threaded.asyncify.wasm"]);
  env.backends.onnx.wasm.wasmPaths = {
    mjs: new URL("../vendor/transformers/ort-wasm-simd-threaded.asyncify.mjs", import.meta.url).href,
    wasm: URL.createObjectURL(new Blob([wasm], { type: "application/wasm" })),
  };
  let dev = device || (await pickDevice()), pipe = null, lastError = null;
  const seen = new Set();
  const progress = (p) => {
    if (p.status === "progress" && p.file?.endsWith(".onnx") && !seen.has("done")) onStatus(`downloading the depth model, ${Math.round(p.progress || 0)}% of ${MODEL.sizeMB} MB (once; your browser keeps it)`);
  };
  for (const d of dev === "webgpu" ? ["webgpu", "wasm"] : ["wasm"]) {
    try {
      onStatus(`preparing the depth model (${d === "webgpu" ? "your graphics chip" : "the processor, slower"})`);
      pipe = await pipeline("depth-estimation", MODEL.id, { device: d, dtype: MODEL.dtype, revision: MODEL.revision, progress_callback: progress });
      dev = d; lastError = null;
      break;
    } catch (e) { lastError = e; }
  }
  if (!pipe) throw new Error(`Could not load the depth model (${MODEL.sizeMB} MB from huggingface.co). Check your connection and try again. ${lastError?.message ?? ""}`.trim());
  return {
    device: dev,
    /** Relative inverse depth (bigger = closer) for a JPEG blob, resized to w x h as a Float32Array. */
    async disparity(blob, w, h) {
      const out = await pipe(await RawImage.fromBlob(blob));
      const t = out.predicted_depth, dims = t.dims, ih = dims[dims.length - 2], iw = dims[dims.length - 1];
      return resizeBilinear(t.data, iw, ih, w, h);
    },
  };
}

/** Bilinear resize of a row-major float image. */
export function resizeBilinear(src, sw, sh, dw, dh) {
  const out = new Float32Array(dw * dh), xr = sw / dw, yr = sh / dh;
  for (let y = 0; y < dh; y++) {
    const fy = Math.max(0, Math.min(sh - 1, (y + 0.5) * yr - 0.5)), y0 = Math.floor(fy), y1 = Math.min(sh - 1, y0 + 1), wy = fy - y0;
    for (let x = 0; x < dw; x++) {
      const fx = Math.max(0, Math.min(sw - 1, (x + 0.5) * xr - 0.5)), x0 = Math.floor(fx), x1 = Math.min(sw - 1, x0 + 1), wx = fx - x0;
      out[y * dw + x] = (src[y0 * sw + x0] * (1 - wx) + src[y0 * sw + x1] * wx) * (1 - wy) + (src[y1 * sw + x0] * (1 - wx) + src[y1 * sw + x1] * wx) * wy;
    }
  }
  return out;
}

/** A FrameSource for core/pipeline.js from the JPEG pictures that were sent (named frame_0000.jpg ...). */
export function makeSource(frames, payload, depth, { signal, onFrame = () => {} } = {}) {
  const byName = new Map(frames.map((f) => [f.name, f.blob])), { width: W, height: H } = payload.camera;
  const names = payload.frames.map((f) => f.name);
  const blobOf = (i) => { if (signal?.aborted) throw abortError(); const b = byName.get(names[i]); if (!b) throw new Error(`The server returned a frame (${names[i]}) that was not sent.`); return b; };
  const canvas = document.createElement("canvas"), ctx = canvas.getContext("2d", { willReadFrequently: true });
  const draw = async (blob, w, h) => {
    const bm = await createImageBitmap(blob);
    canvas.width = w; canvas.height = h;
    ctx.drawImage(bm, 0, 0, w, h);
    bm.close();
    return ctx.getImageData(0, 0, w, h).data; // RGBA
  };
  const toRgb = (rgba, n) => { const rgb = new Uint8Array(n * 3); for (let i = 0; i < n; i++) { rgb[3 * i] = rgba[4 * i]; rgb[3 * i + 1] = rgba[4 * i + 1]; rgb[3 * i + 2] = rgba[4 * i + 2]; } return rgb; };
  return {
    async luma(i) { const w = 256, h = Math.max(1, Math.round((H / W) * w)); return frameLuma(toRgb(await draw(blobOf(i), w, h), w * h), w * h); },
    async frame(i) {
      const blob = blobOf(i);
      const rgb = toRgb(await draw(blob, W, H), W * H);
      const disp = await depth.disparity(blob, W, H);
      if (signal?.aborted) throw abortError();
      onFrame(i + 1, names.length);
      return { rgb, disp };
    },
  };
}
