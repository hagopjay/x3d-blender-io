# Gallery 16: haunted gallery

**Idea.** A camera you do not control drifts down a 70 m hall, yawing from wall to wall for a 40 s loop. Sixteen
portraits hang on the walls in eight pairs. As the camera comes level with a pair the calm portraits vanish and
haunted ones (red canvas, yellow eyes, open mouth, horns) take their place, the frames rattle, a ghost rises between
them and the two sconces flare. When the camera leaves, everything goes back to sleep. Four chandeliers sway all the time.

**Graph.** TimeSensor `Drift` → PositionInterpolator and OrientationInterpolator (101 keys each) → the Viewpoint
`Visitor`'s `position` and `orientation`. Per pair `i`: ProximitySensor `Neari` (9 x 4 x 6 m) `isActive` → the two
`Wake` canvases, the ghost and two flames (`visible`), and → BooleanFilter `Asleepi` whose `inputNegate` → the two
`Calm` canvases (`visible`); `enterTime` → 1.2 s TimeSensor `Rattlei` → OrientationInterpolator `Shakei` → both frames'
`rotation`; `enterTime` → 3 s TimeSensor `Risei` → PositionInterpolator `Floati` → the ghost's `translation`. Four looping
TimeSensors → OrientationInterpolators swing the chandeliers. 136 nodes, 132 ROUTEs, 67 ROUTE sources, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play and watch from the scene camera (Numpad 0). No clicks. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-16-haunted-gallery`, Blender 5.3, 42 s of player time, 8 pairs sampled about 4 times a second | Host-eyes **pass**; `act_ok` true; `not_applied` empty; Stop restored everything (`not_restored` empty) |
| Wake order | rising edges of each pair's haunted canvas | 4,5,6,7,0,1,2,3,4,5: one pair after the next, cyclic as the loop wrapped; all 8 pairs woke and all 8 calm canvases went dark |
| Camera | Blender camera position sampled in the act | 66.6 m of travel along the hall |
| Look | act screenshots read by eye | a long hall in perspective: framed calm portraits receding down the wall, ceiling beams, swaying chandelier bulb. In the final run's frames I read (7 and 9 of 14) every portrait in view is still asleep. An earlier run's frames (since overwritten by this run) showed a red awake portrait and a ghost beside the camera; the final run's data (above) says all pairs woke, but I did not see an awake portrait in a final-run frame. |

## Not checked

- X_ITE judging (none: `judges` is empty, no `x_ite.json`).
- Calm and haunted canvases overlap: in 72 of 1328 pair-samples (5%) both were shown at once, probably the one-step lag
  of the BooleanFilter chain on the 5 Hz clock; I did not trace it. The wrong state is brief and still a portrait.
- The solid viewport ignores scene lights and `transparency`, so the ghost reads as an opaque grey-white figure.

## Findings for Loom

1. **A ProximitySensor works from a Viewpoint flight with a wide, yawing camera:** all 8 sensors fired in order, with the
   camera turning ±0.75 rad, so only position matters, not view direction.
2. **Fan-out kept it small:** one `isActive` drives 6 targets per pair, and one `Shake` interpolator drives two frames;
   the whole flight is 2 x 101 keys.
3. **Inverting a bool with BooleanFilter `inputNegate` leaves a brief both-shown overlap** (above) (not compared with a direct
   `isActive` ROUTE).
4. The act's pacing must use `player.now`: 430 yields of 0.1 s took about 106 s of player time.
