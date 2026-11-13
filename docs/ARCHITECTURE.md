# Architecture

video-to-3d is a pipeline of six stages that turns a phone video into a measurable point cloud, plus a static web viewer.
The pipeline runs on one person's computer. The viewer can run anywhere, because it only reads files.

## 1. System

```mermaid
flowchart LR
    subgraph Local["Your computer"]
        V[/"video .mp4 / .mov"/] --> CLI["vid3d process<br/>(pipeline.py)"]
        V --> SRV["vid3d serve<br/>(server.py, 127.0.0.1 only)"]
        SRV -- "starts as a subprocess" --> CLI
        CLI --> S1["1 frames.py<br/>OpenCV"]
        S1 --> S2["2 sfm.py<br/>COLMAP, own process"]
        S2 --> S3["3 depth.py<br/>Depth Anything V2"]
        S3 --> S4["4 geometry.py<br/>fuse"]
        S4 --> S5["5 geometry.py<br/>floor + scale"]
        S5 --> S6["6 floorplan.py + uncertainty.py"]
        S6 --> OUT[("cloud.ply<br/>scene.json<br/>floorplan.png")]
    end
    OUT --> VIEW["Viewer (viewer/)<br/>static HTML + JS + three.js"]
    SRV -- "serves the viewer and the result files" --> VIEW
    HOST["Static host<br/>(GitHub Pages / Vercel)"] -- "same viewer, no server code" --> VIEW
    VIEW -. "drop cloud.ply + scene.json<br/>(stays in the browser)" .-> OUT
```

Why COLMAP runs in its own process: it and PyTorch each load their own OpenMP runtime, and in one process they abort.
A subprocess also gives the camera-solve a clean exit code (3 with an `error:` line when the message is meant for people).

## 2. Data flow and file formats

```mermaid
flowchart TD
    A[/"video"/] -->|"extract_frames: sharpest frame per window<br/>(limits: 300 s, 4K, 20,000 frames)"| B["frames/frame_0000.jpg ...<br/>(~80, deleted at the end)"]
    B -->|"pycolmap"| C["work/sfm.npz<br/>names, K, R, t, k1, 2-D to 3-D observations<br/>work/sfm_stats.json<br/>(deleted at the end)"]
    B --> D["Depth Anything V2<br/>relative depth per frame"]
    C --> E["align_disparity<br/>1/z = a d + b per frame"]
    D --> E
    E -->|"metric_depth + flying-pixel filter<br/>backproject"| F["points + colours per frame"]
    F -->|"fuse: voxels seen by 2+ frames"| G["raw cloud<br/>(arbitrary units)"]
    G -->|"find_floor, scale s = h / h_raw<br/>yaw_align"| H["metric cloud<br/>floor at y = 0, walls on x/z"]
    H --> I["floorplan.analyze<br/>uncertainty.estimate"]
    H --> J[("cloud.ply<br/>binary PLY: x y z, red green blue,<br/>views = frames that saw the point")]
    I --> K[("scene.json<br/>room, uncertainty.ranges, confidence,<br/>camera_height, palette, warnings, cameras")]
    I --> L[("floorplan.png")]
```

| File | Format | Holds |
|---|---|---|
| `cloud.ply` | binary little-endian PLY | `x y z` as float32 metres, `red green blue` as uint8, optional `views` as uint8 |
| `scene.json` | JSON | the video **file name** (never a path), scale method, frame counts, `room` (size, `wall_support`, `missing_wall`), `uncertainty` (90% ranges), `confidence`, `camera_height`, `palette`, camera positions, `warnings`. Demo scenes add `demo` with the known truth. |
| `floorplan.png` | PNG | top-down view with the room box and camera path |
| `work/sfm.npz` | NumPy archive | camera poses and intrinsics, per-frame 3-D to 2-D matches. Deleted after the run. |

## 3. Upload to result (local mode)

The progress the viewer shows is parsed from the lines the pipeline really prints, so it cannot get ahead of the work.

```mermaid
sequenceDiagram
    actor U as You
    participant B as Browser (viewer)
    participant S as vid3d serve (127.0.0.1)
    participant P as Pipeline subprocess
    U->>B: drop video
    B->>S: POST /api/jobs (octet-stream)
    S->>S: check Host, Origin, size, extension, one job at a time
    S->>P: start (fixed argument list, no shell)
    S-->>B: 202 {id}
    loop every second
        B->>S: GET /api/jobs/{id}
        S-->>B: stages 1-6, details ("frame 12 of 58")
    end
    P-->>S: log lines "[1/6]", "60 frames kept", "12/58", "96,191 points"
    P->>P: write cloud.ply, scene.json, floorplan.png
    P->>P: delete frames/, work/
    S->>S: delete the uploaded video
    S-->>B: state done, files
    B->>S: GET /jobs/{id}/cloud.ply, scene.json, floorplan.png
    B->>U: 3D scene, ranges, confidence
    opt cancel
        U->>B: Cancel
        B->>S: POST /api/jobs/{id}/cancel
        S->>P: SIGTERM to the process group
        S->>S: delete private files
    end
```

## 4. Trust boundaries

```mermaid
flowchart LR
    subgraph Untrusted["Untrusted"]
        W["Other web pages in your browser"]
        VID["The video file"]
        DROP["Files dropped into the hosted viewer"]
        NET["Model download (network)"]
    end
    subgraph Boundary["Checks at the boundary"]
        C1["Host allow-list<br/>Origin check<br/>octet-stream only<br/>size cap, extension allow-list"]
        C2["Length / resolution / frame limits<br/>before and during decode"]
        C3["PLY and JSON readers validate sizes;<br/>text goes in with textContent / escaping"]
        C4["Pinned commit + safetensors"]
    end
    subgraph Trusted["Your computer"]
        SRV["vid3d serve"]
        DEC["OpenCV / COLMAP"]
        VIEW["Viewer in the browser"]
        MODEL["Depth model"]
    end
    W --> C1 --> SRV
    VID --> C2 --> DEC
    DROP --> C3 --> VIEW
    NET --> C4 --> MODEL
```

Details and the threat model are in [SECURITY.md](SECURITY.md).

## Hybrid mode: the seam

```mermaid
sequenceDiagram
    participant C as Your computer (CLI today, browser later)
    participant S as sfm server (pycolmap only)
    C->>C: pick ~80 sharp frames, resize to 1024 px
    C->>S: POST /v1/sfm (zip of JPEGs, never the video)
    S->>S: validate, strip EXIF by re-encoding, solve camera path, delete frames
    S-->>C: sfm payload (cameras K, k1, per-frame R, t and sparse u, v, z), under 1 MB
    C->>C: depth, fit, fusion, floor and scale, ranges, floor plan
```

In the browser the same seam is used: the page does stages 1, 3, 4, 5 and 6 on the device (frame picking on the main thread, AI depth on WebGPU or WASM, fusion to ranges in a worker) and only stage 2 (COLMAP) on the server. `ts/src` is a port of `src/vid3d` checked against it by golden vectors.

The payload format is documented in `src/vid3d/sfm_payload.py` and validated on both sides. Local mode (`vid3d process`) writes the same data to `work/sfm.npz`; any solver that produces the payload (the server, colmap-wasm) plugs in at the same point.

## Modules

| Module | Job |
|---|---|
| `frames.py` | sharpest frame per window, with duration, resolution and frame-count limits |
| `sfm.py` | COLMAP camera path in a separate process |
| `depth.py` | Depth Anything V2 and the robust fit to COLMAP's depths |
| `geometry.py` | back-projection, voxel fusion, RANSAC, floor and ceiling finding |
| `floorplan.py` | wall alignment, room extent, wall support, floor-plan image, palette |
| `uncertainty.py` | Monte Carlo ranges, confidence, camera-height consistency |
| `color.py` | exposure normalisation, dominant colours |
| `sfm_payload.py`, `sfm_server.py`, `sfm_client.py` | the camera-solve seam, the Hybrid server and its client |
| `privacy.py` | deleting the frames and work files |
| `pipeline.py` | runs the stages, writes the outputs, quality warnings |
| `server.py`, `cli.py` | local servers and the command line |

The maths of stages 3 to 6 is in [MATH.md](MATH.md).
