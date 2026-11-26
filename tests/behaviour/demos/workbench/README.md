# Workbench: drag, turn, spin

A warm workshop bench under one lamp, with three toys. Each toy is a drag sensor, and each has something that follows it
(`docs/BEHAVIOUR_DEMOS.md`, section 1). Everything on this page was measured on one MacBook (Apple silicon, macOS), X_ITE
16.7.1 in headless Chromium with software GL, Blender 5.3.0, the add-on from this checkout.

| Toy | Sensor | What follows |
|---|---|---|
| **Fader**: a brass knob on a 2 m track | `PlaneSensor` `Slide`, `minPosition -1 0`, `maxPosition 1 0` (x only) | the knob (`translation_changed`); a toy car on a parallel rail through a `PositionChaser` (`duration 0.8`): it lags and catches up |
| **Dial**: a big brass knob in a panel | `CylinderSensor` `Turn` (`autoOffset true`) | the dial (`rotation_changed`); `isActive` true starts a 2 s colour sweep: `BooleanFilter` `Press` → `TimeTrigger` `Kick` → `TimeSensor` `Sweep` → `ColorInterpolator` `Colours` (amber, rose, teal) → `ColorChaser` `GlowChase` (`duration 3`, not the spec's 0.6: see below) → the lamp shade's `emissiveColor` and the bench light's `color` |
| **Globe** | `SphereSensor` `Roll` | the globe (`rotation_changed`); a moon on an arm through an `OrientationChaser` `MoonChase` (`duration 2`, spec silent), trailing the globe's turn |

The spec gives the ColorChaser 0.6 s. At that length the recorded frames (X_ITE ran at 7 to 18 frames a second here) came
so close to a ramp's length that few fell inside one, and the ramp's shape was hardly sampled: a first version of this demo
judged the ColorChaser at a worst gap of 0.000000 and still passed with the ramp made linear. So `GlowChase` runs 3 s and
`MoonChase` 2 s (a 0.8 s moon chaser also met a 0.8 s frame stall once, finding 6): about 35 to 55 frames fall inside each ramp.
The lamp therefore follows the sweep slowly, about 5 s from the press to teal.

Three `TouchSensor`s sit beside the drag sensors only so the recorder logs the press point (as `probe-drag` does); their
`hitPoint_changed` goes to three empty Transforms.

Files: `build.py` writes `workbench.x3d` and `drags.json` (`python tests/behaviour/demos/workbench/build.py`);
`x_ite.json` is X_ITE's trace; `act.py` is the live-window act; `shots/` are four screenshots from the run below.

## Play it in Blender

File > Import > X3D with "Behaviour graph" on, then Play in the X3D Behaviour editor. Grab the brass knob (or the track) and
slide it along; grab the brass dial and sweep the pointer round its face; grab the globe and sweep across it. The lamp's
colours show in Material Preview with "Scene Lights" and "Scene World" on (Blender's studio lighting washes them out).
Esc stops and puts everything back.

## Checked

### The judge: X_ITE 16.7.1, 12 of 12 streams agree

`python tools/behaviour_demo.py check|record|judge workbench`, `demo.json` `judges: ["PlaneSensor", "ColorChaser"]`.
The recorder made four real drags in X_ITE (fader out and back past both limits and stopped at +0.4 m; a second short grab
of the fader to show `autoOffset`; the dial three quarters of a turn; the globe a diagonal sweep); the simulator is given
the same pointer and steps at X_ITE's own frames.

| Stream | X_ITE events | Simulator events | Worst gap | Tolerance |
|---|---|---|---|---|
| `Slide.translation_changed` (PlaneSensor, driven, matched in order) | 68 | 68 | 0.000000 | 0.002 |
| `Slide.trackPoint_changed` | 73 | 73 | 0.000001 | 0.002 |
| `CarChase.value_changed` (PositionChaser) | 194 | 189 | 0.021307 | 0.08 |
| `Turn.rotation_changed` (CylinderSensor, driven) | 41 | 41 | 0.000000 | 0.002 |
| `Turn.isActive` | 2 | 2 | 0.000000 | 0.002 |
| `Press.inputTrue` | 1 | 1 | 0.000000 | 0.002 |
| `Kick.triggerTime` | 1 | 1 | 0.000000 | 0.002 |
| `Sweep.fraction_changed` | 20 | 21 | 0.000000 | 0.002 |
| `Colours.value_changed` | 20 | 21 | 0.000000 | 0.002 |
| `GlowChase.value_changed` (ColorChaser) | 63 | 64 | 0.000000 | 0.08 |
| `Roll.rotation_changed` (SphereSensor, driven) | 34 | 34 | 0.000004 | 0.002 |
| `MoonChase.value_changed` (OrientationChaser) | 128 | 127 | 0.005459 | 0.08 |

(Gap: largest distance between X_ITE's value and the simulator's at each X_ITE event; rotations by the angle between them.
The three driven sensors are matched event for event, in order; the others by time. Event counts of the time-driven
streams differ by one or two at the ends of a run; I did not look into why.)

The ramp is sampled well: in the committed recording `GlowChase` ticked 63 times, `MoonChase` 128 and `CarChase` 194, at a
median gap of 0.05 to 0.06 s (about 18 frames a second) against ramps of 3, 2 and 0.8 s.

Recordings: three of this version of the world (`GlowChase` 3 s, `MoonChase` 2 s), made while other sessions loaded the
machine (load average 4 to 11); all three passed 12 of 12 (`CarChase` 0.004 to 0.029, `GlowChase` 0.000, `MoonChase` 0.003 to
0.005). The committed trace is the first. Before this change, seven recordings of the earlier version (`GlowChase` 0.6 s,
`MoonChase` 0.8 s) were made: six passed with `CarChase` 0.013 to 0.072 and `MoonChase` 0.002 to 0.008; one (a frame gap
of about 0.8 s, the chaser's own duration) failed `MoonChase` at 0.097. A further recording with `GlowChase` at 3 s but
`MoonChase` still 0.8 s failed `MoonChase` at 0.091 the same way, which is why `MoonChase` was lengthened too (finding 6).

### What changed in the simulator, and the deliberately wrong versions

New or changed code: `_PlaneSensor` (X_ITE's PlaneSensor from the pointer's ray: a line on the screen when one axis is
limited, a plane otherwise); `_BufferChaser`, `_ColorChaser`, `_OrientationChaser` (X_ITE's 60-slot chaser, HSV for colour,
quaternions for orientation); in the judge, the PlaneSensor replay (camera orientation, camera axes, X_ITE's time stamp for
a press and release, stepping at X_ITE's frames). Each deliberately wrong version was applied alone with a script that restores
the file afterwards, and `judge workbench` was run:

| Wrong version | `GlowChase` gap | `MoonChase` gap | Rejected (failing streams) |
|---|---|---|---|
| **the honest simulator** | **0.000000** | **0.005459** | passes 12 of 12 |
| P1 a plane even when one axis is limited | 0.000000 | 0.005459 | `Slide.translation_changed`, `Slide.trackPoint_changed` |
| P2 no clamp at the limits | 0.000000 | 0.005459 | `Slide.translation_changed`, `CarChase.value_changed` |
| P3 the offset ignored at the press | 0.000000 | 0.005459 | `Slide.translation_changed`, `CarChase.value_changed` |
| P4 the camera ignored (nearest the ray, not nearest its picture) | 0.000000 | 0.005459 | `Slide.translation_changed`, `Slide.trackPoint_changed` |
| P5 `translation_changed` sent every time | 0.000000 | 0.005459 | `Slide.translation_changed` |
| P6 the track point on the grabbed line, not the axis line | 0.000000 | 0.005459 | `Slide.trackPoint_changed` |
| P7 `autoOffset` not kept on release | 0.000000 | 0.005459 | `Slide.translation_changed`, `CarChase.value_changed` |
| J1 replay ignores the viewpoint's orientation | 0.000000 | 3.035660 | `Slide.translation_changed`, `Slide.trackPoint_changed`, `Turn.rotation_changed`, `Roll.rotation_changed`, `MoonChase.value_changed` |
| J2 replay puts the eye 1 m too low | 0.000000 | 2.535983 | the same five |
| J3 press and release not stamped by X_ITE's clock | 0.000757 | 0.005459 | `Press.inputTrue`, `Kick.triggerTime` |
| J4 replay leaves PlaneSensor to the recording | 0.000000 | 0.005459 | count: 10 of 10 streams, contract says 12 (no stream names it) |
| J5 camera up vector taken without the pitch | 0.000000 | 0.005459 | `Slide.translation_changed`, `Slide.trackPoint_changed` |
| J6 the simulator stepped at every page frame, not X_ITE's | 0.146184 | 0.038263 | `GlowChase.value_changed` |
| C2 **the buffer chaser's `ramp` linear** (`age / duration`), not a half cosine | 0.124446 | 0.083192 | `GlowChase.value_changed`, `MoonChase.value_changed` |
| C1 **ColorChaser in RGB, not HSV** (lift and lower identity, blend a plain lerp) | 0.306787 | 0.005459 | `GlowChase.value_changed` |
| C5 **hue never goes the short way round** (the `abs(hb - ha) <= pi` branch dropped) | 0.770226 | 0.005459 | `GlowChase.value_changed` |
| C3 no spreading of a frame's change over the frame | 0.151613 | 0.052868 | `GlowChase.value_changed` |
| C4 slot spacing wrong (duration / 120) | 0.481634 | 0.255993 | `GlowChase.value_changed`, `MoonChase.value_changed` |
| C6 colour steps added with the wrong sign | 0.969779 | 0.005459 | `GlowChase.value_changed` |
| O1 rotation steps composed the other way | 0.000000 | 0.775161 | `MoonChase.value_changed` |
| O2 the orientation chaser stops within 0.5 rad | 0.000000 | 0.473360 | `MoonChase.value_changed` |
| O3 the ramp a square, not a half cosine | 0.588748 | 0.345564 | `GlowChase.value_changed`, `MoonChase.value_changed` |

All 22 are rejected on the committed trace. The three the lead asked to see are in bold: the chaser's ramp linear
(`GlowChase` 0.124, `MoonChase` 0.083), the colour chased in RGB (`GlowChase` 0.307), and the hue sent the long way round
(`GlowChase` 0.770), against the honest simulator's 0.000000, all with the tolerance unchanged at 0.08. (Before the
chasers were lengthened, J3, J6 and C2 passed the committed trace and only some of the other recordings rejected them.)

Plain unit tests for the same code (no X_ITE, no Blender): `tests/test_behaviour_demo_workbench.py` (10 tests: the folder is
what `build.py` writes; the line follows the pointer's picture and not a plane, with a worked number; limits; `autoOffset`;
what is sent after the first motion; the colour goes through hue, settles and says so; an orientation chaser fed a new
destination every frame holds a constant lag). The full suite in Blender 5.3 (`run_tests_in_blender.py`, `-b`): 1115 tests,
1 failure (`test_import_extreme_scale_bpy.test_inverted_helper`, known, not this work), 49 skipped for tools this machine lacks
(the glTF validator, X3DUOM); no other failure. Play was not changed, so there is no `tests/test_behaviour_demo_workbench_bpy.py`.

### The live window: Host-eyes pass

`python tools/behaviour_demo.py show workbench --out DIR`, Blender 5.3.0, 1600 x 1000, input through Blender's event queue
(`--enable-event-simulate`). `host-eyes.json` (from the committed tree, `development` false): `pass`, 1 of 1 worlds shown, laid out, played and restored; `act_ok` true;
`not_applied` empty; `not_simulated` empty; Stop put everything back (`restored` true, `not_restored` empty).
`act.py` finds every object by the DEF the importer recorded, drags each toy through the event queue with a screenshot
mid-drag, and checks (all true): the knob reached +1 m and then -1 m (the clamps); the car never moved before the knob,
lagged it by up to 1.0 m (1.023), and was within 0.03 m of the knob 1.4 s after it stopped; the dial turned (3.14 rad at its
furthest from where it began, the largest angle a short-way measure can show); the lamp changed colour (largest change 0.80 in
one channel), the shade's emission and the bench light's colour both ended teal; the globe turned 1.65 rad and the moon
followed it (at the release it had turned 2.36 rad where the globe was at 1.65, the moon trailing the path the globe
had swept, and 3.5 s later it was within 0.001 rad). While the knob slid, its picture stayed within 6.1 px of the pointer
(76 px a metre at the knob): that is Play's own plane drag, see finding 9.

What I saw in the screenshots (`shots/`): the knob well along its track and the car on its rail behind it, to the left (the
car chasing the fader); the lamp shade, its glow and the track lit green in the middle of the dial's sweep, with the dial's
pointer no longer at twelve o'clock (green because the colour chaser runs in HSV and was heading from the previous sweep's
teal back to amber, not a mistake in the picture), and teal-blue in the full-window shot a little later; the moon on its arm
out to the upper right of the globe; and, in the full-window shot, the node editor beside the bench with some nodes tinted
(the ones that had just sent events). I judged colour and position by eye on those four pictures only; I did not watch a
person use it. I did not see amber and rose in a picture this time (the earlier, 0.6 s version showed rose).

### Not checked

- A person using it; how the lamp looks on another monitor; Blender versions other than 5.3.0; Eevee against Cycles.
- X_ITE on a real GPU, or on a quiet machine: every recording was made with software GL on a loaded one (finding 6).
- `PlaneSensor` with `axisRotation` other than the identity, a scaled Transform above the sensor (the judge's camera axes assume
  none), `enabled` false, a limit on y only (a line along y), or `offset` set in the file. The plane case (both axes free, or
  both limited) is run only in a unit test, not against X_ITE.
- Play's `PlaneSensor` drag, which still meets the ray with the plane through the press point, is not the code the judge
  ran (finding 9). The `TouchSensor` outputs are replayed from the trace, not compared.
- `ScalarChaser`, `PositionChaser` and `PositionChaser2D` keep the old sum-of-eased-jumps model (finding 4); `CarChase` is
  judged, at the margins above, `PositionChaser2D` is still not.

## Findings for Loom

1. **X_ITE slides a PlaneSensor along a line, by the picture on the screen, when one axis is limited.** With
   `minPosition.y == maxPosition.y` (or x) X_ITE does not intersect a plane: it projects the line to the window, takes the
   point of that picture nearest the pointer, and un-projects it (`PlaneSensor.js`, `getLineTrackPoint`). Evidence: the
   simulator does the same from the ray and the camera's axes and agrees on 68 `translation_changed` and 73
   `trackPoint_changed` events (worst gap 0.000001); P1, P4 and J5 are rejected. The pixel size cancels, so the simulator
   needs the camera's right and up axes and nothing else.
2. **X_ITE's `PlaneSensor.track` discards a rotation.** It calls `axisRotation.multVecRot(translation)` and does not use the
   result, so `translation_changed` is in the rotated frame, not rotated back. Read from the source only (X_ITE 16.7.1); this demo's
   `axisRotation` is the identity, so it is neither run nor judged. The simulator copies it.
3. **The simulator's old ColorChaser and OrientationChaser were wrong, not merely approximate.** The ColorChaser summed jumps
   in RGB; X_ITE chases in HSV with the hue in radians (before the port, `GlowChase` was 0.136 away, past the 0.08 limit). The
   OrientationChaser ran one ramp at a time; a destination that changes every pointer step (the moon behind a turning globe)
   left it 1.05 rad away. Both are now X_ITE's own 60-slot scheme; the colour agrees to 0.000000 and the moon to 0.002 to 0.008
   rad on six recordings. The probe's single-jump `ChaseTurn` could not show this.
4. **The scalar and position chasers still disagree with X_ITE in principle, and only the tolerance hides it.** They sum
   eased jumps at the moment the destination moved; X_ITE spreads a frame's change over the frame, so the two part company at
   coarse frames. `test_a_chaser_arrives_exactly_after_its_duration` pins the old model (half-way at half time after one
   0.25 s step; by my reading of `X3DChaserNode.js` X_ITE would not give that, and a port would fail it; I did not try), so
   I left them. `CarChase`'s worst gap over the seven recordings: 0.013 to 0.072
   of a 0.08 limit. `PositionChaser2D` (the orrery demo) shares that model. Decision for the owner: port them and change that
   test's expectation deliberately.
5. **The replay must step followers at X_ITE's frames, and a page's animation-frame stamps are not those.** They include the
   moments the pointer moved. Stepping there moved `GlowChase` 0.095 to 0.131 off on three recordings (mutant J6); the judge now
   steps the simulator when a time-driven node spoke, or the viewer was reported (`stepped` in `judge`). Every other judged
   world still agrees (`tests/test_behaviour_sim.py`). This changes the shared judge: the other two demo pull requests meet it.
6. **A recording made at about one frame a second is not a fair one.** With the chaser's duration equal to the frame gap
   (steps >= 60 resets X_ITE's buffer to the destination) a few milliseconds of difference in when the chaser started flips
   between two branches (my reading of the trace: X_ITE's output went straight to the destination after a gap of 0.79 s against
   a duration of 0.8 s, and the simulator's did not; not proven): recording 4 gave `MoonChase` 0.097 with 83 events on each
   side. Recordings at 7 to 10 frames a second (the loaded machine here) agree. Suggest `record` refuse a trace whose frame gaps approach a follower's duration.
   Not done.
7. **X_ITE's first motion after a press repeats values by rounding.** `trackPoint_changed` is always sent (the press and the
   motion find it by two formulas that differ in the last bits) and `translation_changed` is sent whenever the offset is not
   zero (`(end + offset) - start` is not the offset in the last bit). The simulator sends exactly those on that first motion
   and only what changed after. Evidence: 68 against 68 events across two grabs, the second with a non-zero offset; P5 is
   rejected. A guard written as exact equality in X_ITE is thus not an "only what changed" guarantee.
8. **The importer names a DEF'd Transform's empty `Name.001` and gives the first mesh the plain name** (`Knob` is the cap mesh,
   `Knob.001` the empty). The behaviour resolver binds the empty (right), but anything that looks up `objects["Knob"]` gets the
   mesh: the act finds objects by `x3d_def`. The importer notes every event node and ROUTE as "not imported" (the graph carries
   them) and keeps no play-once `TimeSensor` start; nothing the demo needs was dropped.
9. **Play's PlaneSensor drag is not the judged code.** `Player.drag` meets the ray with the plane through the press point and
   hands the simulator a point; the judge runs the ray path. At this camera the knob's picture stayed within 6.1 px of the
   pointer (about 0.08 m), so it follows well here; I expect it to drift under a steeper camera (not tried). Play was not changed (the spec
   allows it only if the fader does not move); a follow-up is to pass the ray and the camera's axes from `_eye`.
10. **Play never sends `hitPoint_changed`**, so the `TouchSensor`s' ROUTEs (three empty Transforms) never move in the window.
    The demo needs them only for the recorder.
11. **The eye test's generic drag step grabs every mesh of every sensed Transform** (30 drags for this world) and runs before the act, so the act starts with the knob at its left limit and the lamp already teal; the act
    measures the change and the peak, not absolute values. One drag per sensor would be quicker and leave the world at rest.
12. **Blender's studio lighting hides an emissive lamp.** The sweep reads only with Material Preview, scene lights and scene
    world on; the act sets them.
