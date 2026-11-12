// Hybrid mode, browser side: pick sharp frames from the video ON THIS DEVICE, then (after consent) send only those
// resized pictures to a camera-solve server and read back the camera poses. The video itself never leaves the device.
import { checkVideo, laplacianVariance, candidateTimes, pickSharpest, fitSide } from "./frames.js";
import { makeZip } from "./zip.js";

export const DEFAULT_SERVER = "http://127.0.0.1:8787";
const abortError = () => new DOMException("Cancelled", "AbortError");

/** The server address the user typed -> a clean origin string, or an Error with a plain message. */
export function parseServerUrl(text) {
  let u;
  try { u = new URL((text || DEFAULT_SERVER).trim()); } catch { throw new Error("The server address isn't valid. It should look like http://127.0.0.1:8787"); }
  if (u.protocol !== "http:" && u.protocol !== "https:") throw new Error("The server address must start with http:// or https://");
  if (u.username || u.password) throw new Error("Don't put a password in the server address.");
  return u.origin;
}

function loadVideo(file) {
  return new Promise((resolve, reject) => {
    const v = document.createElement("video");
    v.muted = true; v.playsInline = true; v.preload = "auto";
    v.onloadedmetadata = () => resolve(v);
    v.onerror = () => reject(new Error("This browser couldn't read that video. Try an .mp4 (H.264) file, or use Chrome."));
    v.src = URL.createObjectURL(file);
  });
}

const seek = (v, t) => new Promise((resolve, reject) => {
  v.onseeked = () => resolve();
  v.onerror = () => reject(new Error("The video stopped being readable partway through."));
  v.currentTime = t;
});

const toJpeg = (canvas) => new Promise((resolve, reject) =>
  canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Could not encode a picture."))), "image/jpeg", 0.92));

/**
 * Picks about `target` sharp frames (the sharpest of `per` candidates in each equal slice of the video), resized to
 * at most `maxSide` px. Drawing each frame onto a canvas and encoding it again drops all metadata (EXIF, GPS).
 * Returns { frames: [{ name, blob }], info }.
 */
export async function extractFrames(file, { target = 80, per = 3, maxSide = 1024, onProgress = () => {}, signal } = {}) {
  const v = await loadVideo(file);
  const url = v.src;
  try {
    const info = { duration: v.duration, width: v.videoWidth, height: v.videoHeight };
    const problem = checkVideo({ ...info, size: file.size });
    if (problem) throw new Error(problem);
    const [W, H] = fitSide(info.width, info.height, maxSide), [sw, sh] = fitSide(info.width, info.height, 320);
    const small = document.createElement("canvas"); small.width = sw; small.height = sh;
    const sctx = small.getContext("2d", { willReadFrequently: true });
    const big = document.createElement("canvas"); big.width = W; big.height = H;
    const bctx = big.getContext("2d");
    const frames = [];
    for (const [i, times] of candidateTimes(info.duration, target, per).entries()) {
      if (signal?.aborted) throw abortError();
      const bitmaps = [], scores = [];
      for (const t of times) {
        await seek(v, t);
        const bm = await createImageBitmap(v);
        sctx.drawImage(bm, 0, 0, sw, sh);
        scores.push(laplacianVariance(sctx.getImageData(0, 0, sw, sh).data, sw, sh));
        bitmaps.push(bm);
      }
      const best = pickSharpest([scores])[0];
      bctx.drawImage(bitmaps[best], 0, 0, W, H);
      bitmaps.forEach((b) => b.close());
      frames.push({ name: `frame_${String(i).padStart(4, "0")}.jpg`, blob: await toJpeg(big) });
      onProgress(i + 1, target);
    }
    return { frames, info };
  } finally { URL.revokeObjectURL(url); }
}

/** Zip the pictures and POST them. Resolves with the sfm payload; rejects with a plain-language Error. */
export async function solveOnServer(frames, serverOrigin, fov, { signal, onUpload = () => {}, onUploaded = () => {} } = {}) {
  const files = [];
  for (const f of frames) files.push({ name: f.name, bytes: new Uint8Array(await f.blob.arrayBuffer()) });
  const body = makeZip(files);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const q = fov ? `?fov=${encodeURIComponent(fov)}` : "";
    xhr.open("POST", `${serverOrigin}/v1/sfm${q}`);
    xhr.setRequestHeader("Content-Type", "application/zip");
    xhr.timeout = 20 * 60 * 1000;
    xhr.upload.onprogress = (e) => e.lengthComputable && onUpload(e.loaded / e.total);
    xhr.upload.onload = () => onUploaded();
    xhr.onabort = () => reject(abortError());
    xhr.ontimeout = () => reject(new Error("The server took too long. Try again later."));
    xhr.onerror = () => reject(new Error(`Could not reach the server at ${new URL(serverOrigin).host}. Is it running, and does it allow this site (--origin)?`));
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status === 200 && data && Array.isArray(data.frames) && data.camera) return resolve(data);
      reject(new Error((data && data.error) || `The server answered ${xhr.status}.`));
    };
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(body);
  });
}

/** Camera centres (x, y, z) from the payload: C = -R^T t. Skips malformed entries. */
export function cameraCentres(payload) {
  const out = [];
  for (const f of payload.frames || []) {
    const R = f.R, t = f.t;
    if (!Array.isArray(R) || R.length !== 9 || !Array.isArray(t) || t.length !== 3 || ![...R, ...t].every(Number.isFinite)) continue;
    out.push([-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])]);
  }
  return out;
}
