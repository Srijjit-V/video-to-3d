// Page logic: which mode we are in, drag and drop, live progress, and the panel around the 3D view.

import { SceneView } from "./scene.js";
import { parsePly } from "./ply.js";
import { RAMP, availableModes } from "./colors.js";
import { detectMode, uploadVideo, getJob, cancelJob } from "./jobs.js";
import { demoSteps, markDone } from "./demo.js";
import { parseServerUrl, extractFrames, solveOnServer } from "./hybrid.js";
import { collectPoints, writePly } from "./core/pipeline.js";
import { loadDepth, makeSource } from "./depth.js";
import { floorPlanJson, floorPlanSvg } from "./export.js";
import { confidenceView, esc, fmtLen, fmtRange, mmss, textOn } from "./format.js";

const $ = (id) => document.getElementById(id);
const VIDEO = /\.(mp4|mov|m4v|webm|avi|mkv)$/i;
const MAX_VIDEO = 2 * 1024 ** 3;
const SCREENS = ["start", "consent", "progress", "scene"];

let mode = "hosted", view = null, meta = null, planUrl = null, calKey = "vid3d-cal", lastLegend = null, job = null, ticker = 0;

function show(name) {
  for (const s of SCREENS) $(s).hidden = s !== name;
  view?.setActive(name === "scene");
  scrollTo(0, 0);
}

function say(text) { $("hint").textContent = text; }
function fail(text) { const e = $("start-error"); e.textContent = text; e.hidden = !text; }

// ---------- start screen ----------

function setupMode() {
  document.documentElement.dataset.mode = mode;
  const file = $("file");
  file.multiple = true;
  if (mode === "local") {
    file.accept = "video/*,.mp4,.mov,.m4v,.webm,.avi,.mkv,.ply,.json,.png";
    $("drop-title").textContent = "Drop a video here";
    $("drop-sub").textContent = "or choose a file · 10 to 30 seconds of slow walking works best";
    $("mode-note").textContent = "Everything stays on this computer. Processing takes about three minutes.";
  } else {
    file.accept = "video/*,.mp4,.mov,.m4v,.webm,.ply,.json,.png";
    $("server-field").hidden = false;
    try { $("opt-server").value = localStorage.getItem("vid3d-server") || ""; } catch { /* storage blocked */ }
    $("drop-title").textContent = "Drop a video here";
    $("drop-sub").textContent = "or choose a file · or drop a cloud.ply and scene.json to view a scan";
    $("mode-note").textContent = "Frames are picked on your device. Nothing leaves it until you say so, and then only small pictures, never the video. "
      + "The depth and measuring also run on your device (the AI model, 19 MB, downloads once).";
  }
}

async function handleFiles(files) {
  fail("");
  const list = [...files];
  const video = list.find((f) => VIDEO.test(f.name) || f.type.startsWith("video/"));
  if (video) {
    if (video.size > MAX_VIDEO) return fail("That video is bigger than 2 GB. Trim it or lower its resolution.");
    return mode === "local" ? startJob(video) : startHybrid(video);
  }
  const ply = list.find((f) => /\.ply$/i.test(f.name));
  if (!ply) return fail(mode === "local" ? "Drop a video, or a cloud.ply file with its scene.json." : "Drop a cloud.ply file (with its scene.json) from a vid3d run.");
  try {
    const json = list.find((f) => /\.json$/i.test(f.name)), png = list.find((f) => /\.png$/i.test(f.name));
    const m = json ? JSON.parse(await json.text()) : fallbackMeta(ply.name);
    openScene(parsePly(await ply.arrayBuffer()), m, png ? URL.createObjectURL(png) : null);
  } catch (e) { fail(e instanceof SyntaxError ? "That scene.json isn't valid JSON." : e.message); }
}

function fallbackMeta(name) {
  return { video: name, points: 0, cameras: [], room: {}, palette: null, seconds: null, frames_registered: 0, frames_extracted: 0,
    warnings: ["No scene.json was dropped, so the room size, camera path and floor plan aren't available."] };
}

function wireStart() {
  const drop = $("drop"), file = $("file");
  const open = () => file.click();
  drop.addEventListener("click", open);
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  file.addEventListener("change", () => { if (file.files.length) handleFiles(file.files); file.value = ""; });
  for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("dragover"); });
  for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, () => drop.classList.remove("dragover"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); });
  // A file dropped beside the zone should not make the browser navigate away from the page.
  for (const ev of ["dragover", "drop"]) addEventListener(ev, (e) => e.preventDefault());
  $("sample-btn").addEventListener("click", () => loadUrls("sample"));
}

// ---------- processing (local mode) ----------

const STAGES = ["Pick sharp frames", "Solve the camera path", "AI depth on each frame", "Fuse into one cloud", "Find the floor and scale", "Floor plan and export"];

function buildStages(where = []) {
  $("stage-list").replaceChildren(...STAGES.map((label, i) => {
    const li = document.createElement("li");
    li.dataset.status = "pending";
    const tag = where[i] ? ` <span class="where">${esc(where[i])}</span>` : "";
    li.innerHTML = `<span class="dot" aria-hidden="true"></span><span class="stage-label">${i + 1}. ${esc(label)}${tag}<span class="sr-only"></span></span><span class="stage-detail"></span>`;
    return li;
  }));
}

const STATUS_TEXT = { pending: " (waiting)", running: " (in progress)", done: " (done)", error: " (failed)", cancelled: " (cancelled)" };

function renderJob(s) {
  const items = $("stage-list").children;
  let done = 0, running = null;
  s.stages.forEach((st, i) => {
    const li = items[i];
    li.dataset.status = st.status;
    li.querySelector(".dot").textContent = st.status === "done" ? "✓" : st.status === "error" || st.status === "cancelled" ? "!" : "";
    li.querySelector(".sr-only").textContent = STATUS_TEXT[st.status];
    li.querySelector(".stage-detail").textContent = st.detail;
    if (st.status === "done") done++;
    if (st.status === "running") running = st;
  });
  let frac = 0;
  const m = running && /(\d+) of (\d+)/.exec(running.detail);
  if (running) frac = m && running.n === 3 ? +m[1] / +m[2] : 0.4;
  const pct = Math.min(100, ((done + frac) / 6) * 100);
  $("bar-fill").style.width = `${pct}%`;
  $("stage-list").parentElement.querySelector("[role=progressbar]").setAttribute("aria-valuenow", String(done));
  const text = running ? `Stage ${running.n} of 6: ${running.label}` : s.state === "done" ? "Done" : "Starting…";
  if ($("prog-summary").textContent !== text) { $("prog-summary").textContent = text; $("prog-live").textContent = text; }
}

function tick(startedAt) {
  clearInterval(ticker);
  const paint = () => ($("elapsed").textContent = mmss((Date.now() - startedAt) / 1000));
  paint();
  ticker = setInterval(paint, 500);
}

async function startJob(file) {
  show("progress");
  buildStages();
  $("prog-error").hidden = true;
  $("again-btn").hidden = true;
  $("cancel-btn").hidden = false;
  $("cancel-btn").disabled = false;
  $("bar-fill").style.width = "0%";
  $("prog-summary").textContent = "Uploading…";
  tick(Date.now());
  try {
    const { id } = await uploadVideo(file, {
      camera_height: $("opt-camera").value, ceiling_height: $("opt-ceiling").value, fov: $("opt-fov").value,
    }, (f) => ($("prog-summary").textContent = `Uploading… ${Math.round(f * 100)}%`));
    job = id;
    await poll(id);
  } catch (e) { stopWithError("That didn't work", e.message, [], "Couldn't start"); }
}

// ---------- hybrid mode (hosted page): frames on this device, camera path on a server ----------

const HYBRID_WHERE = ["on your device", "on the server", "on your device", "on your device", "on your device", "on your device"];
let hy = null; // { abort, frames, thumbs }

function setStage(i, status, detail = "") {
  const li = $("stage-list").children[i];
  li.dataset.status = status;
  li.querySelector(".dot").textContent = status === "done" ? "✓" : status === "error" ? "!" : "";
  li.querySelector(".sr-only").textContent = STATUS_TEXT[status];
  li.querySelector(".stage-detail").textContent = detail;
}

function hybridSummary(text, fraction) {
  $("prog-summary").textContent = text;
  $("prog-live").textContent = text;
  if (fraction != null) $("bar-fill").style.width = `${Math.round(fraction * 100)}%`;
}

function dropHybrid() {
  hy?.thumbs?.forEach((u) => URL.revokeObjectURL(u));
  hy = null;
}

async function startHybrid(file) {
  let server;
  try {
    server = parseServerUrl($("opt-server").value);
    try { localStorage.setItem("vid3d-server", $("opt-server").value.trim()); } catch { /* storage blocked */ }
  } catch (e) { return fail(e.message); }
  dropHybrid();
  const abort = new AbortController();
  hy = { abort, frames: [], thumbs: [], fileName: file.name };
  show("progress");
  buildStages(HYBRID_WHERE);
  $("prog-error").hidden = true;
  $("again-btn").hidden = true;
  $("cancel-btn").hidden = false;
  $("cancel-btn").disabled = false;
  $("bar-fill").style.width = "0%";
  tick(Date.now());
  setStage(0, "running", "reading the video");
  hybridSummary("Stage 1: picking sharp frames on your device", 0.02);
  try {
    const { frames } = await extractFrames(file, {
      signal: abort.signal,
      onProgress: (n, total) => { setStage(0, "running", `frame ${n} of ${total}`); hybridSummary("Stage 1: picking sharp frames on your device", 0.25 * (n / total)); },
    });
    setStage(0, "done", `${frames.length} frames, on your device`);
    hy.frames = frames;
    clearInterval(ticker);
    showConsent(server);
    $("consent-send").onclick = () => sendFrames(server);
  } catch (e) { hybridFailed(e); }
}

function showConsent(server) {
  const bytes = hy.frames.reduce((s, f) => s + f.blob.size, 0);
  hy.thumbs = hy.frames.filter((_, i) => i % Math.ceil(hy.frames.length / 6) === 0).slice(0, 6).map((f) => URL.createObjectURL(f.blob));
  $("consent-count").textContent = $("consent-count2").textContent = String(hy.frames.length);
  $("consent-size").textContent = `${(bytes / 1e6).toFixed(1)} MB`;
  $("consent-host").textContent = new URL(server).host;
  $("consent-thumbs").replaceChildren(...hy.thumbs.map((u) => {
    const li = document.createElement("li"), img = document.createElement("img");
    img.src = u; img.alt = ""; img.width = 96; img.height = 64;
    li.append(img);
    return li;
  }));
  show("consent");
  $("consent-send").focus();
}

async function sendFrames(server) {
  if (!hy) return;
  const { abort, frames, fileName } = hy;
  show("progress");
  $("cancel-btn").hidden = false;
  $("cancel-btn").disabled = false;
  tick(Date.now());
  setStage(1, "running", "uploading");
  hybridSummary("Stage 2: sending pictures to the server", 0.3);
  try {
    const payload = await solveOnServer(frames, server, $("opt-fov").value, {
      signal: abort.signal,
      onUpload: (f) => { setStage(1, "running", `uploading ${Math.round(f * 100)}%`); hybridSummary("Stage 2: sending pictures to the server", 0.3 + 0.1 * f); },
      onUploaded: () => { setStage(1, "running", "solving on the server, about a minute"); hybridSummary("Stage 2: the server is solving the camera path", 0.45); },
    });
    const placed = payload.frames.length, total = Number.isFinite(payload.frames_total) ? payload.frames_total : frames.length;
    setStage(1, "done", `${placed} of ${total} frames placed`);
    await measureOnDevice(payload, frames, fileName, abort.signal);
  } catch (e) { hybridFailed(e); }
}

/** Stages 3-6 on this device: AI depth per frame (main thread, GPU if there is one), then fusion, floor, scale and the room in a worker. */
async function measureOnDevice(payload, frames, fileName, signal) {
  const started = Date.now();
  setStage(2, "running", "loading the depth model");
  hybridSummary("Stage 3: AI depth on your device", 0.5);
  const depth = await loadDepth({ onStatus: (t) => setStage(2, "running", t) });
  if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
  const n = payload.frames.length, where = depth.device === "webgpu" ? "graphics chip" : "processor (no WebGPU here, so slower)";
  const source = makeSource(frames, payload, depth, { signal, onFrame: (i) => {
    setStage(2, "running", `frame ${i} of ${n} · ${where}`);
    hybridSummary("Stage 3: AI depth on your device", 0.5 + 0.35 * (i / n));
  } });
  const collected = await collectPoints(payload, source, {});
  setStage(2, "done", `${n} frames, ${depth.device === "webgpu" ? "graphics chip" : "processor"}`);
  const opts = { cameraHeight: parseFloat($("opt-camera").value) || null, ceilingHeight: parseFloat($("opt-ceiling").value) || null,
    videoLabel: fileName.replace(/[\\/]/g, "_"), secondsSoFar: (Date.now() - started) / 1000 };
  const labels = { 4: "fusing the frames into one cloud", 5: "finding the floor and the real-world scale", 6: "measuring the room and its error range" };
  for (let k = 3; k < 6; k++) setStage(k, "pending", "");
  setStage(3, "running", labels[4]);
  hybridSummary("Stages 4 to 6: building the model on your device", 0.88);
  const result = await new Promise((resolve, reject) => {
    const w = new Worker(new URL("./core/scene-worker.js", import.meta.url), { type: "module" });
    signal.addEventListener("abort", () => { w.terminate(); reject(new DOMException("Cancelled", "AbortError")); }, { once: true });
    w.onmessage = (e) => {
      const m = e.data;
      if (m.type === "progress") {
        for (let k = 3; k < 6; k++) setStage(k, k + 1 < m.stage ? "done" : k + 1 === m.stage ? "running" : "pending", k + 1 === m.stage ? labels[m.stage] : "");
        hybridSummary(`Stage ${m.stage} of 6: ${labels[m.stage]}`, 0.85 + 0.05 * (m.stage - 3));
      } else if (m.type === "done") { w.terminate(); resolve(m.result); }
      else { w.terminate(); reject(new Error(m.message)); }
    };
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message || "The measuring step crashed.")); };
    w.postMessage({ payload, collected, options: opts }, [collected.points.buffer, collected.colors.buffer, collected.frames.buffer]);
  });
  for (let k = 3; k < 6; k++) setStage(k, "done", "");
  clearInterval(ticker);
  hybridSummary("Done", 1);
  dropHybrid();
  const ply = writePly(result.points, result.colors, result.views);
  openScene(parsePly(ply.buffer), result.scene, null);
}

function hybridFailed(e) {
  clearInterval(ticker);
  dropHybrid();
  if (e?.name === "AbortError") return show("start");
  const at = [...$("stage-list").children].findIndex((li) => li.dataset.status === "running");
  if (at >= 0) setStage(at, "error", "");
  stopWithError("That didn't work", e.message, [], at >= 0 ? `Stopped at stage ${at + 1} of 6: ${STAGES[at]}` : "Stopped");
}

async function poll(id) {
  for (;;) {
    const s = await getJob(id);
    if (job !== id) return;
    tick(Date.now() - s.elapsed * 1000);
    renderJob(s);
    if (s.state === "done") { clearInterval(ticker); return loadUrls(`jobs/${id}`); }
    if (s.state === "error") {
      const at = s.stages.find((x) => x.status === "error");
      return stopWithError("That didn't work", s.error, s.log, at ? `Stopped at stage ${at.n} of 6: ${at.label}` : "Stopped");
    }
    if (s.state === "cancelled") { clearInterval(ticker); return show("start"); }
    await new Promise((r) => setTimeout(r, 800));
  }
}

function stopWithError(title, message, log = [], summary = "Stopped") {
  clearInterval(ticker);
  $("prog-summary").textContent = summary;
  $("prog-error-title").textContent = title;
  $("prog-error-msg").textContent = message || "Something went wrong.";
  $("prog-log").textContent = log.join("\n");
  $("prog-error").hidden = false;
  $("cancel-btn").hidden = true;
  $("again-btn").hidden = false;
  $("again-btn").focus();
}

function wireProgress() {
  $("cancel-btn").addEventListener("click", async () => {
    $("cancel-btn").disabled = true;
    $("prog-summary").textContent = "Cancelling…";
    if (hy) hy.abort.abort();
    else if (job) await cancelJob(job).catch(() => {});
  });
  $("again-btn").addEventListener("click", () => { job = null; show("start"); });
  $("consent-cancel").addEventListener("click", () => { dropHybrid(); show("start"); });
}

// ---------- the scene ----------

async function loadUrls(base) {
  fail("");
  try {
    const [m, buf] = await Promise.all([
      fetch(`${base}/scene.json`).then((r) => { if (!r.ok) throw new Error("scene.json is missing."); return r.json(); }),
      fetch(`${base}/cloud.ply`).then((r) => { if (!r.ok) throw new Error("cloud.ply is missing."); return r.arrayBuffer(); }),
    ]);
    openScene(parsePly(buf), m, `${base}/floorplan.png`);
  } catch (e) { show("start"); fail(`Couldn't open that scene. ${e.message}`); }
}

function saveText(name, type, text) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function exportPlan(kind) {
  const k = view?.cal || 1;
  if (kind === "svg") { const s = floorPlanSvg(meta, k); if (s) saveText("floorplan.svg", "image/svg+xml", s); }
  else { const j = floorPlanJson(meta, k); if (j) saveText("floorplan.json", "application/json", JSON.stringify(j, null, 2)); }
}
$("plan-svg").addEventListener("click", () => exportPlan("svg"));
$("plan-json").addEventListener("click", () => exportPlan("json"));

function openScene(data, m, plan) {
  if (planUrl?.startsWith("blob:")) URL.revokeObjectURL(planUrl);
  meta = { ...m, points: m.points || data.count };
  planUrl = plan;
  calKey = `vid3d-cal:${meta.video}:${meta.points}`;
  show("scene");
  view.load(data, meta);
  let cal = 1;
  try { cal = parseFloat(localStorage.getItem(calKey)) || 1; } catch { /* storage blocked */ }
  view.setCal(cal);
  buildModeSelect(data);
  renderPanel();
  const plan$ = $("plan");
  plan$.onerror = () => ($("plan-wrap").hidden = true);
  plan$.onload = () => ($("plan-wrap").hidden = false);
  $("plan-wrap").hidden = !plan;
  $("plan-export").hidden = !floorPlanJson(meta);
  if (plan) plan$.src = plan;
  $("panel").hidden = innerWidth <= 720;
  $("tool-panel").setAttribute("aria-expanded", String(!$("panel").hidden));
  say("Drag to orbit · right-drag to pan · scroll to zoom");
  $("canvas-host").querySelector("canvas").focus({ preventScroll: true });
}

function renderPanel() {
  const r = meta.room || {}, cal = view.cal;
  renderConfidence();
  renderDemo();
  const ro = $("cal-readout");
  ro.hidden = cal === 1 || !r.length_m;
  if (!ro.hidden) ro.textContent = `Before: ${r.length_m.toFixed(2)} × ${r.width_m.toFixed(2)} m. After your calibration (×${cal.toFixed(3)}): ${(r.length_m * cal).toFixed(2)} × ${(r.width_m * cal).toFixed(2)} m.`;
  const atLeast = r.missing_wall ? "at least " : "";
  $("dims").textContent = r.length_m ? `${atLeast}${(r.length_m * cal).toFixed(2)} × ${(r.width_m * cal).toFixed(2)} m`
    : r.at_least_m ? `at least ${(r.at_least_m[0] * cal).toFixed(1)} × ${(r.at_least_m[1] * cal).toFixed(1)} m` : "Room not fully captured";
  const rows = [
    ["Height", r.height_m ? fmtLen(r.height_m, cal) : "ceiling not seen"],
    ["Area", r.area_m2 ? `${r.missing_wall ? "at least " : ""}${(r.area_m2 * cal * cal).toFixed(1)} m² · ${(r.area_ft2 * cal * cal).toFixed(0)} ft²` : "–"],
    ["Frames used", meta.frames_extracted ? `${meta.frames_registered} / ${meta.frames_extracted}` : "–"],
    ["Points", meta.points.toLocaleString()],
    ["Solve error", meta.sfm_reprojection_error_px != null ? `${meta.sfm_reprojection_error_px} px` : "–"],
  ];
  const rg = meta.uncertainty?.ranges;
  if (rg) {
    rows.splice(0, 0, ["Length range", fmtRange(rg.length_m, cal, "m", 2)], ["Width range", fmtRange(rg.width_m, cal, "m", 2)],
      ["Area range", fmtRange(rg.area_m2, cal * cal, "m²")]);
  }
  $("stats").innerHTML = rows.map(([a, b]) => `<tr><td>${esc(a)}</td><td>${esc(b)}</td></tr>`).join("");
  // The scale guess is covered by the calibration tool, so drop that warning once calibrated.
  const warns = (Array.isArray(meta.warnings) ? meta.warnings : []).map(String).filter((w) => cal === 1 || !w.startsWith("Real-world scale"));
  if (cal !== 1) warns.unshift(`Scale calibrated by you (×${cal.toFixed(3)}).`);
  $("warnings").replaceChildren(...warns.map((w) => { const d = document.createElement("p"); d.className = "warn"; d.textContent = w; return d; }));
  $("status").textContent = meta.seconds ? `Processed in ${Math.round(meta.seconds)} s` : "";
  renderPalette();
  renderLegend();
}

const demoDone = new Set();

function renderDemo() {
  const steps = demoSteps(meta), box = $("demo");
  box.hidden = !steps;
  if (!steps) return;
  const bad = meta.demo.kind === "bad";
  $("demo-note").textContent = bad
    ? "A deliberately bad capture: the walk never reached the far wall. See how the program reacts."
    : "Follow the steps. Each one says what you should see, and the true values are known.";
  $("demo-steps").replaceChildren(...steps.map((st) => {
    const li = document.createElement("li");
    li.dataset.step = st.id;
    li.className = demoDone.has(st.id) ? "done" : "";
    const a = document.createElement("span"), b = document.createElement("small");
    a.textContent = st.text; b.textContent = `Expect: ${st.expect}`;
    li.append(a, b);
    return li;
  }));
  const sw = $("demo-switch");
  sw.textContent = bad ? "Back to the good scan" : "Try the bad capture";
  sw.onclick = () => loadUrls(bad ? "sample" : "sample-bad");
  if (bad) { stepDone("warn"); stepDone("range"); }
}

function stepDone(id) {
  if (markDone(demoDone, id)) $("demo-steps")?.querySelector(`[data-step="${id}"]`)?.classList.add("done");
}

function renderConfidence() {
  const c = confidenceView(meta.confidence), box = $("confidence");
  box.hidden = !c;
  if (!c) return;
  box.dataset.level = c.label;
  box.replaceChildren(...[["strong", c.text], ["span", c.summary], ...c.reasons.map((x) => ["small", x])]
    .map(([tag, text]) => { const e = document.createElement(tag); e.textContent = text; return e; }));
}

function renderPalette() {
  const rows = [["Walls", "walls"], ["Floor", "floor"], ["Ceiling", "ceiling"]];
  $("palette").replaceChildren(...rows.map(([name, key]) => {
    const row = document.createElement("div");
    row.className = "pal-row";
    const label = document.createElement("span");
    label.className = "pal-name";
    label.textContent = name;
    const box = document.createElement("div");
    box.className = "pal-swatches";
    const colors = meta.palette?.[key] || [];
    if (!colors.length) {
      const none = document.createElement("span");
      none.className = "pal-empty";
      none.textContent = key === "ceiling" ? "not seen" : "not available";
      box.append(none);
    }
    for (const c of colors) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "swatch";
      b.style.backgroundColor = c.hex;
      b.style.color = textOn(c.hex);
      b.setAttribute("aria-label", `${name} colour ${c.hex}, ${Math.round(c.share * 100)} percent. Copy hex`);
      b.innerHTML = `${esc(c.hex)}<small>${Math.round(c.share * 100)}%</small>`;
      b.addEventListener("click", () => copyHex(c.hex));
      box.append(b);
    }
    row.append(label, box);
    return row;
  }));
}

async function copyHex(hex) {
  try { await navigator.clipboard.writeText(hex); say(`Copied ${hex}`); } catch { say(`${hex} (copy it by hand: your browser blocked the clipboard)`); }
}

function buildModeSelect(data) {
  const modes = availableModes(data, meta), sel = $("color-mode");
  sel.replaceChildren(...modes.map((m) => {
    const o = document.createElement("option");
    o.value = m.id;
    o.disabled = !m.ok;
    o.textContent = m.ok ? m.label : `${m.label} (not available)`;
    return o;
  }));
  sel.value = "true";
  const why = modes.filter((m) => !m.ok).map((m) => `${m.label}: ${m.why}`).join(" ");
  $("mode-why").textContent = why;
  $("mode-why").hidden = !why;
}

function renderLegend() {
  const l = lastLegend, box = $("legend");
  box.hidden = !l;
  if (!l) return;
  const f = (v) => (l.unit === "m" ? `${(v * view.cal).toFixed(1)} m` : `${Math.round(v)} frames`);
  $("legend-title").textContent = l.title;
  $("legend-lo").textContent = f(l.lo);
  $("legend-hi").textContent = f(l.hi);
  $("legend-bar").style.background = `linear-gradient(90deg, ${RAMP.join(", ")})`;
}

// ---------- panel controls ----------

function wireScene() {
  view = new SceneView($("canvas-host"), {
    hint: say,
    tool: (t) => { $("tool-measure").setAttribute("aria-pressed", String(t === "measure")); $("tool-pick").setAttribute("aria-pressed", String(t === "pick")); },
    top: (on) => $("tool-top").setAttribute("aria-pressed", String(on)),
    legend: (l) => { lastLegend = l; if (meta) renderLegend(); },
    measures: (list) => { if (list.length) stepDone("measure"); $("measures").replaceChildren(...list.map((t) => { const li = document.createElement("li"); li.textContent = t; return li; })) },
    picked: (p) => {
      $("pick-readout").hidden = false;
      $("pick-swatch").style.backgroundColor = p.hex;
      $("pick-rgb").textContent = `RGB ${p.rgb.join(", ")}`;
      $("pick-hex").textContent = p.hex;
      $("pick-extra").textContent = `Height ${(p.height * view.cal).toFixed(2)} m` + (p.views != null ? ` · seen in ${p.views} frames` : "");
      $("pick-copy").dataset.hex = p.hex;
      stepDone("pick");
      say(`Picked ${p.hex}`);
    },
  });
  $("tool-measure").addEventListener("click", () => view.setTool("measure"));
  $("tool-pick").addEventListener("click", () => view.setTool("pick"));
  $("tool-top").addEventListener("click", () => { view.toggleTop(); stepDone("top"); });
  $("tool-reset").addEventListener("click", () => view.resetView());
  $("tool-panel").addEventListener("click", () => {
    const p = $("panel");
    p.hidden = !p.hidden;
    $("tool-panel").setAttribute("aria-expanded", String(!p.hidden));
  });
  $("new-btn").addEventListener("click", () => show("start"));
  $("clear-btn").addEventListener("click", () => view.clearMeasures());
  $("color-mode").addEventListener("change", (e) => { view.setColorMode(e.target.value); if (e.target.value === "height") stepDone("height"); });
  $("pick-copy").addEventListener("click", (e) => copyHex(e.currentTarget.dataset.hex));
  $("pt-size").addEventListener("input", (e) => view.setPointSize(+e.target.value));
  $("show-cams").addEventListener("change", (e) => view.showCameras(e.target.checked));
  $("show-room").addEventListener("change", (e) => view.showRoom(e.target.checked));
  const setCal = (v) => { view.setCal(v); try { localStorage.setItem(calKey, String(v)); } catch { /* storage blocked */ } renderPanel(); };
  $("cal-btn").addEventListener("click", () => {
    const t = parseFloat($("true-len").value);
    if (!view.measuresList.length) return say("Measure something first (press M, then click two points).");
    if (!(t > 0)) return say("Type the true length in metres.");
    setCal(view.calibrateLast(t));
    stepDone("calibrate");
  });
  $("uncal-btn").addEventListener("click", () => setCal(1));
}

// ---------- start ----------

async function main() {
  wireStart();
  wireProgress();
  wireScene();
  mode = await detectMode();
  setupMode();
  if (mode === "view") await loadUrls("run");
  else if (new URLSearchParams(location.search).has("sample")) await loadUrls("sample");
  else show("start");
  // Debug and test hook: read-only handles to the live objects.
  Object.defineProperties((window.__vid3d = {}), {
    mode: { get: () => mode }, view: { get: () => view }, meta: { get: () => meta },
  });
}

main();
