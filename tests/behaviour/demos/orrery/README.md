# Orrery: a clockwork sky

A brass orrery on a dark stage: a sun, four planets on arms (Terra and Gale each with a moon), every arm turned by its
own looping clock, and a star chart on the back wall that ticks along with the year. Click the sun or a planet and the
camera swoops to its post; pull the lever and every clock stops.

World: `orrery.x3d`, written by `build.py` (`python build.py`). X3D 4.0, profile Immersive, 51 nodes and 54 ROUTEs in
the graph.

## Play it in Blender

File > Import > X3D with "Behaviour graph" on, press Play in the X3D Behaviour editor (the node editor lights up as
clocks and interpolators send). Switch the 3D view to Material Preview to see the star chart (Solid mode draws no
textures). Click the sun or a planet: the camera flies to its post. Planets move 2 to 3 units a second, so pull the
lever (the red handle at the front left) first and click a planet that holds still; pull it again to let go. Esc stops
and puts everything back.

## The graph

| Part | Nodes |
|---|---|
| orbits | per arm a looping TimeSensor (`EmberClock` 4 s, `VenusClock` 7 s, `TerraClock` 12 s, `GaleClock` 20 s; moons `LunaClock` 5 s, `PebbleClock` 9 s) → OrientationInterpolator (`EmberSpin` ...: 8 keys, one turn about Y) → `rotation` of the arm Transform (`EmberArm` ...) |
| flights | per body (Sun, Ember, Venus, Terra, Gale): TouchSensor `XTouch`.`isActive` → TimeTrigger `XGo` → `triggerTime` → 3 s TimeSensor `XFlight`.`startTime` → PositionInterpolator `XPath` (3 keys: home, a lift above the middle, the post) and OrientationInterpolator `XTurn` → Viewpoint `View`.`position` and `.orientation` |
| star chart | `YearClock` (20 s) → PositionInterpolator2D `ChartPan` (a ratchet: 4 ticks of 0.6 of the chart, 2 s apart) → PositionChaser2D `ChartSmooth` (`duration 1.5`) → TextureTransform `ChartMap`.`translation` (on the chart's Appearance; PixelTexture star field) |
| lever | TouchSensor `LeverTouch` → BooleanFilter `LeverPull` → BooleanToggle `Running` (`toggle="true"`, so the first pull sends false) → `enabled` of the seven orbit and year clocks |

## Checked

| What | Instrument | Result |
|---|---|---|
| Judge | X_ITE 16.7.1, headless Chromium (SwiftShader, 946 frames over 63 s), 2 requested clicks on the first pointing sensor it found (the sun's crown at 480, 120); `tools/behaviour_demo.py judge orrery` | 37 of 37 streams agree: 19 with X_ITE events (worst gap: 0.000003 exact streams, 0.072965 `ChartSmooth` against the follower tolerance 0.08) and 18 idle, silent in X_ITE and the simulator |
| `judges` | same | `PositionInterpolator2D` (`ChartPan`, 455 X_ITE events) and `PositionChaser2D` (`ChartSmooth`, 455) are judged; no simulator code was changed |
| The test catches mistakes | `tests/test_behaviour_sim.py::DemoJudgeTests`, five wrong simulators, by hand (table below) | all five rejected |
| Play and graph code | `tests/test_behaviour_demo_orrery_bpy.py`, 6 tests, Blender 5.3.0; seven wrong versions by hand (table below) | all seven rejected |
| Live window | `tools/behaviour_demo.py show orrery`, Blender 5.3.0, 1600 x 1000, real clicks through the event queue; the act (`act.py`) | Host-eyes pass; `act_ok` true; `not_applied` and `not_simulated` empty; restored after Esc (see below) |
| Full suite | Blender 5.3.0 `-b`, `.github/scripts/run_tests_in_blender.py` | 1111 tests, 49 skipped by the suite itself; one failure, `test_import_extreme_scale_bpy.test_inverted_helper`, the known macOS arm64 one; none new |

The act (every object found by DEF through the graph): runs the orrery with a screenshot every 1.5 s (all six arms
turned 44 to 176 degrees in the run, the chart's Mapping node moved through 4 positions), checks the camera flew to the
sun's post (the last key of `SunPath`, within 0.05), pulls the lever (clocks stop: every arm moved 0.00 degrees through
both flights), clicks Terra, then Venus, with real clicks (camera at each planet's post within 0.05 each time), pulls
the lever again (every arm turns again). I looked at the screenshots: the star chart shows stars in Material Preview
and moves between runs; the camera ends in front of each planet with the sun, arms and chart in frame; the planets sit
on their arms.

### Idle streams (not fired by the recording)

The recorder clicks one spot, so only the sun's chain fires in X_ITE. The other 18 sources (the flights of Ember,
Venus, Terra and Gale: 4 each; the lever's `LeverPull.inputTrue` and `Running.toggle_changed`) are listed under `idle`
in `demo.json`. The judge requires them to be silent in X_ITE and in the simulator; the act proves the chains in the
live window. They were not compared against X_ITE: those paths (a second flight, the clocks being disabled and
enabled again) are only checked by the act, in Blender. **`idle` is a new, optional key of `demo.json`** (see "Shared
files").

### Mutants

Simulator (`source/behaviour_sim.py`, restored after each), by hand, `judge orrery`:

| Wrong version | Stream(s) the judge rejects (worst gap) |
|---|---|
| PositionInterpolator2D sends (y, x) | `ChartPan` (0.900000), `ChartSmooth` (0.902516) |
| PositionInterpolator2D eases its fraction (`t * t`) | `ChartPan` (0.149816) |
| PositionChaser2D takes 1.3 times its `duration` | `ChartSmooth` (0.110390) |
| PositionChaser2D ramps linearly, not half a cosine | `ChartSmooth` (0.102739) |
| PositionChaser2D sends its destination (no smoothing) | `ChartSmooth` (0.587970) |

Play and graph (`source/behaviour_play.py`, `behaviour_graph.py`, `behaviour_nodes.py`, restored after each), by hand,
`test_behaviour_demo_orrery_bpy`:

| Wrong version | Tests that fail |
|---|---|
| translation written to the Scale socket | pans / lands / existing Mapping (3) |
| Stop leaves the Mapping nodes behind | pans / lands / existing Mapping (3) |
| rotation sent with the wrong sign | lands |
| only the first Image Texture gets the Mapping node | pans |
| an existing Mapping node is not put back | existing Mapping |
| the graph never finds the Appearance's material | 5 of 6 |
| the resolver does not know a texture target | 5 of 6 |

The first version of the chart (a gentle triangle wave, 0.35 of the chart in 5 s) let three chaser mutants through: the
simulator with 1.3 times the duration, a linear ramp and no smoothing at all all stayed inside the follower tolerance
(worst gaps 0.008, 0.013, 0.040 against 0.08), because the input never moved fast enough for the chaser's shape to
show. The chart ticks in jumps of 0.6 for that reason; see Finding 4.

## Shared files this demo touched

- `source/behaviour_graph.py`: `BINDING_OF["TextureTransform"] = "texture"` (its own line) and, at parse time, a
  TextureTransform target is bound through the DEF of the material in its Appearance (`_appearance_material_def`).
- `source/behaviour_nodes.py`: `MATERIAL_KINDS = ("material", "texture")`: both bindings name a Blender material; the
  resolver finds the material by its recorded `x3d_def`.
- `source/behaviour_play.py`: `Player._texture`, `_mapping_for`, `_undo_textures`: TextureTransform `translation`,
  `rotation`, `scale` onto a Mapping node, made on the first event and removed on Stop. The importer makes none; Play
  makes a Texture Coordinate (UV) → Mapping → Image Texture chain, one Mapping node for every unlinked Image Texture,
  or drives (and restores) a Mapping node that is already there.
- `tools/behaviour_demo.py` and `DemoJudgeTests`: the optional `idle` list (Finding 1). This was not in the spec;
  it is a separate commit, so it can be dropped.
- `tests/test_behaviour_sim.py`: `PositionChaser2D` and `PositionInterpolator2D` left the `unjudged` list.

Not touched: the importer, exporter, `ir.py`, `validate.py`, `mapping/*`, the version.

## Not checked

- How the scene looks to a person beyond the screenshots described above; Solid and Material Preview were seen, not
  rendered (EEVEE or Cycles).
- The flights, the lever and the clocks being disabled and enabled again were not compared with X_ITE (idle streams).
- `TextureTransform.rotation`, `scale` and `center` are tested in Blender (rotation and scale reach the Mapping node,
  `center` is reported as not shown) but never judged: the orrery sends only `translation`. The rotation sign follows
  the exporter's reading of a Mapping node (Rotation Z = rotation), not the importer's own `rot * -1` on UVs.
- A transform the file gives the TextureTransform at load: the importer has already baked it into the UVs, and Play's
  Mapping node starts at identity and takes the event's value, so a non-zero initial value would be applied twice
  while playing (by reading the code; the orrery starts at 0 0).
- TouchSensor `hitPoint_changed` on hover (X_ITE sends it as the pointer moves over a body, the simulator at the press
  only) was not measured; it is why a "fly to wherever you click" design (hit point into a chaser) was not used.
- The lever is pulled through `Player.press` and `release`, not with the pointer: from a planet's post it is behind the
  camera.
- The second of the recorder's two clicks did not land (one `SunTouch` press in the trace): by then the camera had
  started flying. So a second flight was not recorded.
- No other Blender version, no other platform.

## Findings for Loom

1. **The judge needs a recording that fires every stream, which allows one click chain per world.** The recorder
   clicks one spot and `run_judge` and `DemoJudgeTests` required an X_ITE event on every non-pointing ROUTE source.
   A world with a flight per planet and a lever has one chain that fires and 18 sources that cannot. Evidence: the
   first recording (a far planet, Gale, was the first sensor found) left 18 of 37 streams empty. Answer here: an optional
   `idle` list in `demo.json`, silent in both X_ITE and the simulator, proved by the act in the window.
2. **A ROUTE into a TextureTransform never reached Play.** `behaviour_graph.BINDING_OF` had no entry for it and the
   importer neither makes a Mapping node (it bakes the transform into the UVs) nor records the node's DEF. Evidence:
   import log "TextureTransform 'ChartMap' is the end of a ROUTE but is neither a Blender object nor a top-level
   node that can be carried; its ROUTEs were left out" (Blender 5.3.0). Now bound to the material of its Appearance,
   so the material needs a DEF.
3. **That ROUTE does not survive export.** `emit_x3d40.py` has no DEF for a TextureTransform and writes one from a
   Mapping node without a DEF, so on export the ROUTE is left out and named in the file's head ("Target 'ChartMap'
   (TextureTransform) is not in the exported file; its ROUTEs were left out"); `test_what_export_does_with_the_route_is_named_not_silent`
   pins that. A real round trip needs the exporter to write the TextureTransform with the DEF (and to stop baking
   the UVs twice).
4. **The follower tolerance cannot see a chaser's shape on gentle input.** Evidence: Mutants, above: with a chart
   that moves about 0.035 of its width a second, a chaser 1.3 times too slow, a linear one and none at all all passed (gaps 0.008, 0.013,
   0.040 against 0.08). With jumps of 0.6 they fail (0.110, 0.103, 0.588), but the honest simulator is at 0.073, close
   to the limit: X_ITE's step comes from the frame rate and the headless recording ran at about 15 frames a second
   (946 frames in 63 s). A second recording might cross 0.08 for no fault of the simulator.
5. **The recorder's scan finds a moving planet at an unpredictable moment.** The first recording clicked Gale, the next
   would have clicked another, and the click lands 0.1 s after the scan found it, by when the planet has moved
   (they move 2 to 3 units a second). The sun's crown (a cone on the sun's Transform, higher than any planet in the
   view) is what the scan finds first, every time it was checked (480, 120 in three recordings). A person has the same problem:
   hence the lever.
6. **X3D cannot start a flight from where the camera is.** Every flight here runs from the home pose through a
   lift to the post (key 0 is the home pose), so a click on a second planet starts with the camera jumping back home
   (by reading the keys; not filmed). Without a Script, the alternatives are a viewpoint per body bound by `set_bind`
   (which unbinds on release of the sensor's `isActive`), or one chaser fed a destination (which needs a number a
   click cannot send).
