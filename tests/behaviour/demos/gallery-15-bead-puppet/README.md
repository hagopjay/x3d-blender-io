# Gallery 15: bead puppet

**Idea.** A string puppet with no body: six beads (head, torso, two hands, two feet) hang from a crossbar on strings. Drag the
bar sideways and the beads do not come with it, they trail behind in order of how heavy they are (head first, right foot last),
stretching the figure out; let go and they swing back under the bar and the puppet re-assembles. A stage glow lights while you
hold the bar. It is a toy for feeling what a follower's `duration` is.

**The graph, in one paragraph.** One `PlaneSensor` (`Drag`, `autoOffset`, x only: `minPosition -4 0`, `maxPosition 4 0`) sits beside
the bar's shapes inside the Transform `Pull`; its `translation_changed` moves `Pull` (the bar) and also goes to six
`PositionChaser`s (`duration` 0.25, 0.45, 0.8, 1.0, 1.2, 1.5 s), each of which drives one bead Transform (`Head`, `Torso`,
`HandL`, `HandR`, `FootL`, `FootR`). A bead Transform also carries a thin string cylinder up to the bar's height, so the string
slants as the bead lags. Two hands rock on looping `OrientationInterpolator`s, two feet shuffle on looping
`PositionInterpolator`s (opposite phases), and `Drag.isActive` goes straight into the `visible` of the stage glow.
17 ROUTE sources (`demo.json` streams, as `tools/behaviour_demo.py check` counts them).

**How to play.** Import the .x3d with the behaviour graph, press Play, grab the brass crossbar (the T-shaped bar above the puppet)
and sweep it left and right. Esc stops. `python build.py` rewrites the .x3d.

## Checked

| Instrument | Result |
|---|---|
| `python tools/behaviour_demo.py check gallery-15-bead-puppet` | 27 nodes, 22 ROUTEs, 17 ROUTE sources, contract 17 |
| Blender 5.3 window, `tools/behaviour_demo.py show` (Host-eyes) | pass; `not_applied` empty; `act_ok` true; Stop restores everything |
| act, sampled every 0.05 s while the pointer swept 150 px (bar moved 1.43 units) | peak lag behind the bar, in world units: Head 0.26, Torso 0.36, HandL 0.56, HandR 0.68, FootL 0.79, FootR 0.95: ordered by `duration` |
| act, 2.5 s after the pointer let go | every bead within 0.00 to 0.04 units of the bar (FootR 0.04 at release, 0.00 at settle) |
| act, Blender data | the glow object is shown while held and hidden after release |
| Screenshots read by eye (act-drag-12, act-held, act-settled) | during the sweep the beads trail the bar and the strings slant, feet furthest; held and settled show the figure re-assembled under the bar |

The numbers come from one live run; the run before the final camera tweak gave the same ordering (FootR 1.13 over a 1.75 sweep).

## Not checked

- No X_ITE recording or judge run: `judges` is `[]`, so no `x_ite.json` for this demo and no claim that these PositionChaser or PlaneSensor
  streams agree with X_ITE. (The 17 sources are counted, not compared.)
- Only an x-only drag was exercised. The y axis is clamped to 0, so strings stay vertical; a free 2D drag would need the strings to stretch,
  and X3D has no way to turn a vec3 into a scale without a Script.
- The Blender screenshot is the solid viewport with the importer's selection outlines, not a render; materials, shadows and the real
  lighting were not looked at.
- Not run: the full Blender test suite (nothing shared was changed).

## Findings for Loom

1. A vec3 follower cannot drive a part of a transform. To make a string stretch to a lagging bead, or to make hands lift in proportion to
   how far the bar travelled, one needs "pick x of an SFVec3f" and "map a scalar to a scale", and X3D has neither outside a Script. This is why the
   puppet's strings are fixed length and the bar travels in x only.
2. A baseline measured at the start of an act is wrong whenever the eye test's own drag has just run: the chasers were still mid-ramp, so a
   first version of this act reported beads "stuck" 0.2 to 1.5 units short of the bar. Waiting longer than the slowest `duration` before reading the
   baseline fixes it (the act yields 2.0 s first). The player was ticking fine: the clock advanced and the beads converged to the bar exactly.
