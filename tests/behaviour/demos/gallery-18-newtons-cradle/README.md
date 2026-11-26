# Gallery 18: Newton's cradle, you pick how many balls fly

**Idea.** Six steel balls hang in a frame. Click a ball to choose the outcome: balls 1, 2, 3 (from the left) lift that many
balls from the left end; balls 6, 5, 4 lift 1, 2, 3 from the right end. The lifted balls fall, the far end kicks out the same
number, they swing back, the first end kicks out again (smaller), the far end once more, and the cradle settles. The physics
is faked by interpolator curves and clocks; the clicks decide which curves play on which balls. Pips on the base show how
many each ball lifts; a yellow disc lights under the ball you clicked.

**Graph.** Six TouchSensors (one per ball) feed six chains: BooleanFilter `Press<c>` → TimeTrigger `Go<c>` → TimeSensor
`Run<c>` (8 s, one clock per choice L1 L2 L3 R3 R2 R1). Each clock drives two OrientationInterpolators: `Lift<c>` (rise 0-1 s,
fall 1-2 s, a smaller echo 4-6 s) fanned out to the k lifted pivots, and `Kick<c>` (swing 2-4 s, a smaller one 6-8 s) fanned
out to the k pivots at the far end; every pivot gets its rotation from up to six interpolators but only the running clock
emits. Lock: `Run<c>.isActive` → BooleanFilter `Busy<c>` → `inputNegate` → `enabled` of the other five clocks, so a click
during a run does nothing. `Busy<c>.inputNegate` also drives the green Ready lamp, `Busy<c>.inputTrue` → BooleanToggle
`Round` → two alternating round lamps (`toggle` and, through a BooleanFilter, its negation). Impact sparks: BooleanSequencers on
the clock's fraction light the gap at t = 2, 4, 6 s. 74 DEF'd nodes, 131 ROUTEs, 66 ROUTE sources, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play, click a ball (for example the third from the left: three fly). Wait for
the green lamp, click another. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-18-newtons-cradle`, Blender 5.3 | Host-eyes **pass**; `act_ok` true; `not_applied` empty; Stop restores |
| Eye test's own click | pivots' swing read from Blender data (angle of each pivot empty away from its rest pose) | clicked ball 1: pivots 0 and 5 swung |
| Act, three real clicks (ball 2, ball 6, ball 3) | same, sampled every 0.05 s of wall time for 9.5 s of `player.now` | lift 2 left: pivots {0,1,4,5} swung; lift 1 right: {0,5}; lift 3 left: all six. Each matched the expected set exactly; the three outcomes differ |
| Order and size | first-move times from `player.now` | lifted group first (0.11 s), the far group only after the fall (2.1 to 2.2 s, designed 2.0); largest swing 0.57-0.58 rad (designed 0.58); all pivots back at rest after each run |
| Headless | the simulator (`behaviour_sim`) press/release on `Touch2`, 10 s | Run starts, Ready lamp goes dark and returns at the end, all pivots end at rest |
| Look | screenshots mid-lift and mid-kick, read by eye | a wooden frame with six coloured metallic balls; the lifted ones (left) hang at an angle on their V strings, then the far-end ones swing out. The frame was widened after the first screenshot showed the lifted ball touching a post |

Not checked: the sparks and the round lamps were not read from data and are small in the screenshots (the spark sphere sits
low in front of the gap; I could not confirm it is visible); lock behaviour (a click during a run) was not exercised in the
window; collision realism (curves, not physics: no momentum, all lifted balls swing as one); X_ITE judging (none).

## Findings for Loom

1. **The importer's Z-up conversion makes each DEF'd Transform an EMPTY resting at a 90 degree X rotation (quaternion
   mode)**, and the DEF also sits on the meshes of its children. A first act that read `matrix_basis.to_euler().z` of every
   object with the DEF saw no motion at all; the swing is the rotation difference from that rest pose, read only from the
   EMPTY.
2. Fan-out from one OrientationInterpolator to k pivots, and several interpolators targeting the same pivot, work in the
   player when only one clock runs at a time.
3. `isActive` → BooleanFilter → `inputNegate` → another TimeSensor's `enabled` works as a mutual-exclusion lock in the
   simulator and the live window.
