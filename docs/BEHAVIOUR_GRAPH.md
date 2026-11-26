# X3D behaviour graph (proof of concept)

An X3D scene's behaviour (sensors, timers, interpolators, event utilities, followers and the ROUTEs between them) as an
editable graph: plain Python data, a Blender node tree, and X3D text, kept in step.

| File | What it is |
|---|---|
| `source/behaviour_catalogue.py` | generated from the X3D Unified Object Model 4.0 by `tools/behaviour_catalogue_gen.py` (`--check` fails when stale): 45 behaviour node types with 303 fields, 32 target types |
| `source/behaviour_graph.py` | the graph without Blender: parse from X3D, validate, edit, emit, weave into a document, compare, lay out, JSON; and the scripting methods (`Behaviour`, `add`, `target`, `>>`) |
| `source/behaviour_nodes.py` | the Blender node tree `X3DBehaviourTree`: one node class per X3D node, one socket class per field type; `apply`, `read`, `target`, `import_graph` |
| `source/behaviour_sim.py` | version 2: the event model in plain Python (`Simulation`): timers, interpolators, sequencers, event utilities, dampers, chasers, pointer events |
| `source/behaviour_play.py` | version 2: `Player(scene)` runs the simulation on the scene's objects, materials and lights and restores them; the Play operator and the sidebar panel |
| `tools/behaviour_sim_judge.cjs`, `tools/behaviour_sim_judge.py`, `tools/behaviour_probe.py` | record X_ITE's events, replay them through the simulator, compare; build the probe world |
| `tests/test_behaviour_sim.py`, `tests/test_behaviour_play_bpy.py` | version 2: 20 plain-Python tests (4 replay X_ITE traces) and 15 Blender tests |
| `tools/behaviour_roundtrip.py` | import a file with its graph, optionally set fields, export, print the graph difference |
| `tools/behaviour_eyetest.py` | open a real Blender window, import each world with its graph, screenshot the editor, Play it with real (simulated) clicks, check Esc restores everything |
| `tools/behaviour_replay.cjs` | play the same real mouse clicks on two files in X_ITE and compare what the scene did |
| `tests/test_behaviour_graph.py`, `tests/test_behaviour_nodes_bpy.py` | 23 plain-Python and 17 Blender tests |
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
| TimeSensor; Scalar, Position, Position2D, Color (HSV) and Orientation (slerp) interpolators; EaseInEaseOut; the Scalar, Position and Position2D Spline interpolators; SquadOrientationInterpolator; Boolean and Integer sequencers; BooleanFilter, BooleanToggle, BooleanTrigger, IntegerTrigger, TimeTrigger; the Scalar, Position, Position2D, Color and Orientation dampers and chasers; TouchSensor, PlaneSensor, CylinderSensor (including disk mode and angle limits) and SphereSensor from the pointer; ProximitySensor from the viewer | Coordinate and Normal interpolators, coordinate and texture-coordinate followers, VisibilitySensor, TransformSensor, KeySensor, StringSensor, LoadSensor, Scripts and PROTOs |

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

## Limits

Looked at on a real screen by a script (see below) and by the owner for `door.x3d` only; nobody has judged the look by
eye on the other four worlds, at other UI scales, or in Blender 4.5 to 5.2 with a window. The player uses the export dialog's default axes (-Z forward, Y up). Of the sensors that need the viewer, only ProximitySensor is simulated, with one 3D view as the viewer (VisibilitySensor is not). XML encoding only on import. Scripts and PROTOs are carried as XML, not edited or
played. Targets are Transform, Viewpoint, lights and materials. Names survive only for what the graph touches. The
importer's loss report still prints "ROUTE not imported" for ROUTEs the graph kept.
