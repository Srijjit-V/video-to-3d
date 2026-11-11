# Real-phone accuracy benchmark (checklist)

The only measured accuracy so far is on a synthetic room (see [VERIFICATION.md](VERIFICATION.md)). This page is the protocol for measuring it on real
footage, so the claim "within 5 to 10%" can be tested instead of assumed. Fill in one row per room.

## What you need

- A phone (note the model and which lens: main, ultra-wide).
- A tape measure or laser measure, and a known-size object in the room (a standard interior door is about 2.03 m tall).
- 3 to 5 rooms of different kinds: a box-shaped room, a room with furniture, an L-shaped room, a dim room, a bare room.

## Measure the truth first (before filming)

| Measure | How | Write down |
|---|---|---|
| Length and width | wall to wall at hip height, twice, take the mean | metres, 2 decimals |
| Ceiling height | floor to ceiling in the middle | metres |
| Door height | the door you will use for calibration | metres |
| Camera height | how high you will hold the phone (mark it against a wall) | metres |

## Film

1. Walk slowly, 20 to 30 seconds, one loop, ending where you started. Keep the floor and the corners in view.
2. Hold the phone at the marked height for the whole walk. Landscape, no zoom, no stabilisation tricks if you can turn them off.
3. Do one extra take at a different height (chest) to see how scale error shows up.

## Run

```bash
.venv/bin/vid3d process room.mp4 --out runs/room                          # default scale, assumes 1.45 m
.venv/bin/vid3d process room.mp4 --camera-height 1.50 --out runs/room_h   # your real height
.venv/bin/vid3d process room.mp4 --ceiling-height 2.44 --out runs/room_c  # if the ceiling is seen
```

(Run one at a time and give each its own `--out`.)

## Record

| Room | Phone / lens | Truth L x W (m) | Scale source | Measured L x W | Error % (L, W, area) | Range (90%) contains truth? | Confidence label | Warnings shown |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

## How to read the result

- **Error:** `(measured - truth) / truth` for length, width and area. The area error should be about twice the length error when only the scale is wrong.
- **Coverage:** over all rooms, the 90% range should contain the truth about 9 times out of 10. With 5 rooms you cannot tell 90% from 70%; with 20 you can start to.
  If the truth falls outside far more often, the scale prior in `uncertainty.SCALE_SIGMA_REL` is too small.
- **Calibrated:** repeat with the door measured in the viewer and typed into Calibrate. Note the error before and after.
- **Confidence:** do "low" rooms really have larger errors than "high" ones? If not, the score weights in `uncertainty.confidence` need changing.

## Failure log

Write down every room where it failed (no floor found, walls missing, wrong size by more than 15%), with a still from the video. These are the cases that
teach the most and the first ones to turn into tests.
