// Talks to `vid3d serve` (local mode). Hosted mode never calls these.

/** "local" (vid3d serve), "view" (vid3d view) or "hosted" (a static site). api/health is a real file on static hosts. */
export async function detectMode() {
  try {
    const r = await fetch("api/health", { cache: "no-store" });
    if (r.ok) return (await r.json()).mode || "hosted";
  } catch { /* offline or opened as a file: treat as hosted */ }
  return "hosted";
}

export function uploadVideo(file, opts, onProgress) {
  return new Promise((resolve, reject) => {
    const q = new URLSearchParams({ name: file.name });
    for (const [k, v] of Object.entries(opts)) if (v !== "" && v != null) q.set(k, v);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `api/jobs?${q}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new Error("Could not reach the local server. Is `vid3d serve` still running?"));
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      xhr.status === 202 ? resolve(body) : reject(new Error(body.error || `The upload failed (${xhr.status}).`));
    };
    xhr.send(file);
  });
}

export async function getJob(id) {
  const r = await fetch(`api/jobs/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error("The local server lost track of this job.");
  return r.json();
}

export async function cancelJob(id) {
  await fetch(`api/jobs/${id}/cancel`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: "" });
}
