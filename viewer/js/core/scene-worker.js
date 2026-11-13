// Web worker: runs stages 4-6 (fusion, floor, scale, room, ranges) off the page's main thread.
// Message in:  { payload, collected, options }   Messages out: { type: "progress", stage } | { type: "done", result } | { type: "error", message }
import { finishScene } from "./pipeline.js";
const scope = self;
scope.onmessage = (e) => {
    try {
        const { payload, collected, options } = e.data;
        const r = finishScene(payload, collected, { ...options, onProgress: (stage) => scope.postMessage({ type: "progress", stage }) });
        scope.postMessage({ type: "done", result: r }, [r.points.buffer, r.colors.buffer, r.views.buffer]);
    }
    catch (err) {
        scope.postMessage({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
};
