// The 3D view: point cloud, camera path, room box, colour modes, colour picker, measuring, top-down.

import * as THREE from "../vendor/three/three.module.min.js";
import { OrbitControls } from "../vendor/three/addons/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "../vendor/three/addons/CSS2DRenderer.js";
import { colorize } from "./colors.js";
import { fmtLen, toHex } from "./format.js";

THREE.ColorManagement.enabled = false;  // show the video's sRGB values exactly as they are

const HINT = "Drag to orbit · right-drag to pan · scroll to zoom";

export class SceneView {
  /** hooks: hint(text), tool(name|null), top(bool), picked(info), measures(strings[]), legend(legend|null) */
  constructor(host, hooks = {}) {
    this.host = host;
    this.hooks = hooks;
    this.cal = 1;
    this.tool = null;
    this.top = false;
    this.active = false;
    this.measuresList = [];
    this.pending = null;
    this.marker = null;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const el = this.renderer.domElement;
    el.tabIndex = 0;
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", "3D view of the room. Keys: M measure, P pick colour, T top-down, R reset view, arrow keys pan, plus and minus zoom.");
    host.appendChild(el);

    this.labels = new CSS2DRenderer();
    Object.assign(this.labels.domElement.style, { position: "absolute", top: "0", left: "0", pointerEvents: "none" });
    host.appendChild(this.labels.domElement);
    const cross = document.createElement("div");
    cross.className = "cross";
    host.appendChild(cross);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0c0e12);
    this.camera = new THREE.PerspectiveCamera(60, 1, 0.01, 500);
    this.controls = new OrbitControls(this.camera, el);
    this.controls.enableDamping = true;
    this.controls.listenToKeyEvents(el);  // arrow keys pan
    this.raycaster = new THREE.Raycaster();
    this.home = { pos: new THREE.Vector3(), target: new THREE.Vector3() };

    new ResizeObserver(() => this._resize()).observe(host);
    el.addEventListener("pointerdown", (e) => { this._down = e.isPrimary ? { x: e.clientX, y: e.clientY, t: performance.now() } : null; });
    el.addEventListener("pointerup", (e) => {
      const d = this._down;
      this._down = null;
      if (!d || !this.tool || !this.cloud) return;
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6 || performance.now() - d.t > 700) return;  // a drag, not a tap
      const r = el.getBoundingClientRect();
      this._handlePick(this.pickPoint(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1));
    });
    window.addEventListener("keydown", (e) => this._key(e));
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      this.labels.render(this.scene, this.camera);
    });
  }

  _resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
  }

  // ---------- loading ----------

  clear() {
    this.clearMeasures();
    this._removeMarker();
    for (const o of [this.cloud, this.camLine, this.roomBox, this.grid]) {
      if (!o) continue;
      this.scene.remove(o);
      o.geometry?.dispose();
    }
    this.cloud = this.camLine = this.roomBox = this.grid = null;
    this.top = false;
    this.setTool(null);
  }

  load(data, meta) {
    this.clear();
    this.data = data;
    this.meta = meta;
    this.modeCache = {};
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(data.positions, 3));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(data.count * 3), 3));
    this.cloud = new THREE.Points(g, new THREE.PointsMaterial({ size: 2, vertexColors: true, sizeAttenuation: false }));
    this.scene.add(this.cloud);

    if (meta.cameras?.length > 1) {
      this.camLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(meta.cameras.map((c) => new THREE.Vector3(...c))),
        new THREE.LineBasicMaterial({ color: 0xfbbf24 }));
      this.scene.add(this.camLine);
    }
    const r = meta.room;
    if (r?.rect_m) {
      const [x0, z0, x1, z1] = r.rect_m;
      this.roomBox = new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3(x0, 0, z0), new THREE.Vector3(x1, r.height_m || 2.4, z1)), 0x2dd4bf);
      this.scene.add(this.roomBox);
    }
    this.grid = new THREE.GridHelper(40, 40, 0x3a4152, 0x20252f);
    this.scene.add(this.grid);

    g.computeBoundingSphere();
    const s = g.boundingSphere;
    this.home.target.copy(s.center);
    this.home.pos.copy(s.center).add(new THREE.Vector3(s.radius * 0.6, s.radius * 0.9, s.radius * 0.9));
    this.resetView();
    this.setColorMode("true");
    this._resize();
  }

  setActive(on) { this.active = on; if (on) this._resize(); }

  // ---------- colour ----------

  setColorMode(mode) {
    const c = (this.modeCache[mode] ??= colorize(mode, this.data, this.meta));
    const attr = this.cloud.geometry.attributes.color;
    attr.array.set(c.colors);
    attr.needsUpdate = true;
    this.mode = mode;
    this.hooks.legend?.(c.legend);
    return c.legend;
  }

  // ---------- picking ----------

  /** Nearest point to the camera under screen position (nx, ny in -1..1), or null. */
  pickPoint(nx, ny) {
    this.raycaster.setFromCamera({ x: nx, y: ny }, this.camera);
    // Pick radius grows with viewing distance so far-away walls are still clickable.
    this.raycaster.params.Points.threshold = this.camera.position.distanceTo(this.controls.target) * 0.012;
    const hits = this.raycaster.intersectObject(this.cloud);
    if (!hits.length) return null;
    hits.sort((a, b) => a.distanceToRay - b.distanceToRay || a.distance - b.distance);
    return hits.slice(0, 8).sort((a, b) => a.distance - b.distance)[0];
  }

  pickAtCenter() { this._handlePick(this.pickPoint(0, 0)); }

  /** Viewport pixel position of point `index` (used by tests and for the keyboard cross). */
  screenPositionOf(index) {
    const p = new THREE.Vector3(...this.data.positions.slice(3 * index, 3 * index + 3)).project(this.camera);
    const r = this.renderer.domElement.getBoundingClientRect();
    return { x: r.left + ((p.x + 1) / 2) * r.width, y: r.top + ((1 - p.y) / 2) * r.height };
  }

  _handlePick(hit) {
    if (!this.tool) return;
    if (!hit) return this.hooks.hint?.("No point there. Click or tap directly on the model.");
    return this.tool === "pick" ? this._pickColor(hit) : this._measurePoint(hit.point.clone());
  }

  _pickColor(hit) {
    const i = hit.index, c = this.data.colors, [r, g, b] = [c[3 * i], c[3 * i + 1], c[3 * i + 2]];
    this._removeMarker();
    this.marker = this._dot(hit.point, 0xffffff, 150);
    this.hooks.picked?.({ index: i, rgb: [r, g, b], hex: toHex(r, g, b), height: this.data.positions[3 * i + 1],
      views: this.data.views ? this.data.views[i] : null });
  }

  _removeMarker() { if (this.marker) { this.scene.remove(this.marker); this.marker = null; } }

  _dot(p, color, divisor) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 12), new THREE.MeshBasicMaterial({ color, depthTest: false }));
    m.position.copy(p);
    m.scale.setScalar(this.cloud.geometry.boundingSphere.radius / divisor);
    m.renderOrder = 3;
    this.scene.add(m);
    return m;
  }

  // ---------- tools ----------

  /** Switch a tool on or off ("measure" | "pick"); picking the active tool again turns it off. */
  setTool(name) {
    this.tool = this.tool === name ? null : name;
    if (this.pending) { this.scene.remove(this.pending.dot); this.pending = null; }
    this.host.classList.toggle("tool-active", !!this.tool);
    this.hooks.tool?.(this.tool);
    this.hooks.hint?.(this.tool === "measure" ? "Click a first point on the model"
      : this.tool === "pick" ? "Click a point to read its colour" : HINT);
  }

  _measurePoint(p) {
    if (!this.pending) {
      this.pending = { p, dot: this._dot(p, 0xfb7185, 120) };
      return this.hooks.hint?.("Click the second point");
    }
    const a = this.pending.p, dots = [this.pending.dot, this._dot(p, 0xfb7185, 120)];
    this.pending = null;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, p]), new THREE.LineBasicMaterial({ color: 0xfb7185, depthTest: false }));
    line.renderOrder = 2;
    const el = document.createElement("div");
    el.className = "label";
    const lbl = new CSS2DObject(el);
    lbl.position.copy(a).add(p).multiplyScalar(0.5);
    this.scene.add(line, lbl);
    this.measuresList.push({ raw: a.distanceTo(p), line, lbl, el, dots });
    this._refreshMeasures();
    this.hooks.hint?.("Click a first point to measure again");
  }

  _refreshMeasures() {
    this.measuresList.forEach((m) => (m.el.textContent = fmtLen(m.raw, this.cal)));
    this.hooks.measures?.(this.measuresList.map((m) => fmtLen(m.raw, this.cal)));
  }

  clearMeasures() {
    for (const m of this.measuresList) this.scene.remove(m.line, m.lbl, ...m.dots);
    this.measuresList = [];
    if (this.pending) { this.scene.remove(this.pending.dot); this.pending = null; }
    this._refreshMeasures();
  }

  /** Scale so the last measured line has the true length. Returns the new scale, or null if nothing was measured. */
  calibrateLast(trueLen) {
    const last = this.measuresList[this.measuresList.length - 1];
    if (!last) return null;
    this.setCal(trueLen / last.raw);
    return this.cal;
  }

  setCal(v) { this.cal = v; this._refreshMeasures(); }

  // ---------- view ----------

  resetView() {
    this.top = false;
    this.hooks.top?.(false);
    this.camera.position.copy(this.home.pos);
    this.controls.target.copy(this.home.target);
    this.controls.update();
  }

  toggleTop() {
    this.top = !this.top;
    if (this.top) {
      const s = this.cloud.geometry.boundingSphere;
      this.controls.target.set(s.center.x, 0, s.center.z);
      this.camera.position.set(s.center.x, s.radius * 2.2, s.center.z + 0.001);
      this.controls.update();
    } else this.resetView();
    this.hooks.top?.(this.top);
    return this.top;
  }

  setPointSize(v) { if (this.cloud) this.cloud.material.size = v; }
  showCameras(on) { if (this.camLine) this.camLine.visible = on; }
  showRoom(on) { if (this.roomBox) this.roomBox.visible = on; }

  _zoom(factor) {
    const v = this.camera.position.clone().sub(this.controls.target).multiplyScalar(factor);
    this.camera.position.copy(this.controls.target).add(v);
  }

  _key(e) {
    if (!this.active || !this.cloud || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest?.("input, select, textarea, [contenteditable]")) return;
    const k = e.key.toLowerCase();
    if (k === "m") this.setTool("measure");
    else if (k === "p") this.setTool("pick");
    else if (k === "t") this.toggleTop();
    else if (k === "r") this.resetView();
    else if (k === "escape") this.setTool(null);
    else if (k === "enter" && this.tool && e.target === this.renderer.domElement) this.pickAtCenter();
    else if (k === "+" || k === "=") this._zoom(0.9);
    else if (k === "-" || k === "_") this._zoom(1.1);
    else return;
    e.preventDefault();
  }
}
