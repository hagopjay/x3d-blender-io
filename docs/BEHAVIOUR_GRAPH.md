# X3D behaviour graph (proof of concept)

An X3D scene's behaviour (sensors, timers, interpolators, event utilities, followers and the ROUTEs between them) as an
editable graph: plain Python data, a Blender node tree, and X3D text, kept in step.

| File | What it is |
|---|---|
| `source/behaviour_catalogue.py` | generated from the X3D Unified Object Model 4.0 by `tools/behaviour_catalogue_gen.py` (`--check` fails when stale): 45 behaviour node types with 303 fields, 35 target types |
| `source/behaviour_graph.py` | the graph without Blender: parse from X3D, validate, edit, emit, weave into a document, compare, lay out, JSON; and the scripting methods (`Behaviour`, `add`, `target`, `>>`) |
| `source/behaviour_nodes.py` | the Blender node tree `X3DBehaviourTree`: one node class per X3D node, one socket class per field type; `apply`, `read`, `target`, `import_graph` |
| `source/behaviour_sim.py` | version 2: the event model in plain Python (`Simulation`): timers, interpolators, sequencers, event utilities, dampers, chasers, pointer events |
| `source/behaviour_play.py` | version 2: `Player(scene)` runs the simulation on the scene's objects, materials and lights and restores them; the Play operator and the sidebar panel |
| `tools/behaviour_sim_judge.cjs`, `tools/behaviour_sim_judge.py`, `tools/behaviour_probe.py` | record X_ITE's events, replay them through the simulator, compare; build the probe world |
| `tests/test_behaviour_sim.py`, `tests/test_behaviour_play_bpy.py` | version 2: 20 plain-Python tests (4 replay X_ITE traces) and 15 Blender tests |
| `tools/behaviour_roundtrip.py` | import a file with its graph, optionally set fields, export, print the graph difference |
| `tools/behaviour_record.py` | record a world's full activity (every delivery, every call) from a script, in plain Python |
| `source/behaviour_activity.py` | live activity while playing: the counting model (plain Python) and its drawing in the node editor |
| `tools/behaviour_eyetest.py` | open a real Blender window, import each world with its graph, screenshot the editor, Play it with real (simulated) clicks, check Esc restores everything |
| `tools/behaviour_replay.cjs` | play the same real mouse clicks on two files in X_ITE and compare what the scene did |
| `tests/test_behaviour_graph.py`, `tests/test_behaviour_nodes_bpy.py` | 23 plain-Python and 17 Blender tests |
| `tools/behaviour_fuzz.py`, `tests/test_behaviour_fuzz.py` | random and hostile graphs against the graph, the simulator and the node tree (see Hardening) |
| `tests/behaviour/` | `route-demo.x3d`, the three Wire Lab worlds, and `route-cases.json` (55 ROUTE legality cases shared with the browser Wire Lab) |

## Use

* Import: tick "Behaviour as node graph" (off by default). The scene gets a node tree in `scene.x3d_behaviour_tree`.
  If a node editor is open, the tree is shown in it (one already showing an X3D Behaviour tree first, else the largest),
  laid out so no two nodes overlap, and framed. No other editor is changed. The import's last line says where the graph
  went: "X3D Behaviour: 3 nodes, 3 ROUTEs in node tree 'X3D Behaviour', shown in the node editor." or, with no node
  editor open, "… To see them, switch any editor's type to X3D Behaviour."
* Edit: node editor, tree type "X3D Behaviour". A link between two field types is removed as it is made.
* Export: a scene with a tree writes it. A scene without one exports exactly as before.
* Script (no window needed):

```python
from io_scene_x3d import behaviour_graph as bg, behaviour_nodes as bn   # the package name depends on the install

b = bg.Behaviour()
click = b.add("TouchSensor", "Click", parent="Door")
timer = b.add("TimeSensor", "Timer", cycleInterval=2)
slide = b.add("PositionInterpolator", "Slide", key=[0, 1], keyValue=[(0, 0, 0), (0, 2, 0)])
door = bn.target(b, bpy.data.objects["Door"])
click.touchTime >> timer.startTime
timer.fraction_changed >> slide.set_fraction
slide.value_changed >> door.translation
bn.apply(b, bpy.context.scene)
```

## Rules the exporter keeps

1. Illegal ROUTEs are left out and named in a head `meta` line.
2. The graph's names are reserved before any other DEF: a node called `Timer` is `Timer` in the file.
3. A target is written under its name in the graph (for an imported file, the DEF it came with).
4. A ROUTE whose target is not exported is left out and counted in a head `meta` line.
5. Keyframes of an object the graph drives are not sampled into a second set of interpolators.
6. On import with the graph, keyframes the same import baked for an object the graph drives are removed (and reported).

## Measured (22 Nov 2026; Blender 5.3.0 bpy wheel, Python 3.13.18, x3d.py 4.0.65.8, X_ITE 16.7.1 headless)

| File | ROUTEs | Default import path, re-exported | Graph path, re-exported |
|---|---|---|---|
| route-demo.x3d | 22 | 24 ROUTEs; 9 nodes with changed fields, 1 node added | 22; no difference |
| door.x3d | 3 | 2; all 3 nodes and 3 ROUTEs lost | 3; no difference |
| counter.x3d | 5 | 0; all 4 nodes and 5 ROUTEs lost | 5; no difference |
| snake.x3d | 6 | 2; all 4 nodes and 6 ROUTEs lost | 6; no difference |

Behaviour replay with real clicks (`tools/behaviour_replay.cjs`): door identical before and after the Blender trip. The
counter differed in version 1, because the importer did not read `visible` on a Transform (lamps that start hidden came
back shown). Version 2 reads it: 5 real clicks give the same lamp states before and after the trip.

## Version 2: play it, edit it with real widgets, keep what is hidden

### Play in the viewport

`source/behaviour_sim.py` is the X3D event model in plain Python (no Blender, no browser): `Simulation(graph)`, then
`start`, `step(now)`, and `press` / `release` / `drag` / `click` for the pointer. `source/behaviour_play.py` runs it on
the scene: `Player(scene)` writes each value that reaches a target onto the Blender object, material or light it is
bound to, and `stop()` puts everything back.

In Blender: the **Play** button in the X3D Behaviour editor's header, or the 3D viewport's sidebar (N), tab **X3D**.
While it plays, click or drag what a sensor senses; nodes glow as they send events; **Esc** stops and restores the scene.
Nothing is keyframed and nothing is left changed.

| Simulated | Not simulated (named in the sidebar, never silently skipped) |
|---|---|
| TimeSensor; Scalar, Position, Position2D, Color (HSV) and Orientation (slerp) interpolators; EaseInEaseOut; the Scalar, Position and Position2D Spline interpolators; SquadOrientationInterpolator; the Coordinate, Coordinate2D and Normal interpolators; Boolean and Integer sequencers; BooleanFilter, BooleanToggle, BooleanTrigger, IntegerTrigger, TimeTrigger; the Scalar, Position, Position2D, Color and Orientation dampers and chasers; the Coordinate and TexCoord (2D) dampers and chasers (lists of points); TouchSensor, PlaneSensor, CylinderSensor (including disk mode and angle limits) and SphereSensor from the pointer; ProximitySensor from the viewer | VisibilitySensor, TransformSensor, KeySensor, StringSensor, LoadSensor, Scripts and PROTOs |

Shown on Blender data: Transform translation, rotation, scale, visible; material baseColor / diffuseColor,
emissiveColor, transparency, roughness, metallic; light color and on; Viewpoint set_bind (the scene camera). Anything
else an event reaches is listed as "Not shown".

**Axes.** The exporter writes a parentless object's Transform as `global_matrix @ matrix_world` and a child's as its
matrix in its parent's space. The player turns each object into that Transform, changes the field the event set, and
turns it back. So a value means in the viewport what it means in the file, and a child's values are already in Blender's
axes.

### The simulator is checked against X_ITE

`tools/behaviour_sim_judge.cjs` records every event at every ROUTE source in X_ITE, with X_ITE's own time stamps, while
real mouse clicks are made. `tools/behaviour_sim_judge.py` gives the simulator the same pointer events at the same
times and compares each stream. Recorded 22 Nov 2026, X_ITE 16.7.1, headless Chromium with software GL; the traces are
in `tests/behaviour/x_ite_traces/` and replayed by `tests/test_behaviour_sim.py` on every run.

| File | Event streams | Agree | Worst gap |
|---|---|---|---|
| door.x3d (2 clicks) | 2 | 2 | 0.000001 |
| counter.x3d (5 clicks) | 3 | 3 | 0 |
| snake.x3d (8 s) | 6 | 6 | 0.0048 (followers) |
| probe.x3d (2 clicks; every simulated kind, built by `tools/behaviour_probe.py`) | 25 | 25 | 0.0645 (followers) |
| probe-spline.x3d (2 clicks; EaseInEaseOut, the Spline interpolators, Squad, PositionDamper2D; same tool) | 12 | 12 | 0.000001 exact; 0.0202 (follower) |
| probe-drag.x3d (7 real drags on 5 sensors, `probe-drag.drags.json`; same tools) | 7 | 7 | 0.000007 (matched event for event) |
| probe-proximity.x3d (a camera flight a TimeSensor drives through the Viewpoint; 10 s) | 13 | 13 | 0.000001 |

Tolerances: 0.002 for everything exact, 0.08 for dampers and chasers and what they feed (X_ITE steps them by its frame
rate, the simulator by the clock). Discrete streams must also have the same number of events. What the comparison
taught, all now in the simulator: X_ITE's TimeTrigger and IntegerTrigger answer `true` only; a looping TimeSensor
counts its cycles from `startTime`, not from when the world loaded; a follower chases where its destination was one
frame ago; colours are mixed through HSV, in dampers too; a chaser's answer to a jump is eased (half a cosine), not a
straight ramp. Not judged: PositionChaser2D and ColorChaser (same code as a judged one), and sensors the caller drives.

**Splines, easing and Squad (25 Nov 2026).** Written from X_ITE 16.7's own code and judged against X_ITE 16.7.1 on
`probe-spline.x3d`, recorded the same way. What X_ITE does where the standard leaves room, all now in the simulator:
EaseInEaseOut sends the eased weight within the current key segment (0 to 1), not a fraction mapped back onto the keys,
and scales ease in and ease out down when they add up to more than 1; a Spline interpolator's velocities, when there are
fewer than keys, are padded with zeros (two velocities are not "first and last"); `normalizeVelocity` scales every
velocity but the last to the path length; an open curve's end tangents are zero and a closed curve's first tangent
wraps; tangents are weighted by the key spacing on each side; Squad uses Shoemake's inner points, with an open path's
ends as their own. The judge was checked against five deliberately wrong versions (easing off by 2%, the last velocity
normalised, two velocities read as first and last, Squad as plain slerp, a closed curve treated as open): it rejects
all five. **X_ITE 16.7.1 cannot load a world with a vector Spline interpolator (2D or 3D) whose `keyVelocity` is set and
`normalizeVelocity` is true** ("e.norm is not a function"); the scalar one loads. The simulator runs that case as X_ITE's
code intends; it is not judged. Through Blender, `probe-spline.x3d` keeps 19 of 20 ROUTEs: the one into a
TextureTransform is left out and named (targets are Transform, Viewpoint, lights and materials).

**Coordinate, Coordinate2D and Normal interpolators (26 Nov 2026).** `probe-coord.x3d` (hand written; a TouchSensor starts
a TimeSensor that drives all five interpolators from the same fraction: 3 keys of 4 points into a Coordinate, a
TextureCoordinate and a Normal, plus one with 13 points for 3 keys and one with 2 points for 3 keys) recorded on X_ITE
16.8.1 (headless Chromium, software GL; load average 1.5 at the recording, 79 frames; a first recording at load 4.3 agreed
too). Judged stream by stream with `tools/behaviour_sim_judge_mf.py`: 6 of 6 agree, worst gap 0.000001 (tolerance
0.002). The judge's own reader takes lists of numbers; X_ITE writes an MF value as text and the simulator sends a list of
tuples, so the wrapper flattens both and leaves everything else to the judge. The judge was checked against four wrong
simulators (Normal as a straight lerp, its weight times 0.98, every weight times 1.02, nothing sent for a bad count): it
rejects all four. What X_ITE does where the standard leaves room, now in the simulator: the list sent has
`len(keyValue) // len(key)` points, so a `keyValue` that is not a whole number of lists is read as that many whole lists
(the rest is ignored) and one shorter than `key` sends an empty list on every event (not "nothing"); both are counted in
`sim.noted["bad-count"]`, not in `dropped`, because nothing is lost. A Normal interpolator slerps without normalising and
without taking the short way, so vectors that are not unit vectors can give NaN, which is dropped like every non-finite
value. Not judged: a change of `keyValue` while a fraction is held (X_ITE re-sends for the Normal interpolator only).
Through Blender nothing changes: a ROUTE into a Coordinate, TextureCoordinate or Normal has no Blender datablock to bind
to, so Play shows it as "Not shown: Coordinate.point" as before (no change to `behaviour_play.py`); driving mesh vertices
is not done.

**Followers of lists: CoordinateChaser, CoordinateDamper, TexCoordChaser2D, TexCoordDamper2D (26 Nov 2026).**
`probe-list-followers.x3d` (hand written): six pads (TouchSensors, clicked with the judge's click plan) start timers that
drive a Coordinate and a Coordinate2D interpolator into `set_destination` of all four followers: 4 points, then from 4
to 6 points, from 6 to 2, to no points at all (an interpolator whose `keyValue` is shorter than `key` sends `[]`), from
none back to 4, and lists given to `set_value`. A looping TimeSensor turns a box so that X_ITE keeps drawing between the
clicks. Recorded on X_ITE 16.8.1 (headless Chromium, software GL, Python 3.13.18 / Node as in the other traces; load
average 3.5 to 5.6 by `uptime` around the recordings; 2,006 frames) and judged with `tools/behaviour_sim_judge_mf.py`:
28 of 28 streams agree, among them the four `value_changed` streams (worst gaps: CoordinateDamper 0.022, TexCoordDamper2D
0.041, the two chasers 0.000001; the follower tolerance is 0.08) and the four `isActive` streams (every event time
matches, 131 to 138 events in X_ITE). All four nodes are therefore simulated. The judge was checked against four
simulators that are wrong on purpose (a damper 25% too quick, a chaser 15% too quick, buffers not made as long as the
destination, a missing point taken as the last point instead of zero): it rejects all four
(`test_the_judge_rejects_wrong_list_followers`).

What X_ITE 16.8.1 does with lists, read from its code and checked by recording (the simulator does the same):
- Lists need not be as long as each other. A destination of another length first makes every buffer (a damper's 1 + order,
  a chaser's 60) that long, cut or padded with zero vectors; a point one list lacks counts as the zero vector in every blend.
- A follower's output is as long as the list it blends *from*, so a chaser that started from 1 point and was given 3 sends 1
  point until its slots have shifted once; a damper sends the destination's length from its first step. At rest means the same
  length and every point within tolerance (the largest point distance), so lists of different lengths are never at rest.
- An empty list after an empty list is no event (X_ITE writes the list into `value_changed` point by point and cuts it to
  length), but a list a follower is *given* (`set_value`, the initial value) is assigned whole and is an event even when empty.
- Every `set_destination` or `set_value` wakes a damper, equal or not (the scalar damper wakes only for a different value).
- `initialValue` and `initialDestination` default to one point at the origin for the Coordinate nodes and to no points for the
  TexCoord nodes (the standard's defaults as X_ITE has them).
Where the simulator differs on purpose: an `order` is clamped to 0..5 as X_ITE does, a `tau` of 0 or less jumps (X_ITE with a
negative `tau` diverges), a chaser with `duration` 0 jumps (X_ITE's step time is then 0 and its output NaN), a clock that jumps
to infinity does not make a chaser fault, and a list longer than 10,000 points is cut to that (counted in `sim.noted["capped"]`;
memory is points times 60 slots). Not judged: `tau` or `duration` set at run time, a destination that changes length while
the follower runs (only the stepwise changes above), a list in `set_value` while the follower runs a long chase.
**What the probe cannot judge, found on the way.** X_ITE steps a damper it has just woken by 1 / (its measured frame rate), not
by the time since the last frame, and takes the new destination in the frame that woke it. In a first recording whose
destinations jumped by 1 to 3 at the length changes the 3D damper's worst gap was 0.11 and the 2D one's 0.068 (a damper
that follows a destination already running agrees to 0.000); the probe's destinations are therefore continuous where the
length changes and its new points small, and a first recording without the spinning box (X_ITE idle for a minute between
clicks, so a large first step) gave gaps of 0.52 and 0.32. These are the frame timing of X_ITE under software GL, not the
list rules, and they apply to the scalar dampers as well; they were not chased further.
Through Blender nothing changes: a ROUTE into a Coordinate or TextureCoordinate has no datablock, so Play runs these nodes
and lists "Not shown: Coordinate.point" / "TextureCoordinate.point" (`PlayerListsFollowerPointsTests`), and the importer
leaves out a ROUTE that ends at a Coordinate. Speed: 1,000 CoordinateDampers of 100 points each on one timer
(`tools/behaviour_bench.py --shapes lists --sizes 100 1000`, PYTHONHASHSEED=3, Python 3.13.18, Intel Xeon 2.10 GHz, load
average 3.5 to 4.2 by `uptime`, 300 steps): median **246 ms per step** at 1,000 dampers (p95 335 ms; 2,021 events per step,
peak 90 MB by tracemalloc) and 14.5 ms at 100 (p95 20.6 ms). That is over the 16.7 ms of a frame at 1,000 dampers: 100,000
points a step, each blended three times, in pure Python. Profiled (cProfile, 100 dampers, 30 steps) the first version spent
64% of its time in the generic field-shape test (`_fits`, called for every point of every list on every ROUTE) and 9% in
`_finite`; it ran 51.7 ms per step at 100 dampers (bench tool, same settings, load 2.8). Fixed: a list of vectors is
checked a point at a time in C (`set(map(type, ...))`), once per kind of field for one event instead of once per ROUTE,
`_finite` takes a list of vectors through `math.isfinite` in C, and the followers keep a list as one flat list of floats
(a blend is one comprehension, not a tuple per point). What is left is the blend itself (about 18 microseconds per list of
100 points, three per damper per step), the gap test and the garbage collector (25% of a step: `gc.disable()` took a
step from 185 to 141 ms in a trial). A faster step needs arrays (numpy), which the simulator does not depend on. The
bench shape is opt-in (`--shapes lists`) and is not timed in the Player (there is no Blender data for the points).

### Two files against X_ITE, with their own noise floor

`tools/behaviour_pair_judge.py` (`judge_pair(file_a, file_b, stimulus, repeats=3, x_ite=dist)` and a CLI) replays two
files in X_ITE, `repeats` times each, interleaved A B A B, under the same stimulus, and judges every field a ROUTE ends at
in the scene (matched by DEF and field name; what only one file has is listed as unmatched). It exists because a fixed
1 % threshold failed six unchanged solutions in another repo: on a loaded machine the same file against itself read up to
5.5 %. Each stream gets the disagreement A-versus-B (fraction of samples outside tolerance, largest absolute difference,
for every pairing), the same two numbers for A-versus-A and B-versus-B (the floor, measured in the same session), and a
verdict: "same" (the middle A-versus-B pairing is no worse than the worst repeat-against-repeat pairing), "differs"
(every A-versus-B pairing above the typical floor by 3 times and by at least 1 % of the samples), else "unclear". The
result carries the machine load (`os.getloadavg` before and after every run), X_ITE and Chromium versions, the
tolerances (2 % of each stream's span, samples every 0.05 s from each run's own time zero: the first start of a TimeSensor, else the
first pointer press, else the first cycle start of a TimeSensor) and every raw per-pairing number. CLI exit codes: 0 same, 1 differs, 2 unclear,
3 tool error (Node, Playwright, X_ITE or a file missing, or a stimulus call that X_ITE cannot be given). Stimulus: none or
`{"seconds": 4}` (a timer-only world: load, run, sample), `{"clicks": n, "hold": [ms], "gap": ms}`, `{"click_plan":
[DEF]}`, `{"drags": ...}`, `{"keys": ...}` (the formats of `tools/behaviour_sim_judge.cjs`), or the recorded list
`[{time, call, node, args}]`, of which only `start`, `click` and `press` followed by `release` of one sensor can be
replayed; any other call is a tool error, not skipped. Tests: `tests/test_behaviour_pair_judge.py` (pure parts on
synthetic series; three browser cases, skipped with a reason when Node, Playwright or an X_ITE dist is missing: door.x3d
against itself, against a copy with the interpolator's keyValue changed, and `timer-only.x3d` against itself). Numbers
from the last run are in the commit message of the change that added it.

#### The pair judge on real scenes: blind, simultaneous, rotations (26 Nov 2026)

Its first use on real scenes found three defects, fixed in `tools/behaviour_pair_judge.py`; this subsection replaces what
the text above says about interleaving and raw numbers where they differ.

- **Blind.** In X_ITE a looping TimeSensor with startTime 0 has the wall clock's phase (a cycle starts at every whole
  multiple of `cycleInterval` since 1970). With a watch shorter than the loop no cycle start falls in it, time zero falls back to the
  moment recording began, and a file disagrees with itself on up to all of its samples. The judge used to say "same" then,
  for everything, planted differences included. Now a stream whose median floor pairing (A against A and B against B) has
  0.5 or more of its samples outside tolerance (`blind=0.5`) is "unclear" with `reason: "blind"` (and a `detail` with the
  number), whatever A-versus-B reads; the overall result carries `reason: "blind"` too, and the exit code is 2. "Same" is
  impossible when blind. Measured, `loop-20s.x3d` against itself, sequential, 4 s watch: floor 1.0, unclear, blind.
- **Simultaneous mode** (`mode="simultaneous"`, the default for a world nobody touches; CLI `--mode`). One time zero per run
  was wrong for a scene with several loops (3, 5, 7 s): lined up on one timer, another stream read "differs" though identical.
  Now A and B run at the same moment in two browsers started together and are compared at the same X_ITE time stamps (its
  clock is the wall clock, shared by both), so equal loops are in equal phase with no alignment step. Each repeat runs
  three pairs, A with B, A with A, B with B; the floor is the A with A and B with B pairs. The runs watch `seconds` plus
  2 s and the compared window is the overlap of the two recordings, cut to `seconds`; less than 1 s of overlap is a tool
  error. `mode="sequential"` is the old A B A B layout from each run's own time zero: use it when the world starts on a
  click or a key (the default, `auto`, picks it for any pointer, key or drag stimulus; pointer stimuli cannot be made at the
  same moment in two browsers, so asking for both is a tool error), or for a timer started by an event. Simultaneous mode
  needs a shared wall clock: two browsers on one machine.
- **Rotations as rotations.** An SFRotation or MFRotation stream is compared by the angle between the two rotations (the
  maths of `behaviour_sim._rotation_distance`: `0 1 0 6.17` and `0 -1 0 0.11` are 0.003 rad apart, not 6 apart), the span
  is the widest angle swept from the first value, and the tolerance (2 % of that span) is in radians; each stream says
  `tolerance_unit: "rad"`. A stream whose values are nodes (SFNode, MFNode: `addChildren`, a rigid body's `set_contacts`)
  has nothing to compare: it is listed under `skipped` with the reason, from the catalogue's field type, or, for a node type
  the catalogue does not have, from the values ("Shape { }").

Tests (`tests/test_behaviour_pair_judge.py`): pure ones for a blind floor never giving "same" (nor "differs"), the blind
limit, equal rotations spelled two ways, and node values; browser ones (skipped with a reason when Chromium, Node or X_ITE
is missing) for `loop-20s.x3d` against itself watched 4 s (not blind, same) and against a copy with a changed keyValue
(differs), the same sequentially (blind), `loops-3-5-7.x3d` against itself (same on all three streams), and
`turntable.x3d` with key 3.14159265 against a copy with 3.141593 (differs by about 3.1 rad).

**A turn written as 0, pi, 2 pi (26 Nov 2026).** `probe-turn.x3d`, recorded on X_ITE 16.8.1 (load average 5.4 to 6.2): an
OrientationInterpolator with key `0 0.5 1` and keyValue about y of 0, 3.14159265, 6.28318531 (a hair under pi and 2 pi)
rocks in X_ITE: it turns to pi and comes back to 0, because each half is a shortest-path slerp. The same with 3.141593 and
6.283185 (a hair over) is one continuous full turn, going the other way round first (to about -pi), then on to 2 pi; four
keys 0, 2.0944, 4.18879, 5.23599, 6.28318 turn normally. The simulator agrees at every one of the 62 samples of each
stream (distance 0 at the judge's 6-decimal rounding); no simulator change was needed. The judge already compares
rotations as rotations (the angle between the two quaternions, `behaviour_sim._rotation_distance`, so q and -q and an axis
flip with a negated angle are the same rotation). The same world has a PositionInterpolator with key `0 5e-01 1` and keyValue `0 0 0 1e-05 2.5E+0 -3.0e-1 0 0 0`: X_ITE
parses the exponent forms (`1e-05`, `2.5E+0`, `5e-01`) and the simulator agrees on all 62 samples. To turn a full circle, use more than three keys or write the middle key a
little over pi.

**What a 42-pair run on real scenes asked for (26 Nov 2026).** 39 real scenes and 3 controls gave 25 same, 1 differs, 9
unclear and 4 tool errors in 108 minutes. Four changes in `tools/behaviour_pair_judge.py`:

- **Nothing moved is not a tool error.** A world with a TouchSensor and nothing moving without a click ended with "the two
  simultaneous runs overlapped for 0.00 s" (exit 3). Cause (page log of `touch-still.x3d`, X_ITE 16.8.1, headless Chromium:
  181 requestAnimationFrame ticks, one distinct stamp): `getCurrentTime()` only moves when X_ITE draws a frame, a scene that
  draws nothing leaves every stamp at the start, and the window was derived from the last stamp. The window now comes from the
  recording's own start and its asked-for wait (`_stop`: start plus the wait, or the last drawn frame if later). A stream on which no run of either file
  delivered an event is "unclear" with `reason: "nothing-moved"`, and so is the overall result when every stream is (exit 2);
  a field X_ITE could not hook is `reason: "unobservable"` instead. A stream silent in every run of one file and active in every run of the
  other is "differs" with `reason: "one-side-silent"` (the `detail` says it is silent in every A-versus-B pairing); silent in only some
  runs is left to the floor.
- **Practically still streams.** The verdict rule is unchanged. Each stream now has `span` with `span_unit` ("rad" or "field unit") and, when it
  moved at all and its span is under an absolute limit, `note: "span below 0.001 rad"` (rotations) or `"span below 0.0001 in the field unit"` (every other
  stream; scene units for a length). `notes` is the list, `note` the joined text.
- **Frame rate.** Per run, `frame_rate.per_run` has the drawn frames (distinct X_ITE frame stamps of the page's requestAnimationFrame
  log) over the compared window and frames per second; `frame_rate.median` is over all runs. Per stream, `samples` is the events delivered in each
  run's window. A blind stream with a median under `min_fps` (default 15, `--min-fps`) gets `note: "low frame rate"`; no verdict changes.
- **Cost.** `wall_time_s` has the total and the seconds of every pair (every run, sequentially). `share_runs=True` (CLI `--share-runs`, simultaneous
  only) runs A, A, B, B at once in four pages per repeat: A1 with A2 and B1 with B2 are the floor, the four A-with-B combinations the pairings.
  **Default off.** Measured (the tool itself, X_ITE 16.8.1, 4 cores, 3 repeats, one run after the other; load is the 1-minute load average, which includes the runs):
  `loop-20s.x3d` watched 4 s: three pairs 93.7 s (load 7.2), floor 0.0, same; four pages 32.6 s (load 9.0), floor 0.0, same. `loops-3-5-7.x3d` watched 6 s: three pairs
  111.8 s (load 9.0), floor max 0.0 on all three streams, median 53 frames a second; four pages 39.1 s (load 12.8), floor max 0.11, 0.66 and 0.37 on
  Grower7.scale, Mover3.translation, Turner5.rotation, median 36 frames a second, still "same" but with a floor that is no longer zero. Four browsers at once on four cores are
  3 times faster and the floor is worse, so it is an option for a quick look, not the default. One measurement each: not a distribution.

Tests: pure ones for each rule; browser ones (skipped with a reason without Chromium or X_ITE) for `touch-still.x3d` ("unclear, nothing-moved" in auto mode with no
stimulus), the turntable's frame rate and sample counts, `near-still.x3d` (keys 0 and 6.28319, span 4e-6 rad) carrying the span note, and shared runs.

### Typed field editors

Each single-value field has a real widget (checkbox, number, seconds, colour swatch, vector, axis and angle). An
interpolator's or sequencer's `key` and `keyValue` are one table, a row per key, with add and remove. A node shows its
main fields and whatever has a value; the sidebar shows every field. The stored data is still the X3D text of the file:
a widget reads and writes that text, and a value equal to the standard's default is not stored. **As X3D text** in the
sidebar shows the raw text again.

**Z up** in the editor's header shows places and turns in Blender's axes for nodes whose values reach only parentless
objects (those are the values in the file's Y-up world axes). Only the display turns; the text does not. Values for a
child object are in its parent's axes and are never turned.

### visible="false"

The importer now hides the objects made under a node whose `visible` is false (viewport and render) and marks them
`x3d_visible_false`; the exporter writes `visible="false"` back for an object that is marked and still hidden.
Unhiding it in Blender is the user's choice and is written as visible.

**Drag sensors (26 Nov 2026).** CylinderSensor and SphereSensor run from the pointer's ray and the viewer (where it
is, which way is back), both in the sensor's own coordinates: `Simulation.press(..., ray=, eye=)` and
`drag(..., ray=)`; in Blender, Play takes them from the 3D viewport. The code follows X_ITE 16.7 line by line: the
cylinder's billboarded planes and asin track, its disk mode when the axis points within `diskAngle` of the viewer,
`minAngle` / `maxAngle` by accumulated angle, and "behind" from Inventor's root order; the sphere's track with its
fallback off the sphere, its inverse when pressed behind the centre, `autoOffset`; rotations kept as X_ITE keeps them
(half angle wrapped into [0, pi), compared exactly, read back as made until multiplied). Judged on `probe-drag.x3d`:
`tools/behaviour_sim_judge.cjs` with a drags file makes real drags in X_ITE 16.7.1 and logs every pointer event;
`tools/behaviour_sim_judge.py` rebuilds each ray from the pointer and the Viewpoint, takes the press point from a
TouchSensor beside each drag sensor, and runs the simulator. What the recording taught: the press point is X_ITE's
pick at the pixel's centre (0.5 px right and up), while the drag ray uses the pointer as given; X_ITE follows a press
with one motion on the same ray (a SphereSensor's track point moves off the picked point); X_ITE stamps a press with a
fresh clock and a motion with its last frame's, so a driven sensor is compared event for event, in order, with equal
counts. 7 of 7 streams agree (worst 0.000007). Six deliberately wrong versions are rejected (no motion after the
press, sphere ignoring "behind", cylinder never "behind", limits ignored, never a disk, sphere forgetting its offset);
the two "behind" ones passed until the probe got boxes behind their sensor's origin. Through Blender the world keeps 7
of 12 ROUTEs: the 5 into empty Transforms (hit markers) are left out and named. A sensor's empty parent now keeps its
DEF on export (it came back as `OB_CylBase`).

**ProximitySensor (26 Nov 2026).** `Simulation.viewer(sensor, position, orientation, now, center_of_rotation=)` takes
the viewer in the sensor's own coordinates once a frame: inside the box (`center`, `size`; size -1 -1 -1 is
everywhere) it is active; entering sends isActive, enterTime and all three of position, orientation and centre of
rotation; inside, only what changed; leaving sends isActive false and exitTime. In Blender, Play gives it the scene
camera when the viewport looks through it, else the viewport's eye, with Blender's orbit centre as the centre of
rotation; and a ROUTE into a Viewpoint's `position` or `orientation` now moves the camera, so a scripted camera flight
plays. Judged on `probe-proximity.x3d`: the camera flies a loop through a gate and a turned room with an off-centre
box; a root ProximitySensor of size -1 is X_ITE's own report of the viewer each frame, and the judge hands that pose to
the simulator's other sensors in their coordinates. The recorder now also logs what every source held when recording
began (the room was already active). What the recording taught: X_ITE tests the box against the camera as it was
drawn, one frame behind a viewpoint a ROUTE moves, and reports where the camera is now (`test_position`). 13 of 13
streams agree; four wrong versions are rejected (box tested on the current camera, centre ignored, orientation left in
world axes, the sensor's frame without its rotation). Not caught by this judge: a continuous output re-sent unchanged.
Fixed on the way: a sensor or target in a DEF'd Transform whose unnamed child Transforms hold shapes was bound to a
child (the importer gives them the parent's DEF and name, and calls the Transform "Name.001"); the binding now takes the
outermost object that carries the DEF.

**TimeSensor started in the past (26 Nov 2026).** X_ITE counts a TimeSensor's cycles from its `startTime`, looping or
not: when it starts, `fraction = fract((now - startTime) / cycleInterval)` and the cycle ends when that cycle does. So
`TimeSensor.startTime` fed by an `elapsedTime` (small, so far in the past) starts the sensor part way through a cycle
(0.273 in the first recording) and a non-looping one stops after the remainder, not after `cycleInterval`; with
`startTime` equal to now (a `touchTime`, a `cycleTime`) the fraction starts at 0 and the cycle is whole. A `startTime`
that arrives in the frame a cycle ran out is ignored, because X_ITE ends the cycle after it has sent that frame's
`elapsedTime`; the next one, a frame later, starts the sensor again. The simulator did this only when `loop` was true.
`tools/behaviour_sim_judge.cjs` now takes `--hold=ms,...` (and `--gap=ms`) to hold each press before releasing it; the
replay needs no change, since the press and the release are recorded events. Judged on `probe-timer.x3d`, recorded on
X_ITE 16.8.1 (headless Chromium, software GL) with one press held 0.3 s and one 4.5 s: a held press driving a
`loop` -> `elapsedTime` -> `startTime` chain, the `cycleTime` variant, `touchTime` -> `startTime`, and a sensor stopped
early by `touchTime` -> `stopTime`. 14 of 14 streams agree (worst gap 0, judge tolerance 0.002); the simulator as it
was disagreed on 3 of the 14 (the chained sensor's `fraction_changed` and `isActive`, and the interpolator after it).
All seven older traces still agree (3, 2, 25, 7, 13, 12 and 6 streams). `pauseTime` and `resumeTime` are not simulated
and so not judged. X_ITE's start fraction looks different from X3D 4.0 clause 8.2.4 and 8.4.1 (a non-looping sensor runs
one `cycleInterval` from `startTime`); the simulator follows X_ITE (clause text not re-read here).

**Host-eyes witness.** `tools/behaviour_eyetest.py` ends by writing `host-eyes.json`, a `loom.witness/1` record with
the fields loomkit's own writer writes (`origin` executed, `finished_at` included): the subject is the add-on source
folder's Loom candidate digest, taken before the add-on loads and again at the end (changed means status error); the
instrument is the Blender version, flags and window; per world it records whether it was shown, overlaps, played and
restored, drags and proximity toggles; every screenshot is evidence by sha256; `development` is true while the source
has uncommitted changes. Pass only when every world shown has no overlapping nodes and every world played was put
back. Judged by loomkit itself (x3d.loom main, `accept.judge`): the 8-world run of 26 Nov is accepted (pass, grade C);
the first draft of the record is refused as stale (its own digest), and a development run, a fail, coverage of 7
worlds and one screenshot changed by one bit are each refused.

## Looked at on a real screen (25 Nov 2026)

`tools/behaviour_eyetest.py` opens a Blender window (`--factory-startup --enable-event-simulate`, 1600 x 1000), loads
the add-on from a checkout, and for each world imports it with the graph, screenshots the window and the editor, presses
Play, moves the pointer onto what a sensor senses and clicks through Blender's own event queue (so the modal operator,
the ray cast, the glow and Esc run as they do for a person), then checks the scene against its state before Play.
Blender 5.3.0, macOS 26 arm64. Same rig, add-on `main` 0eb4809 against this version:

| | main 0eb4809 | this version |
|---|---|---|
| Import shows the graph in the open node editor | 0 of 5 worlds | 5 of 5 |
| Pairs of overlapping nodes (counter, probe, route-demo) | 70 (1, 31, 38) | 0 |
| Esc puts every object back (`matrix_basis`, hidden flags) | 5 of 5 | 5 of 5 |
| A real click on the sensed object makes the target move or light | door, counter, probe, route-demo | same |

What the screenshots showed and this version changes: the import opened nothing; nodes overlapped because the layout
spaces rows evenly and a target node is several rows tall (`unstack` now pushes them apart after the first draw, when
the editor knows each node's height); an interpolator with 48 keys drew 48 rows on the node (the node now shows six,
the first five and the last, with a line pointing to the sidebar, which shows all); `startTime="1e+30"` (the file's
"not until an event") was drawn as thirty cut-off digits (it is now its X3D text, labelled "never").

The glow painted a node solid orange for as long as it kept sending, so a running timer's fields could not be read; a
node now flashes (85% of the way to orange) for the first 0.35 s of a run of events and then holds a steady amber (35%)
while it keeps sending (`GLOW_FLASH`, `GLOW_BUSY` in `behaviour_play.py`). The importer still bakes interpolators into
actions (`Door_x3d`, ...) while the graph is built: 7 actions in 4 of the 5 worlds, each on an object the graph drives,
so the timeline played a second copy. The import now removes an action when this import made it, a ROUTE drives its
object, and nothing else uses it, and says so in its report; actions that existed before the import are never touched.
Without the graph, nothing changes (the baked keyframes stay).

Seen and not changed: the sidebar repeats an unlinked input (`key`, `keyValue`) as a bare label after the node's panel
(Blender draws unlinked inputs there).

## Activity while playing

While Play runs, the X3D behaviour node editor shows the events the simulation really delivered: dots travelling along
the links, a glow on a link that just carried something, a count badge at the middle of each link that carried
anything, "in / out" beside each node, and one HUD block (events, events per second, ROUTEs active, widest cascade, the
latest event lines). Checkboxes under Activity in the Play panel (N, tab X3D) switch the overlay, the event lines and
the badges (`Scene.x3d_activity_show`, `x3d_activity_stream`, `x3d_activity_badges`); **Copy activity report** puts the
last Play's numbers on the clipboard as a table. Off, Play pays for one `if`.

What the numbers mean (`source/behaviour_activity.py`, class `Activity`, no Blender needed):

| Word | Meaning |
|---|---|
| event | one line of `Simulation.log`: a node sent a value from an output field |
| delivery | an event carried over one ROUTE, as the simulation delivered it (one per ROUTE per `post` the simulation makes, and only a value that fits the destination) |
| ROUTE total | deliveries over that ROUTE; per second is the last second of simulation time |
| widest cascade | most events sharing one timestamp |
| active ROUTEs a/b | ROUTEs that carried an event in the last second, of all |
| packet | a delivery younger than 0.35 s; at most 3 per ROUTE (a 60 per second stream is grouped by age, the count says how many events a dot stands for) and 400 in all |

Nothing is drawn or counted without a delivered event. `Activity` reads the simulation's log (it replaces `sim.log`
by a `CountingLog`, the same lines in the same order, so a bounded log loses nothing from the totals) and the
simulation's ROUTE table; it never runs or changes the simulation. `Activity.report()` returns the totals, every
ROUTE's count and rate, every node's in and out and the last 200 event lines (a stream within 0.25 s updates one line)
as plain data, `to_json()` as JSON (`x3d.activity/1`), for use outside Blender.

### Full recording (opt in)

`Activity(record=True)`, `Activity.from_simulation(sim, record=True)`, or `Scene.x3d_activity_record` (the "Record full
trace" checkbox, default off) keeps every delivery in order and every call the world received, as plain JSON, up to
200,000 of each (`trace_truncated` says when that was hit; the counts are never capped). `report()` then has:

| Key | Meaning |
|---|---|
| `trace` | `[time, from, from_field, to, to_field, type, value]` per delivery, in the simulation's order, uncoalesced, `value` as JSON numbers, strings, booleans and lists; `null` when recording is off |
| `stimulus` | `{time, call, node, args}` per call: `start`, `step`, `press`, `drag`, `release`, `hover`, `key`, `viewer` (and `click`, `post` for scripts); the Player records the Simulation-level calls it makes (a click is a `press` and a `release`); `null` when off |
| `trace_truncated`, `world` | the cap was hit; the file's name when known |

    {"schema": "x3d.activity/1", "world": "door.x3d", "events": 918, "deliveries": 365,
     "trace": [[0.5, "Click", "touchTime", "Timer", "startTime", "SFTime", 0.5]],
     "stimulus": [{"time": 0.0, "call": "start", "node": null, "args": {}},
                  {"time": 0.5, "call": "press", "node": "Click", "args": {}}], "...": "..."}

A pointer call (`press`, `drag`, `release`, `hover`, `click`) also names the scene object the sensor sits on, as
`"object"` (the sensor's parent: a person points at an object, not at a sensor), next to `"node"`. A sensor at the
scene root, or in a group the graph has no name for, has `"object": null` and a `"note"` saying so. Replay works from
`"node"` alone, or from `"object"` alone (`behaviour_activity.sensors_on(graph, object, parent_of)` finds the sensors
on that object as `Player.sensors_for` does, and `perform` does the call on each).

Sensors with no named parent. The graph keeps only the DEF of the Transform a sensor sits in. A sensor at the scene root
has `parent` None, and `Player.sensors_for` returns it for every object (X3D: a sensor affects the geometry under its
parent group, here the whole scene); `Simulation.click/press/hover` work on it by id. A sensor inside a Transform
without a DEF also has `parent` None (or, nested in a DEF'd one, that DEF), so it answers for more objects than its
siblings: the importer gives it no name, so its siblings cannot be known and nothing is guessed. A test pins this.

`behaviour_activity.replay(Simulation(graph), report["stimulus"])` sends the same events again; the tests require the
trace to come out identical. `tools/behaviour_record.py world.x3d --script stimulus.json --seconds 4 --out
x.activity.json` (plain Python, no Blender) makes a recording from a script of calls; three are committed under
`tests/behaviour/activity/` (door, counter, one CylinderSensor drag on `probe-drag.x3d` with the arguments the X_ITE
drag tests use), each under 60 KB. The simulation forgets which ROUTEs fired at the start of every `post` (a press or a
drag makes several), so Activity feeds each `post` as its own batch (it wraps `sim.post` on the instance); counting a
whole press as one batch under-counted by half in the drag recording, which the trace-against-changes test caught.

Checked, with the instrument:

- `tests/test_behaviour_activity.py` (plain Python, 36 tests, including the recordings and the committed files): counts equal the log of the bench worlds and of
  `door.x3d`; deliveries into Transforms equal the changes the simulation handed back; a bounded log; windows; caps;
  packets empty without events; determinism; the link curve passes through both sockets; packets lie on the curve at
  three zoom scales; panel rectangles stay inside the region.
- `tests/test_behaviour_activity_bpy.py` (bpy 5.3.0 wheel, no window, 8 tests): on the door, counter and snake worlds
  the totals equal what the simulation logged for the same calls; Activity off or on gives the same `values` and the
  same log; the benchmark digest is unchanged with Activity attached; the overlay handler is added once and removed
  (Stop, file load, unregister); the Scene properties come back after being deleted.
- Cost: `Player.step` on the `fan` benchmark graph, N = 1000, 300 steps, `PYTHONHASHSEED=3`, bpy 5.3.0 wheel, a shared
  4-core machine, four runs each way alternating: median 4.35 ms per step off, 4.99 ms on (+15 %; one on-run was disturbed by another job).

The drawing was first seen in a CI run (Blender 5.2.2 LTS, Xvfb, Mesa llvmpipe, OpenGL 4.5, the `eyetest.yml`
workflow), which showed that the first version's socket estimate and its HUD were wrong (inputs about 10 px off, the
HUD under the sidebar). Now: links, glow and packets are drawn in the editor's own view space (a POST_VIEW handler, so
they follow the links at any zoom), text and the HUD in pixels (POST_PIXEL; the HUD in the bottom-left of what the
sidebar and header leave). Socket positions come from a layout measured on that screenshot (header 23.3, row 21.6,
inputs from the node's foot, outputs from its head: `socket_position`), which `--activity-debug` draws as crosses and
node boxes so a run can be checked. Still not looked at by a person: UI scales other than 1, HiDPI, a real GPU,
Blender 4.2 to 5.1, and the latest layout rule on a screen.

## Presets to graph (26 Nov 2026)

The older way to carry behaviour is custom properties on objects (`x3d_trigger`, `x3d_action`, `x3d_target`,
`x3d_radius`, see the top of `source/interaction.py`), which the exporter turns into sensors and ROUTEs and the node
editor cannot show. **Presets to graph** (`x3d.behaviour_from_presets`, `source/behaviour_presets.py`) turns them into
nodes of the scene's behaviour tree, so there is one way. The button is in the X3D Behaviour editor's header and the 3D
view's sidebar (N, tab X3D), and only while the scene has a preset it could convert; it reports what it left alone.
From a script: `presets_to_graph(scene)` returns `(presets converted, notes)`.

| Preset | Becomes | Left alone |
|---|---|---|
| click or proximity, `animate` | a TouchSensor or ProximitySensor sitting in the object; the target's own TimeSensor (`loop` false, `startTime` 1e+30, the scene's cycle); a Position / Orientation / Position interpolator (translation, rotation, scale) for each channel of the target's sampled animation; the ROUTEs from sensor to timer to interpolators to the target's Transform | a target with no animation or not exported (the exporter drops these too); a target the graph already drives |
| click, `viewpoint` | a TouchSensor, a BooleanFilter (only the press binds, the release does not unbind), ROUTEs to the camera's Viewpoint `set_bind` | a target that is not an exported camera |
| proximity, `viewpoint` | a ProximitySensor (`size` is 2 x radius divided by the object's scale), `isActive` routed to `set_bind` | the same |
| `x3d_action` `tour`, `x3d_tour_order`, `x3d_tour_dwell`, the scene's `x3d_tour_*` | nothing: the tour is a rig the exporter writes (a Transform with a Viewpoint, a timer, two interpolators) and the catalogue has no node for it; each object is named in the notes | everything, untouched, and still exported as before |

The key lists, key values and cycle are the exporter's own: the conversion runs the exporter's extraction with the
export dialog's defaults (Animation on, every frame, -Z forward, Y up) and writes the numbers with its formatting.
A scene exported with another frame step or other axes would have sampled differently; the converted keys are the
default ones. Converted objects lose `x3d_trigger`, `x3d_action`, `x3d_target`, `x3d_radius` (so the exporter does not
write the behaviour twice); the target's keyframes are kept (they are the person's), and the exporter ignores them for
an object the graph drives (rule 5), while the timeline still plays them. A second run finds nothing to convert. After
the conversion a sensor's `size` is a plain field: it no longer follows the object's scale.

Measured (Blender 5.3.0 bpy wheel, Python 3.13, `tests/test_behaviour_presets_bpy.py`, 10 tests): a scene with a click
and animate preset (a door that moves and turns: 1 TimeSensor, 3 interpolators), a proximity and viewpoint preset on a
scaled object, and a click and viewpoint preset, exported to X3D 4.0 before and after the conversion and parsed with
`behaviour_graph.parse_x3d`: the same 8 behaviour nodes with the same field values (the ProximitySensor `size` included)
and the same 10 ROUTEs. What differs is names only: the exporter calls a scene node `OB_<object>` or `CA_<camera>` when
the scene alone writes it and the graph's id when the graph holds it, so the test matches a node by its type, set fields
and the object it sits in, and a scene target by its type and object name (one leading `OB_` / `CA_` or trailing
`_viewpoint` taken off); it fails when two nodes have one description. A mutated conversion (sensor box 1 x radius) is
rejected by that test. Played (`behaviour_play.Player`, no window): a click on the converted button leaves the door at
rest until the click, near its half way pose at half the cycle, and at the animation's last pose (z 2.0, turn 1.0) after
it, and Stop puts it back; the click preset binds the scene camera, and the proximity preset binds it when the viewer
moves inside the radius. Not checked: a window (the header and sidebar buttons were not looked at on a real screen), a
browser (X_ITE was not run on the converted file), Blender 4.5 to 5.2.

## Scene targets beyond Transform (26 Nov 2026)

Of 160 real scenes, 17 were left out of a search experiment because a ROUTE ends at a node type the graph did not treat as
a target. This section adds them one at a time. A target is a catalogue type (the field names, types and access come from
X3DUOM 4.0, `tools/behaviour_catalogue_gen.py`), a binding kind that says what Blender holds for it, a way the simulator
delivers to it (every target is delivered to the same way: the value is kept in `values()` and sent on from the field's
`*_changed`), and a rule for what `Player` does with it.

### HAnimJoint, HAnimSite, HAnimSegment

Catalogue: HAnimJoint was already a target type; HAnimSegment and HAnimSite are added (34 target types; ComposedShader makes 35, below). Fields come from
X3DUOM 4.0: a joint and a site have `translation`, `rotation`, `scale`, `center` (SFVec3f, SFRotation, SFVec3f, SFVec3f,
inputOutput), a segment has `centerOfMass` (SFVec3f), `mass` (SFFloat), `momentsOfInertia` (MFFloat) and no placement field at
all. **A ROUTE to `HAnimSegment.rotation` is refused as `unknown-field`**, because X3D 4.0 gives a segment no such field;
the one wild scene whose ROUTE ends there is therefore not a legal graph, and the graph does not pretend otherwise (a
test pins that). Binding kinds: `joint` (a bone, named by the joint's `name` attribute, else its DEF) and `site` (an
object found by DEF; also used for a segment, which has nothing to place). The importer keeps the binding even where
Blender has nothing to show, so the ROUTEs are kept (before: the whole HAnimHumanoid was carried as XML, or the ROUTEs
were dropped).

What `Player` applies. *HAnimJoint*: `rotation`, `translation`, `scale` and `center` turn the pose bone found by name among
the scene's armatures (it must be in exactly one; zero or two are listed under Not shown with the reason, never
guessed). The pose is the importer's own formula for a joint's keys, J = T(translation) T(center) R S T(-center) in the
armature's space and basis = rest^-1 J rest; `center` starts as the bone's head (the importer made the head from the
joint's center). Stop gives back the pose bone's rotation mode, location, rotations and scale. *HAnimSite*:
`translation`, `rotation`, `scale` and `visible` move an object whose name is the DEF or that carries `x3d_def` equal to
it; the importer makes no object for a site, so with an imported file this is listed as not shown. *HAnimSegment*: every
field is listed as not shown (a segment has no placement; the importer makes nothing for it). Not applied for any of the
three: `visible` of a joint, `scaleOrientation`, `limitOrientation`, `llimit`, `ulimit`, `stiffness`, `displacers`, skin
weights, `mass`, `centerOfMass`. Exporting from Blender still drops a ROUTE to a joint (the exporter writes its own joint
DEFs; the diagnostic says "not in the exported file"): only the graph's own `weave`, which writes into a document that
already holds the joint, keeps it. The node tree shows the binding as a text field (`x3d_bone`) because a bone is no object.

Judged on X_ITE 16.8.1 (headless Chromium 157, software GL, load average 2.5 to 4.5 during the runs):
`tests/behaviour/probe-hanim.x3d` drives a joint's rotation, translation, scale and center, a site's rotation and
translation and a segment's centerOfMass and mass from interpolators, and echoes six of them through their `*_changed`.
`tools/behaviour_sim_judge.py` finds the simulator agreeing with X_ITE's recorded events at all 16 streams (and the trace
is a test). The pair judge (`tools/behaviour_pair_judge.py`, 3 repeats, the same click) compares that world, with the
segment left out, against a copy where each joint and site is a Transform of the same DEF: verdict **same** at all 12
watched streams (joint and site fields behave as a Transform's in X_ITE); the same copy with the swing's keyValue
changed from 1 to 2 radians: **differs**, at exactly the two streams that carry it (`hanim_root.rotation` and the
Transform it echoes into), **same** at the other ten. The judge cannot compare a segment against a Transform (it has no
such field); the segment is covered by the trace.

Tests: `tests/test_behaviour_graph.py` `HAnimTargetTests` (6), `tests/test_behaviour_sim.py` (the trace, the values, and
a PlaneSensor press that misses its plane, see the fuzz note), `tests/test_behaviour_play_bpy.py` `HAnimPlayTests` (6,
bpy 5.3.0: the bone moves and equals the importer's keyed pose at a key, stop restores, not-shown reasons, a site found
by `x3d_def`, no bone or two, the node tree keeps the binding). Fuzz after the catalogue grew to 34 targets
(`tools/behaviour_fuzz.py`, Python 3.13.18): `--count 2000 --seed 1` 0 failed (49 854 calls, 6 983 events at targets),
`--hostile` 0 failed (59 336 calls, 1 123 non-finite and 1 467 wrong shapes dropped, 624 isolated faults), `--blender
--count 100 --seed 1` 0 failed; seeds 2 and 3 both ways 0 failed. The first hostile run found one failure the new graph
mix reached (seed 1, graph 246): a PlaneSensor pressed by a ray that never meets its plane left no start point and the
next drag raised `AttributeError` out of `Simulation`; `plane_press` now clears the start point and `plane_drag` sends
nothing until a press has one. Not checked: a real Blender window; a humanoid with several armatures sharing bone names
beyond the two-armature case; a joint whose center is not in the armature's space (the importer's own assumption);
Blender's exporter for joint ROUTEs.

### Switch.whichChoice

`whichChoice` (SFInt32, inputOutput) was in the catalogue; the binding kind is now `switch`, named by the Switch's DEF. The
simulator delivers an index as it comes (an index past the last child and -1 are delivered, not clamped: X_ITE does the
same) and keeps it in `values()`.

What `Player` applies. The importer now tags every object it makes under a DEF'd Switch with `x3d_switch`, "DEF:branch:
whichChoice-in-the-file" for each Switch above it (`import_x3d.switch_branches`; the only change to the importer: a custom
property, nothing else reads it). When `whichChoice` arrives, each tagged object is shown when every Switch above it chooses
its branch (a Switch that has not yet received an event counts as the file's own choice) and hidden otherwise, one object at
a time (the objects under it have their own tags); `stop()` gives back each object's viewport, render and eye state. A Switch
with no tagged object (a scripted graph naming a Switch the importer did not see) is listed "Switch.whichChoice (no object
under Switch 'X')". Not applied: a Switch's `visible`; children that are not objects (a light group, a Script); a Switch
under an Inline or a USE'd Switch's second instance (one object per instance is tagged only when the importer made it);
showing a branch also overrides a `visible="false"` the importer applied to the same object. Import binds a Switch only when
some object carries its tag; otherwise it is carried whole as before. Blender's exporter writes no Switch, so a ROUTE to one
is dropped on export ("not in the exported file").

Judged on X_ITE 16.8.1 (load average 0.4 to 5.8, another agent's browser tests ran at the same time): `probe-switch.x3d`
(an IntegerSequencer 2, 1, -1, 5 into a Switch and the Switch echoed into a second one): the simulator agrees at all 3
streams. Pair judge (3 repeats, one click): the file against a copy with only its title changed, **same** at both
`whichChoice` streams; against a copy with the keyValue 2 1 -1 5 changed to 2 0 -1 5, **differs** at both. The judge
watches the field's events; it does not look at which child X_ITE draws. Tests: `SwitchTargetTests` (3) in
`tests/test_behaviour_graph.py`, two in `tests/test_behaviour_sim.py`, `SwitchPlayTests` (3, bpy 5.3.0: the importer's tags,
one branch shown and then none, nothing found is listed) in `tests/test_behaviour_play_bpy.py`. Fuzz (Python 3.13.18,
bpy 5.3.0): 2000 normal and 2000 hostile graphs of seed 1, and 100 Blender graphs, 0 failed, the same counts as above (the
generated graphs are unchanged: Switch was already a target type). One pinned value changed on purpose: the digest of the node tree built from `probe.x3d` in `tests/test_behaviour_perf.py` (its
Switch `Pick` was a carried node and is now a target node). Not checked: nested Switches (the code takes every Switch above an object into account; no
test builds one), a Switch inside an Inline, X_ITE drawing.

### ComposedShader user-defined fields

A ComposedShader's own fields, the ones its `<field name type accessType value>` children declare, are targets (and sources, for
the output ones). `ComposedShader` joins the catalogue's target types (35 now; its own fields are `activate`, `isSelected`,
`isValid`, `language`, `parts`, `field`) and has the binding kind `shader`, a name only. The graph reads the declarations
from the file inside the target's own node and nowhere else: a `Node` has `declared`, a tuple of `(name, type, access)`;
`resolve_field(type, name, direction, declared)` tries the catalogue's rows and then these, so `x`, `set_x` and `x_changed`
spell a declared inputOutput field as they spell any other; `node_rows(node)` is the node's whole table. There is no PROTO
handling and no declaration is read from anywhere but a ComposedShader's `<field>` children. A declaration that cannot be a
field (an illegal name, a type that is not one of the 40 field types, an unknown access type, a name the node has or has
already declared) is left out of the graph and named in `diagnostics`; the same checks refuse a script's
`target("ComposedShader", "Glow", declared=[...])` with `bad-declaration`. A ROUTE is then checked against the declaration:
a float into a declared `SFColor` is `type-mismatch`; into an outputOnly or initializeOnly field it is `wrong-direction`.
The declarations survive `to_json` / `from_json` (an `x3d_declared` property of the node in the node tree: one "name type
access" per line, with a socket for each).

What `Player` applies: nothing. The simulator delivers and echoes, `values()` holds the last value of each field, and Play
lists each such field under Not shown as `ComposedShader.<field> (a shader's fields are not set in Blender)`. Blender's
exporter writes no ComposedShader, so a ROUTE to one is dropped on export with the usual "not in the exported file" line. The
importer keeps these ROUTEs (before: the whole top-level node that held the Appearance was carried as XML, duplicating the
geometry). A `ShaderPart`, PackagedShader and ProgramShader are not targets.

Judged on X_ITE 16.8.1 (headless Chromium 157, software GL; load average 0.5 to 4.7 during the runs): the judge can watch
these fields, inputOutput and inputOnly alike. `tests/behaviour/probe-shader.x3d` has a shader (with vertex and fragment
parts) whose `uTime` (SFFloat), `uTint` (SFColor), `uSteps` (SFInt32), `uFlag` (SFBool) and `uOffset` (SFVec3f) are fed by an
interpolator or sequencer each and echoed from `*_changed`, and an inputOnly `uScale` (SFVec2f); X_ITE loads it with no page
error and the simulator agrees at all 12 streams recorded (the inputOnly field has no output, so the trace cannot hold it).
The pair judge (3 repeats, one click) finds a copy with only its title changed **same** at all 9 watched streams (the six
shader fields, among them the inputOnly `uScale`, and three they echo into), and a copy with `uTime`'s key value 7.5 changed
to 3 **differs** at `Glow.uTime` and **same** at the other eight. The GLSL in the probe was never inspected for what it
draws: nothing here looks at the picture.

Tests: `ShaderTargetTests` (9) in `tests/test_behaviour_graph.py`, three in `tests/test_behaviour_sim.py` (the trace, the
values and the declared types, a wrong shape dropped), `ShaderPlayTests` (3, bpy 5.3.0: import keeps the shader, its six
declarations and all 18 ROUTEs, the node tree has the sockets and survives apply and read, Play simulates and lists). The fuzz
(`tools/behaviour_fuzz.py`) now gives every ComposedShader of a graph 1 to 5 declared fields of random type and access (110
shaders in the 2000 normal graphs of seed 1, 37 ROUTEs into declared fields and 33 out of them), writes the declarations into
the document of its round-trip check, and types a ROUTE from the declaration. Python 3.13.18, bpy 5.3.0: seeds 1, 2 and 3,
2000 normal and 2000 hostile graphs each, 0 failed (seed 1: 49 713 calls and 7 000 events at targets normal, 58 923 calls
hostile with 1 424 wrong shapes and 1 077 non-finite values dropped and 549 isolated faults); `--blender --count 100 --seed
1` 0 failed. The two normal graphs of seeds 2 and 3 that drop a non-finite value (3 and 1 values) do so on the code before this
change as well. Not checked: a shader with a `ProtoInstance` field, a field type X_ITE does not accept (`SFNode`, rejected
here), what Blender's exporter would write for a shader, the GLSL.

## Hardening (26 Nov 2026)

`tools/behaviour_fuzz.py` throws random graphs at the graph, the simulator and the X3D round trip, deterministic from
`--seed` (graph k of a run comes from `random.Random(seed * 1000003 + k)`); `--blender` adds the node tree and the Player.

**What is generated.** Graph k holds node type k mod 45 and target type k mod 35 of the catalogue (so every behaviour and
every target type is in every 45 graphs), plus up to six more nodes, up to four more targets, 2 to 14 ROUTEs and 8 to 50
calls (`start`, `step`, `click`, `press`, `drag`, `release`, `hover`, `send`, `post`, `viewer`) on random nodes. Normal
graphs: values of the right type, finite, keys increasing with one `keyValue` each, type-correct ROUTEs (also spelled
`set_x` / `x_changed`), with self-loops, cycles, fan-in and fan-out, and times that only go forward. Hostile graphs add
text that is not a number, NaN, infinities, 1e308 and 1e-320, empty and mismatched `key` / `keyValue` lists, unsorted and
repeated keys, zero-length axes, empty and control-character strings, odd names, ROUTEs of the wrong type, to fields
that do not exist and to nodes that do not exist, calls on nodes that cannot take them, wrong Python values for `send`
and `post`, and times that repeat, go backwards, are 1e300, NaN or infinite.

**Properties**, each checked on every graph: (a) nothing but a `BehaviourError` escapes `Simulation`, and a node that is
not run is in `not_simulated`; (b) every call returns in under 2 s (a 20 s alarm stops a hang) and delivers no more events
to targets than one per ROUTE per timestamp allows; (c) every value that reaches a target is finite and of the field's
shape. The rule for hostile graphs: a NaN or an infinity is never delivered to a node or a target, and neither is a
value whose shape does not fit the field it is routed to; each is dropped and counted in `Simulation.dropped`
(`non-finite`, `mismatch`; also `bad-field`: field text that is not a value, the standard's default is used; `bad-time`: a
time that is not a number is ignored; `fault`: see below). A legal graph must drop nothing and have no fault.
(d) `from_x3d(weave(...))` of the graph has no `difference` from it; hostile graphs either do this or `weave` raises a
`BehaviourError`, never a file that cannot be read (a field whose text is empty is unset by design, so it is compared as
unset); (e) a second run of the same graph and calls gives the same log, values and counters.
`Simulation.faults` names a node that raised and was left out of that one event (a sensor fed an impossible ray, a
distance that overflows beyond about 1e154): for a legal graph there are none, for a hostile one they are counted and
the rest of the graph runs on.

**Counts** (tools/behaviour_fuzz.py, Python 3.13.18, 22 Nov add-on code plus the fixes below; the run takes 2 to 4 s):
seeds 1, 2 and 3, 2000 normal and 2000 hostile graphs each: no failure of (a) to (e). About 50 000 calls and 6 500 to
7 100 events at targets per normal run; about 59 000 calls per hostile run, with per run about 2 100 field texts that
were not values, 1 700 times that were not numbers, 1 050 non-finite values and 1 300 wrong shapes dropped, and 120 to
170 isolated faults (all `OverflowError` from magnitudes beyond about 1e154, and Cylinder/SphereSensor geometry that a
degenerate ray makes impossible). Slowest call 0.003 s. The checks were each shown able to fail: with the non-finite
filter, the shape filter, the loop rule, the fault guard, the round-trip writer or determinism taken out, the matching
property fails (22, 52, 16, 17, 20 and 50 graphs of the first 300, 300, 60, 300, 300 and 50). The same hostile seed 1 on
the code before the fixes: 1055 of 2000 graphs raised out of `Simulation`, 271 delivered NaN, infinity or a wrong shape to a
target, 2 broke the round trip; the normal graphs were already clean (0 of 2000).

| Finding (hostile, seed 1, graphs listed) | Fix |
|---|---|
| `Simulation(...)` raised `ValueError` on field text that is not a number (`cycleInterval="abc"`, `"1e"`, `"0x10"`; 703 graphs: 0, 3, 5, 9 ...) | field text that is not a value is the standard's default, counted in `dropped["bad-field"]` (`_Machine._read`); `parse_value` itself reads such text as empty, so the editor's own draw and sync code cannot raise on it either |
| `Simulation(...)` raised `OverflowError` / `ValueError` on `inf` or `nan` in an Int32 or Time field (graphs 29, 120, 128 ...) | a non-finite field value is the default too |
| a Damper with `order=1e9` allocated a billion-entry list (graphs 21, 87, 125, 137; the process was killed for memory) | order is clamped to 64 (X3D: 0 to 5) |
| a spline with three equal keys (legal X3D) divided by zero when built: node never built (graphs 50, 79, 259 ...) | zero spacing gives a zero tangent; a segment of zero span gives weight 0 |
| `send` of a wrong-typed or non-finite value raised `TypeError`, `OverflowError` ... inside a node (34 + 25 + 11 + 10 graphs: 32, 46, 49, 88 ...) | `send` checks the value against the field and raises `BehaviourError("bad-value")` |
| a NaN or an infinity, or a value of the wrong shape (a float into `translation`, a vector into `string`), was delivered to a target (271 graphs: 2, 4, 10, 92 ...) | dropped at the node's output and at the ROUTE's end, counted |
| `step(inf)` raised, `step(nan)` put NaN into a running timer (graphs 954, 703, 1050 ...) | a time that is not a number is ignored, counted in `dropped["bad-time"]` |
| `press` / `drag` / `viewer` with a NaN raised `ValueError`, then `release` raised `AttributeError` (graphs 151, 236, 366 ...) | non-finite pointer input is ignored; a failed `press` leaves the sensor with nothing to drag or release |
| a node that raised in `receive`, `tick`, `start` or a sensor call ended the whole call (all of the above, and overflow in dampers and chasers) | each such call is isolated: the node is left out of that event and `Simulation.faults` says which |
| `weave` raised the XML `ParseError` for a field holding a control character (hostile seed 1, 2 graphs) | `validate` reports `bad-value`, `weave` raises `BehaviourError("bad-value")`, `node_xml` drops the character so an export stays well-formed |
| a DEF ending in a newline was legal (`$` matches before it) and was written into ROUTE attributes (found by reading the regular expression; hostile names now include it) | `\Z` |
| Blender: `Player.stop()` restored an object through its matrix, so Euler angles came back as an equal rotation with other numbers (`(0.011, -2.24, 2.97)` became `(-3.13, -0.90, -0.17)`) and a location 3e-8 off (Blender seed 1, graphs 2 and 18 of 20) | `_TransformState` keeps the location, rotation and scale properties and gives them back |

**Blender pass** (`tools/behaviour_fuzz.py --blender`, bpy 5.3.0): 200 normal graphs, seeds 1 and 2, through
`behaviour_nodes.apply` then `read` (no `difference`), then `Player` (start, 30 steps, a click or a press-drag-release
every fourth step, the viewer moved, stop): nothing raised and every object's matrix, location, rotation, scale, visibility
and lamp colour, every material's colour and the scene camera exactly as before; 55 and 60 of the 200 graphs changed the
scene while playing. 200 hostile graphs played directly (the node tree removes a link between two field types as it is
made, so there is nothing to compare): the same. Each takes about 11 s. The suite runs 20 of each.

**Not covered.** Values of node type (`SFNode`, `MFNode`) are never generated; Script, PROTO and carried nodes are not
generated; wrong-shaped Python arguments to `press`, `drag` and `viewer` (a point of two numbers) are not tried, only
wrong numbers; no window, so the editor's drawing code is reached only through `apply` and `read`; the simulator's
agreement with X_ITE is not tested on random graphs (only the recorded worlds, as before); nothing here says the values
are right, only that they are finite, shaped and bounded; the Blender pass was run on bpy 5.3.0 only, and each graph
in a fresh scene; a node that overflows beyond 1e154 is isolated, not made to compute the answer.
## How fast (26 Nov 2026)

Instrument: `tools/behaviour_bench.py` (300 steps of 1/60 s per case, median per step), Intel Xeon Processor @ 2.10GHz
(from /proc/cpuinfo, 4 cores, shared machine, load average 1.1 to 3.5 during the runs), Python 3.13.18, Blender 5.3.0 bpy
wheel, `PYTHONHASHSEED=3`. "Before" is the add-on at 2.7.5; "after" is 2.7.6, which holds the performance work and the
hardening checks together. Same events in the same order with the same values (a digest test pins it).
Shapes: fan = one looping TimeSensor into N PositionInterpolators; chains = N times TimeSensor, PositionInterpolator,
PositionDamper; mixed = N copies of the door graph with one click per 10 copies.

Simulation alone, ms per step (60 steps per second needs 16.7 or less), both columns measured back to back in one run:

| shape | N=10 | N=100 | N=1000 | N=5000 |
|---|---:|---:|---:|---:|
| fan, before / after | 0.024 / 0.024 | 0.21 / 0.22 | 2.33 / 2.48 | 14.9 / 14.7 |
| chains, before / after | 0.08 / 0.12 | 0.94 / 0.72 | 11.7 / 9.8 | 89.6 / 79.3 |
| mixed, before / after | 0.005 / 0.005 | 0.032 / 0.027 | 0.30 / 0.26 | 1.95 / 1.68 |

So the simulation alone is about level on fan and 12 to 16 % faster on chains and mixed from N=1000 up. The performance
work alone had measured 1.66 ms on fan N=1000; the hardening checks (every value is tested for NaN, infinity and shape
before it is delivered) take that back. Their first form cost more than the gain (4.3 ms); a checker built once per
ROUTE for its target's field type brought it to the numbers above.

Player.step in Blender (one empty per target; node glow only where the node tree was built, up to 1000 nodes, because
building the tree with `behaviour_nodes.apply` itself takes 7 s for 600 nodes), ms per step. "Before" was measured in an
earlier run on the same machine, "after" in the run above:

| shape | N=10 | N=100 | N=300 | N=1000 | N=5000 |
|---|---:|---:|---:|---:|---:|
| fan, before / after | 0.13 / 0.12 | 1.17 / 0.91 | 5.87 / 2.39 | 30.4 / 4.45 | did not finish in 40 s (54 steps, 751 each) / 28.0 |
| chains, before / after | 0.25 / 0.23 | 2.12 / 1.75 | 5.66 / 3.17 | 41.2 / 13.1 | did not finish in 40 s (49 steps, 803 each) / 102 |
| mixed, before / after | 0.02 / 0.02 | 0.17 / 0.12 | 0.43 / 0.12 | 3.63 / 0.38 | 107 / 3.37 |

What was slow: the player looked each object up by name (`bpy.data.objects.get`, about 8 microseconds, more on big
scenes) for every event, and walked every node of the tree each step to see whether it should glow. It now remembers
the object it moved (and checks it was not deleted or renamed) and visits only the nodes that sent something. The
simulator builds each ROUTE's key once and skips non-timer nodes when it ticks.

A warning about the instrument: Python's string hash seed changes the fan timing by itself. With `PYTHONHASHSEED` 1 to
6, fan N=1000 read 4.02, 3.93, 2.23, 2.30, 2.40, 2.34 ms on 2.7.5 and 2.61, 2.38, 2.36, 2.36, 2.49, 2.30 ms on 2.7.6.
Compare two versions under the same seed, or the difference you see may be the seed.

Largest size that holds 60 steps per second on this machine (checked at 10, 100, 300, 1000 and 5000 only): the
simulation, fan 5000, mixed 5000, chains between 1000 and 5000; the player, fan 1000 and chains 1000 (fan 5000 takes
28 ms, chains 5000 102 ms), mixed 5000. Not measured: a real viewport redraw, which costs more than these numbers.

## Limits

Looked at on a real screen by a script (see below) and by the owner for `door.x3d` only; nobody has judged the look by
eye on the other four worlds, at other UI scales, or in Blender 4.5 to 5.2 with a window. The player uses the Forward and Up axes set under Play in the X3D sidebar tab (default -Z and Y, the export dialog's defaults; the first Play takes the axes the export dialog was last used with in this Blender session); it does not follow a later change to the dialog, so set them to match your export. Of the sensors that need the viewer, only ProximitySensor is simulated, with one 3D view as the viewer (VisibilitySensor is not). XML encoding only on import. Scripts and PROTOs are carried as XML, not edited or
played. Targets are Transform, Viewpoint, lights, materials, Text, Switch, HAnimJoint, HAnimSite, HAnimSegment and a ComposedShader's declared fields (see Scene targets beyond Transform). Names survive only for what the graph touches. The
importer's loss report (`scene["x3d_import_losses"]`) leaves out ROUTEs the node tree holds when "Behaviour as node graph" is on, and so do the "X3D import loss" log lines and `X3D_IMPORT_STRICT=1`: the importer holds its ROUTE losses back until the graph is built, then reports only those the graph could not keep. Losses that are not ROUTEs (event nodes, timers, sensor fields) are reported at once, as with the option off.

### Building the node tree

Instrument: `tools/behaviour_bench.py --tree` (one case per process; seconds for `behaviour_nodes.apply` onto an empty
scene, with milliseconds per node in brackets), same machine and Blender as above, load average 0.4 to 4.4 during the
runs (the "before" column ran at 0.4 to 3.5, the "after" column at 2.3 to 4.4, so differences under about 10 % are
noise). "Before" is the code at 8e4f4fb, "after" the code with the changes below. `read` of the finished tree takes
0.02 s or less for every size that finished (it was 0.25 s at 2001 nodes: see below). A second `apply` onto the existing tree costs the
same as the first.

| shape | N (nodes) | apply before | apply after |
|---|---:|---:|---:|
| fan | 10 (21) | 0.019 (0.89) | 0.017 (0.81) |
| fan | 30 (61) | 0.090 (1.48) | 0.108 (1.77) |
| fan | 100 (201) | 0.825 (4.10) | 0.810 (4.03); 0.74 in two other runs |
| fan | 300 (601) | 6.56 (10.9) | 6.16 (10.3); 5.65 in another run |
| fan | 1000 (2001) | 78.1 (39.0) | 68.8 (34.4) |
| chains | 100 (400) | 3.22 (8.05) | 2.91 (7.28) |
| chains | 300 (1200) | 28.6 (23.8) | 26.8 (22.3) |
| chains | 1000 (4000) | did not finish in 200 s | did not finish in 120 s |
| mixed | 100 (400) | 3.70 (9.25) | 3.38 (8.45) |
| mixed | 300 (1200) | 32.0 (26.6) | 30.6 (25.5) |
| mixed | 1000 (4000) | did not finish in 200 s | did not finish in 120 s |

It is still not linear, and what is left is inside Blender, not in this add-on. cProfile (fan N=100) puts 88 % of `apply` in the Blender calls made from `_make_sockets` and `apply` itself:
`inputs.new`, `outputs.new` and the property sets that Blender answers with a check of the whole tree (a gdb stack
sampled during a loop of `node.location = ...` shows `RNA_property_update`, `BKE_main_ensure_invariants`,
`NodeTreeMainUpdater::update_tree` and `ensure_topology_cache`). Every `nodes.new`, `inputs.new`, `links.new`, `name` and
`location` call pays for the nodes and sockets already in the tree: about 0.15 microseconds per socket per call, 7222
sockets and about 9600 such calls for the 601-node fan. The same shape shows in a minimal script without this add-on (a
Python node tree with a Python or a built-in socket type, 300 nodes of 10 sockets: 0.87 s to build, and one `location`
set then costs 0.44 ms; with 100, 200 and 400 nodes of 6 sockets the build took 0.16, 0.65 and 2.2 s). What
the add-on could change, it did, in `behaviour_nodes.py`:

* the tree's own `update` callback (it removes a link between two field types) walked every link in Python after every
  change, so a build of L links did L times L work in Python; it now waits while `apply` fills the tree, and one pass
  after the build removes the links of unequal types;
* a node gets its sockets after all nodes are made, so the node, its name and its place are set while the tree holds no
  sockets, and the sockets are made in the same order afterwards (about 10 to 14 % less than before);
* `read` built the set of all routes for every link (`Graph.route`), 0.25 s at 2001 nodes; it now checks duplicates with
  one set (0.014 s).

The result is the same tree: `tests/test_behaviour_perf.py` pins a digest of every node, field, socket and link of
three trees (door, probe, mixed N=20), computed before the change. Not done because it would change what is built:
fewer sockets (the dump holds every socket) or sockets made only when a link needs them.
