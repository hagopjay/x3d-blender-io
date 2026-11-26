# Orrery: a clockwork sky

A brass orrery on a dark stage: a sun, four planets on arms (Terra and Gale each with a moon), every arm turned by its
own looping clock, and a star chart on the back wall that ticks along with the year. Click the sun, Venus or Terra and
the camera swoops to its post; pull the lever (top left, on a post) and every clock stops.

World: `orrery.x3d`, written by `build.py` (`python build.py`). X3D 4.0, profile Immersive, 41 nodes and 42 ROUTEs in
the graph. Only the sun, Venus and Terra have a TouchSensor (and a flight): the recorder clicks every sensor in the
world (`click_plan` in `demo.json`), so there are no chains it cannot reach.

## Play it in Blender

File > Import > X3D with "Behaviour graph" on, press Play in the X3D Behaviour editor (the node editor lights up as
clocks and interpolators send). Switch the 3D view to Material Preview to see the star chart (Solid mode draws no
textures). Click the sun, Venus or Terra: the camera flies to its post. Planets move 2 to 3 units a second, so pull the
lever first and click a planet that holds still; pull it again to let go. Esc stops and puts everything back.

## The graph

| Part | Nodes |
|---|---|
| orbits | per arm a looping TimeSensor (`EmberClock` 4 s, `VenusClock` 7 s, `TerraClock` 12 s, `GaleClock` 20 s; moons `LunaClock` 5 s, `PebbleClock` 9 s) → OrientationInterpolator (`EmberSpin` ...: 8 keys, one turn about Y) → `rotation` of the arm Transform (`EmberArm` ...) |
| flights | per body (Sun, Venus, Terra): TouchSensor `XTouch`.`isActive` → TimeTrigger `XGo` → `triggerTime` → 3 s TimeSensor `XFlight`.`startTime` → PositionInterpolator `XPath` (3 keys: home, a lift above the middle, the post) and OrientationInterpolator `XTurn` → Viewpoint `View`.`position` and `.orientation` |
| star chart | `YearClock` (12 s) → PositionInterpolator2D `ChartPan` (a ratchet: 4 ticks of 1.4 chart widths, 3 s apart; `YearClock` 12 s) → PositionChaser2D `ChartSmooth` (`duration 1.5`) → TextureTransform `ChartMap`.`translation` (on the chart's Appearance; the material `ChartPaint` has a DEF, and two PixelTextures: base and emissive) |
| lever | TouchSensor `LeverTouch` → BooleanFilter `LeverPull` → BooleanToggle `Running` (`toggle="true"`, so the first pull sends false) → `enabled` of the seven orbit and year clocks |

## Checked

| What | Instrument | Result |
|---|---|---|
| Judge | X_ITE 16.7.1, headless Chromium (SwiftShader, 13012 frames over 162 s), one real click on each of `LeverTouch` (210, 120), `TerraTouch` (540, 330), `VenusTouch` (690, 300), `SunTouch` (480, 30), `LeverTouch` (90, 60), each hunted with the pointer sweep, 3.5 s apart, then 20 s; `tools/behaviour_demo.py judge orrery` | 29 of 29 streams agree, every one with X_ITE events (835 for the clocks and chart; 54 to 61 per flight; 2 for the lever); worst gap 0.000005 on exact streams (tolerance 0.002) and 0.027696 on `ChartSmooth` (0.08), which is the first recorded frame (the chaser was mid-ramp when recording began); elsewhere 0.000001 |
| `judges` | same | `PositionInterpolator2D` (`ChartPan`, 835 X_ITE events) and `PositionChaser2D` (`ChartSmooth`, 835) are judged |
| The test catches mistakes | `tests/test_behaviour_sim.py::DemoJudgeTests`, wrong simulators by hand (table below) | all seven rejected (table below) |
| Play and graph code | `tests/test_behaviour_demo_orrery_bpy.py`, 10 tests, Blender 5.3.0; ten wrong versions by hand (table below) | all ten rejected |
| Live window | `tools/behaviour_demo.py show orrery`, Blender 5.3.0, 1600 x 1000, real clicks through the event queue; the act (`act.py`) | Host-eyes pass; `act_ok` true; `not_applied` and `not_simulated` empty; restored after Esc |
| Full suite | Blender 5.3.0 `-b`, `.github/scripts/run_tests_in_blender.py` | 1115 tests, 49 skipped by the suite itself; one failure, `test_import_extreme_scale_bpy.test_inverted_helper`, the known macOS arm64 one; none new |

The act (every object found by DEF through the graph): runs the orrery with a screenshot every 1.5 s (all six arms
turned 44 to 175 degrees, the chart's Mapping node moved through 5 positions), checks the camera flew to the sun's post
(the last key of `SunPath`, within 0.05), pulls the lever (clocks stop: every arm moved 0.00 degrees through both
flights), clicks Terra, then Venus, with real clicks (camera at each planet's post within 0.05 each time), pulls the
lever again (every arm turns again). I looked at the screenshots: the star chart shows stars in Material Preview and
moves between runs; the camera ends in front of each planet with the sun, arms and chart in frame; the lever's post
stands at the back left.

## The simulator change

`PositionChaser2D` now runs X_ITE's own algorithm (`_BufferChaser` in `source/behaviour_sim.py`): 60 buffers
`duration / 60` apart, shifted each frame by the time that passed, skipped frames filled by blending the destination
into the old value, step responses of half a cosine summed. The old clean-ramp chaser (still used by the other
chasers) agreed with X_ITE to 0.07 on a quiet recording and failed (worst gap 0.196, tolerance 0.08) on the click-plan
recording, where the pointer sweeps slow X_ITE's frames to 0.25 to 0.8 s: X_ITE's buffer fill over a long frame is not
a ramp. With the port the worst gap is 0.000001 except the first recorded frame.

### Mutants

Simulator (`source/behaviour_sim.py`, restored after each), by hand, `judge orrery`:

| Wrong version | Result (worst gap on `ChartSmooth`; tolerance 0.08) |
|---|---|
| PositionInterpolator2D sends (y, x) | `ChartPan`, `ChartSmooth` rejected (2.1) |
| PositionInterpolator2D eases its fraction (`t * t`) | `ChartPan`, `ChartSmooth` rejected (0.123) |
| PositionChaser2D takes 1.3 times its `duration` (step time and response) | `ChartSmooth` rejected (0.331) |
| PositionChaser2D step response linear, not half a cosine | `ChartSmooth` rejected (0.193) |
| PositionChaser2D sends its destination (no smoothing) | `ChartSmooth` rejected (1.4) |
| PositionChaser2D fills skipped frames from the wrong buffer | `ChartSmooth` rejected (0.197) |
| PositionChaser2D restarts its clock on every destination event | `ChartSmooth` rejected (0.339) |

With the chart's first ticks (0.6 of a chart width) the linear-response mutant got through (0.0606); with ticks of 1.4
and one every 3 s all seven are rejected. Changing only the buffer
spacing by 1.3 (not the response) is not rejected (0.0268, the same as the honest gap): it is nearly the same chaser.

Play and graph (`source/behaviour_play.py`, `behaviour_graph.py`, `behaviour_nodes.py`, restored after each), by hand,
`test_behaviour_demo_orrery_bpy`:

| Wrong version | Tests that fail |
|---|---|
| Location sent as (t, s) | 3 |
| Stop leaves the Mapping nodes behind | 5 |
| rotation sent with the wrong sign | lands |
| only the first Image Texture gets the Mapping node | pans |
| an existing Mapping node is not put back | existing Mapping |
| the authored transform is not taken out (no inverse of the initial one) | authored transform |
| an existing Mapping node applied before the change, not after | existing Mapping |
| the link in front of an Image Texture is not put back | texture-coordinate link |
| the graph never finds the Appearance's material | 8 of 10 |
| the resolver does not know a texture target | 8 of 10 |

## Shared files this demo touched

- `source/behaviour_graph.py`: `BINDING_OF["TextureTransform"] = "texture"` (its own line); a TextureTransform target
  is bound at parse time through the DEF of the material in its Appearance, its authored values are kept, and an
  Appearance whose material has no DEF is named in the diagnostics and not guessed (the ROUTEs are left out, as for any
  node that cannot be bound).
- `source/behaviour_nodes.py`: `MATERIAL_KINDS = ("material", "texture")`; the resolver finds the material by its
  recorded `x3d_def`; `import_graph` records the authored TextureTransform on the material (`x3d_texture_transform`).
- `source/behaviour_play.py`: `Player._texture`, `_mapping_for`, `_undo_textures`: TextureTransform `translation`,
  `rotation`, `scale` onto a Mapping node made on the first event and removed on Stop. The Mapping node holds only the
  change from the authored transform (new composed with the inverse of the initial one), so a value equal to the
  authored one changes nothing; one Mapping node feeds every unlinked Image Texture of the material (a material shared
  by two objects is one material); a link that was in front of an Image Texture is kept in front of the Mapping node and
  put back; a Mapping node that is already there is driven and restored.
- `source/behaviour_sim.py`: `_BufferChaser` for PositionChaser2D only.
- `tools/behaviour_sim_judge.cjs` and `tools/behaviour_demo.py`: `click_plan` in `demo.json` (a list of pointing-sensor
  DEFs), passed to the recorder as `--click-plan FILE` after the positional arguments (separate from `--keys`); the
  recorder sweeps the pointer until that sensor reports `isOver`, clicks it, waits 3.5 s, and does nothing different
  when there is no plan; `check` rejects a name that is not a pointing sensor of the world.
- `tests/test_behaviour_sim.py`: `PositionChaser2D` and `PositionInterpolator2D` left the `unjudged` list.

Not touched: the importer, the exporter, `ir.py`, `validate.py`, `mapping/*`, the version.

## Not checked

- How the scene looks to a person beyond the screenshots described above; Material Preview and Solid were seen, not a
  render (EEVEE or Cycles).
- The act pulls the lever through `Player.press` and `release`, not with the pointer (from a planet's post the lever
  is behind the camera); the recorder does click it, in X_ITE.
- `TextureTransform.rotation`, `scale` and `center` are tested in Blender (rotation and scale reach the Mapping node,
  `center` is reported as not shown) but never judged: the orrery sends only `translation`. A composed transform with
  shear, which a Mapping node cannot show, is reported as not applied (by reading the code; no test).
- A non-zero authored TextureTransform is tested with a small world in Blender (the Mapping node stays identity until
  the value changes); not against X_ITE, and not visually.
- The `click_plan` code in the recorder has no test of its own beyond the recording that used it; a plan that names a
  sensor that never reports `isOver` is recorded as `at: null` and skipped.
- No other Blender version, no other platform.

## Findings for Loom

1. **The recorder clicked one spot, so a world could have one click chain.** `run_judge` and `DemoJudgeTests` need an
   X_ITE event on every compared stream. Evidence: the first recording (the pointer found Gale first) left 18 of 37
   streams empty. Answer: `click_plan` (one hunted click per named sensor).
2. **A ROUTE into a TextureTransform never reached Play.** `behaviour_graph.BINDING_OF` had no entry for it and the
   importer neither makes a Mapping node (it bakes the transform into the UVs) nor records the node's DEF. Evidence:
   import log "TextureTransform 'ChartMap' is the end of a ROUTE but is neither a Blender object nor a top-level
   node that can be carried; its ROUTEs were left out" (Blender 5.3.0). Now bound through the DEF of the material in
   its Appearance. Whether the importer should keep a Mapping node and the TextureTransform's DEF is its owner's call.
3. **That ROUTE does not survive export.** `emit_x3d40.py`: `def_of_target` has no texture branch, and
   `_texture_transform_xml` writes no DEF; and because the transform is baked into the UVs, writing it again would
   apply it twice. On export the ROUTE is left out and named in the file's head (`test_what_export_does_with_the_route_is_named_not_silent`).
4. **The importer drops a TextureTransform's translation and center.** It bakes `uv @ matrix` (`translateTexTransform`)
   but a 3-vector times a 4 x 4 matrix in Blender ignores the translation column: `Vector((0.5, 0.25, 0)) @
   Matrix.Translation((1, 2, 0))` gives `(0.5, 0.25, 0)` (Blender 5.3.0). Rotation and scale are kept. So a world's
   authored translation is lost on import, which Play's Mapping node (authored-relative) does not repair.
5. **X_ITE's chaser is a buffer, not a ramp, and a slow frame shows it.** Evidence: the clean-ramp simulator was 0.157
   to 0.196 off on frames 0.25 to 0.8 s long (pointer sweeps under SwiftShader), the buffer port 0.000001. Any follower
   judged on a recording with stalls has this problem.
6. **Moving targets.** Planets move 2 to 3 units a second: the recorder pauses them with the lever before it hunts
   them, and a person has to do the same. The sun's crown (a cone higher than any planet) is what a plain scan finds
   first.
7. **A probe whose steps are too small lets a wrong chaser pass.** With ticks of 0.6 of a chart width a linear step
   response had a worst gap of 0.0606, inside the follower tolerance 0.08; with ticks of 1.4 it is 0.193 and rejected,
   while the honest simulator stays at 0.000001. The tolerance was not changed: the probe was. Any follower probe needs
   steps large compared with the tolerance divided by the shape's difference (about 10 percent of a step).
8. **X3D cannot start a flight from where the camera is.** Every flight runs from the home pose through a lift to the
   post (key 0 is the home pose), so a click on a second planet starts with the camera jumping back home (by reading
   the keys; not filmed).
