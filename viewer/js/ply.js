// Reads the binary PLY files vid3d writes: x y z (float), red green blue (uchar), optional views (uchar).

const SIZES = { char: 1, uchar: 1, int8: 1, uint8: 1, short: 2, ushort: 2, int16: 2, uint16: 2, int: 4, uint: 4,
  int32: 4, uint32: 4, float: 4, float32: 4, double: 8, float64: 8 };

export function parsePly(buffer) {
  const bytes = new Uint8Array(buffer);
  const headEnd = indexOf(bytes, "end_header\n");
  if (headEnd < 0 || String.fromCharCode(...bytes.slice(0, 3)) !== "ply") {
    throw new Error("That doesn't look like a .ply file.");
  }
  const lines = new TextDecoder().decode(bytes.slice(0, headEnd)).split("\n");
  if (!lines.includes("format binary_little_endian 1.0")) {
    throw new Error("Only binary .ply files written by video-to-3d can be opened here.");
  }
  let count = 0, inVertex = false, stride = 0;
  const props = {};
  for (const line of lines) {
    const w = line.trim().split(/\s+/);
    if (w[0] === "element") { inVertex = w[1] === "vertex"; if (inVertex) count = parseInt(w[2], 10); }
    else if (w[0] === "property" && inVertex) {
      if (!(w[1] in SIZES)) throw new Error(`Unsupported .ply property type "${w[1]}".`);
      props[w[2]] = { type: w[1], offset: stride };
      stride += SIZES[w[1]];
    }
  }
  for (const need of ["x", "y", "z"]) if (!props[need]) throw new Error("This .ply has no x, y, z positions.");
  const body = headEnd + "end_header\n".length;
  if (!(count > 0) || bytes.length < body + count * stride) throw new Error("This .ply file looks cut off.");
  const view = new DataView(buffer, body, count * stride);
  const read = (p, i) => {
    const o = i * stride + p.offset;
    return p.type.startsWith("float") && SIZES[p.type] === 4 ? view.getFloat32(o, true)
      : SIZES[p.type] === 8 ? view.getFloat64(o, true) : view.getUint8(o);
  };
  const positions = new Float32Array(count * 3), colors = new Uint8Array(count * 3);
  const hasColor = props.red && props.green && props.blue;
  const views = props.views ? new Uint8Array(count) : null;
  for (let i = 0; i < count; i++) {
    positions[3 * i] = read(props.x, i);
    positions[3 * i + 1] = read(props.y, i);
    positions[3 * i + 2] = read(props.z, i);
    if (hasColor) { colors[3 * i] = read(props.red, i); colors[3 * i + 1] = read(props.green, i); colors[3 * i + 2] = read(props.blue, i); }
    else colors.fill(200, 3 * i, 3 * i + 3);
    if (views) views[i] = read(props.views, i);
  }
  return { count, positions, colors, views };
}

function indexOf(bytes, text) {
  const t = [...text].map((c) => c.charCodeAt(0));
  const limit = Math.min(bytes.length - t.length, 4096);
  outer: for (let i = 0; i <= limit; i++) {
    for (let j = 0; j < t.length; j++) if (bytes[i + j] !== t[j]) continue outer;
    return i;
  }
  return -1;
}
