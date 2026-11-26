# Gallery 12: kaleidoscope

**Idea.** A mandala of 12 mirrored sectors (6 turns x 2 mirrors), each holding the same 8 petals (spheres, boxes, cones,
cylinders) that glide, pulse and change colour together, so the pattern stays exactly symmetric. Click the hub to pause
and resume it.

**Graph.** One 12 s `Beat` clock → for each of 8 petal types a PositionInterpolator `Path` (its orbit), a
PositionInterpolator `Pulse` (its size) and a ColorInterpolator `Hue`; **each of those outputs is routed to the same petal
in all 12 sectors** (12 x 8 x 4 = 384 ROUTEs from 24 interpolators). A 60 s `Slow` clock → OrientationInterpolator → the
whole `Mandala`'s `rotation`. TouchSensor `HubTouch` → BooleanFilter → BooleanToggle → BooleanFilter `Running` →
`inputNegate` → `Beat.enabled` and `Slow.enabled`. 224 nodes, 415 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play. Click the gold hub to pause or resume. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-12-kaleidoscope`, Blender 5.3, two real clicks on the hub (the eye test's own click had paused it), 16 s | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Pause and run | the 8 petals' distance from the centre, sampled 10 times a second | 1 distinct pose while paused, 120 while running, 1 again after the second click |
| Exact symmetry | for each petal type, the spread of its distance from the centre across the 12 sectors, all samples | 0.0 m (it would be non-zero if any ROUTE had missed its petal) |
| Look | screenshot at 12 s, read by eye | a six-armed radial star with clusters of petals at the arm tips and small ones near the hub. It reads as symmetric, not as a rich kaleidoscope: the petals are small and bunch at the ends. |

Not checked: X_ITE judging (none); mirrored (negative-scale) sectors' normals in a rendered view.

## Findings for Loom

1. **Fan-out ROUTEs make symmetry free:** 24 interpolators drive 96 petals through 384 ROUTEs, in Play, with no spread.
2. **Negative scale (the mirror) is applied** by Play's `scale` path and the radii still agree.
3. 224 nodes and 415 ROUTEs loaded and played in one live run; I did not measure where the time goes.
