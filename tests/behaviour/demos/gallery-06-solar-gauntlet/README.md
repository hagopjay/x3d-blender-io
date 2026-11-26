# Gallery 06: solar gauntlet

**Idea.** A 24 s looping camera flight, weaving through ten steel gates toward a flaring sun. As the camera passes a
gate it lights up and its frame swells; when you leave it goes dark. Six prominences swing round the sun.

**Graph.** TimeSensor `Flight` → PositionInterpolator and OrientationInterpolator (61 keys each, a look-ahead along a
sine weave) → the Viewpoint `Pilot`'s `position` and `orientation`. Per gate: ProximitySensor `NearN` (4.4 m cube at the
gate centre) `isActive` → the glow plate's `visible`, `enterTime` → a 0.6 s TimeSensor `PopN` → PositionInterpolator →
the frame's `scale` (1 → 1.35 → 1). Six looping TimeSensors → OrientationInterpolators swing the prominences. 72 nodes,
56 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play and watch from the scene camera (Numpad 0, or the camera
view in the viewport). No clicks. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-06-solar-gauntlet`, Blender 5.3, 26 s of watching, glow state sampled 10 times a second | Host-eyes **pass**; `act_ok` true: all 10 glows lit then went dark, in order, one gate after the next (6..9, 0..9, 0..2 as the loop wrapped), the camera travelled 51 m; `not_applied` empty |
| Look | screenshot at 10 s, read by eye | flying through a square steel gate with the next gates receding toward a golden sun and its cones |

Not checked: X_ITE judging (none); the glow plates are transparent boxes and the solid viewport shows them opaque.

## Findings for Loom

1. **ProximitySensor works from a Viewpoint-interpolator flight** with no viewport help; ten sensors, one pass.
2. The eye test's standard proximity step watches for 9 s before the act starts, so an act that records "first lit"
   sees the flight mid-loop; the act checks rising edges are cyclic instead.
3. Gate frames pop through `enterTime` → clock → scale; scale of a Transform with a rotated parent is applied in the
   gate's own frame (the gates are rotated to face the path), which looks right.
