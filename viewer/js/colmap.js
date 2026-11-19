// The experimental "in this browser" camera solve: colmap-wasm (bundled in vendor/colmap-wasm) does what the server's pycolmap does,
// and its answer is converted to the same sfm payload, so everything after this point is identical to the server path.

const MAX_OBS = 50000;
const abortError = () => new DOMException("Cancelled", "AbortError");

/** colmap-wasm's reconstruction + features -> sfm payload (src/vid3d/sfm_payload.py). Throws a plain message if too few frames were placed. */
export function reconstructionToPayload(rec, features, framesTotal) {
  const cam = rec.camera, placed = rec.images.filter((im) => im.registered && im.R && im.t).length;
  if (placed < 0.5 * framesTotal) {
    throw new Error(`COLMAP only placed ${placed} of ${framesTotal} frames, too few for a reliable model. Try a slower, steadier video, turning gradually, with the floor and room corners in view.`);
  }
  const frames = rec.images.map((im) => ({ name: im.name, registered: !!(im.registered && im.R && im.t), R: im.R && Array.from(im.R), t: im.t && Array.from(im.t), obs: [] }));
  for (const p of rec.points) {
    const [X, Y, Z] = p.xyz;
    for (const [ii, ki] of p.track) {
      const f = frames[ii];
      if (!f || !f.registered) continue;
      const z = f.R[6] * X + f.R[7] * Y + f.R[8] * Z + f.t[2]; // depth along the optical axis
      const kp = features[ii].keypoints;
      const u = kp[ki * 6], v = kp[ki * 6 + 1];
      if (z > 0 && Number.isFinite(z) && Number.isFinite(u) && Number.isFinite(v) && f.obs.length < MAX_OBS) f.obs.push([u, v, z]);
    }
  }
  return {
    version: 1,
    camera: { width: cam.width, height: cam.height, focal: cam.focal, cx: cam.cx, cy: cam.cy, k1: 0 }, // SIMPLE_PINHOLE: no lens distortion
    frames_total: framesTotal,
    reprojection_error_px: 0, // colmap-wasm does not report it
    frames: frames.filter((f) => f.registered).map((f) => ({ name: f.name, R: f.R, t: f.t, obs: f.obs })),
  };
}

/**
 * Solve the camera path in this browser. `frames` are the { name, blob } pictures already picked on the device; nothing is sent anywhere.
 * Uses sequential pairing (window 8, with loop closure): with COLMAP's default all-pairs matching the solve failed on the test room
 * (docs/VERIFICATION.md, Phase 0).
 */
export async function solveInBrowser(frames, { onProgress = () => {}, signal } = {}) {
  const lib = await import("../vendor/colmap-wasm/dist/index.js");
  const files = frames.map((f) => new File([f.blob], f.name, { type: "image/jpeg" }));
  if (signal?.aborted) throw abortError();
  const { reconstruction, features } = await lib.estimatePoses(files, {
    pairs: lib.sequentialPairs(files.length, { window: 8, loop: true }),
    onProgress: ({ stage, done, total }) => onProgress(stage, done, total),
    signal,
  });
  return reconstructionToPayload(reconstruction, features, files.length);
}
