// What this browser can really do, and which camera-solve and depth paths follow from it. Pure functions (the browser objects are passed in)
// so they can be tested. The default stays "hybrid" (the server solves the camera path); running COLMAP in the browser is experimental.

/** { webgpu, shaderF16, webcodecs, workers, wasm, memoryGB, cores } from real browser objects. */
export async function detectCapabilities(nav = globalThis.navigator, win = globalThis) {
  let adapter = null;
  try { adapter = nav?.gpu ? await nav.gpu.requestAdapter() : null; } catch { /* no usable WebGPU */ }
  return {
    webgpu: !!adapter,
    shaderF16: !!adapter?.features?.has?.("shader-f16"),
    webcodecs: typeof win?.VideoDecoder === "function",
    workers: typeof win?.Worker === "function",
    wasm: typeof win?.WebAssembly === "object",
    memoryGB: Number.isFinite(nav?.deviceMemory) ? nav.deviceMemory : null, // Safari and Firefox do not report it
    cores: Number.isFinite(nav?.hardwareConcurrency) ? nav.hardwareConcurrency : null,
  };
}

/** Which depth device runs and which camera-solve modes are offered, each with a plain reason when it is not. */
export function describeModes(c) {
  const why = [];
  if (!c.webgpu) why.push("this browser has no WebGPU (needed for the on-device matching step)");
  if (!c.workers || !c.wasm) why.push("this browser cannot run WebAssembly in workers");
  if (c.memoryGB !== null && c.memoryGB < 4) why.push(`this device reports only ${c.memoryGB} GB of memory (4 GB or more is needed)`);
  const browser = why.length
    ? { available: false, reason: why.join("; ").replace(/^./, (x) => x.toUpperCase()) + "." }
    : { available: true, reason: "" };
  return {
    default: "hybrid",
    depthDevice: c.webgpu && c.shaderF16 ? "webgpu" : "wasm", // the q4f16 model needs 16-bit float shaders
    modes: {
      hybrid: { available: true, reason: "" }, // the server path needs nothing special from the browser
      browser,
    },
  };
}
