three.js r160 (MIT, see LICENSE), from the official npm package three@0.160.0.
vendor/three/three.module.min.js is build/three.module.min.js unchanged.
addons/ are examples/jsm/controls/OrbitControls.js and renderers/CSS2DRenderer.js with one change each:
`from "three"` -> `from "../three.module.min.js"`, so no import map (inline script) is needed.
