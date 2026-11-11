// Guided demo steps. Expected values come from scene.json "demo.truth" (the known size of the synthetic room),
// never from numbers typed into the page, so they stay true if the sample is regenerated.

import { fmtRange } from "./format.js";

const one = (v) => (Number.isFinite(v) ? v.toFixed(1) : "–");
const wallHexes = (m) => (m.palette?.walls || []).map((c) => c.hex).filter((h) => /^#[0-9a-f]{6}$/i.test(h)).join(", ");
const num = (v) => (Number.isFinite(v) ? v : null);

/** The checklist for a scene, or null when the scene is not a demo. */
export function demoSteps(meta) {
  const d = meta?.demo, t = d?.truth;
  if (!d || !t) return null;
  const door = t.door || {};
  const r = meta.room || {}, rg = meta.uncertainty?.ranges;
  if (d.kind === "bad") {
    return [
      { id: "warn", text: "Read the warning in the panel: it says a wall was never filmed.", expect: "Confidence is low and the room is not given as an exact size." },
      { id: "range", text: "Look at the ranges. Open-ended means \"at least\".",
        expect: `Width: ${rg ? fmtRange(rg.width_m, 1, "m", 2) : "–"} (the true width is ${num(t.width_m) ?? "–"} m, so the measured part is honest about being incomplete).` },
      { id: "top", text: "Press T for the top-down view and see where the room stops.", expect: "The far wall is missing: the floor plan ends abruptly." },
    ];
  }
  return [
    { id: "size", text: "Check the size in the panel.",
      expect: `The room is really ${one(t.length_m)} × ${one(t.width_m)} m. Shown: ${one(r.length_m)} × ${one(r.width_m)} m (the two sides can come out either way round), range ${rg ? fmtRange(rg.area_m2, 1, "m²") : "–"} (true area ${num(t.area_m2)} m²).` },
    { id: "measure", text: "Press M, then click the bottom and the top of the brown door.", expect: `About ${door.height_m} m tall (the true door height).` },
    { id: "calibrate", text: `Type ${door.height_m} under Calibrate and press Apply.`, expect: "The size readout shows before and after; the numbers move only a little because this scan was already scaled." },
    { id: "top", text: "Press T for the top-down view.", expect: "A rectangle with the camera path inside it." },
    { id: "pick", text: "Press P and click the wall.", expect: `A colour near one of the wall colours in the palette: ${wallHexes(meta) || "–"}. (The four walls of this room are tinted differently.)` },
    { id: "height", text: "Set Colour by to Height above floor.", expect: "Floor blue, ceiling and top of the walls warm." },
  ];
}

/** Marks a step done once; returns true when this call changed it. */
export function markDone(state, id) {
  if (state.has(id)) return false;
  state.add(id);
  return true;
}
