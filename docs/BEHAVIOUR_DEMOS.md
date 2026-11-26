# Behaviour demos: specification (26 Nov 2026)

Three demo worlds that show the behaviour graph at its best: things you drag, type into and click, playing in a real
Blender window, each one judged event for event against X_ITE 16.7.1. Each demo is built in its own folder by its own
pull request, so the three can be built in parallel. `hello-switch` is the worked template.

| Demo | What you do | What it proves first (against X_ITE) |
|---|---|---|
| [`workbench`](#1-workbench-drag-turn-spin) | drag a fader, turn a knob, spin a globe | PlaneSensor drags; ColorChaser |
| [`piano`](#2-piano-type-and-it-plays) | type on the keyboard; Enter stamps the line | KeySensor and StringSensor from real keys |
| [`orrery`](#3-orrery-a-clockwork-sky) | watch it run; click a planet to fly there | PositionInterpolator2D; PositionChaser2D |

## The shared contract (every demo)

### Files: a demo owns its folder

```
tests/behaviour/demos/NAME/
  NAME.x3d        the world (X3D 4.0 XML, profile Immersive, components declared; hand-written or built by build.py)
  build.py        optional: writes NAME.x3d (and drags.json / keys.json), like tools/behaviour_probe.py
  demo.json       the contract with the tools (below)
  x_ite.json      X_ITE's trace, written by `tools/behaviour_demo.py record NAME`; never edited by hand
  act.py          the live-window act: act(rig, ctx), a generator (see hello-switch/act.py)
  README.md       what it shows, how to play it, what was checked, what was not, findings for Loom
  drags.json / keys.json   input plans for the recorder, when the demo needs them
```

`demo.json`: `title`, `streams` (ROUTE sources the judge compares; all must agree), `clicks` and `seconds` (what
the recorder does), `drags` or `keys` (an input plan file, or null), `judges` (node types this demo is the first to
judge; each must send on a ROUTE in the world).

### Tools

```
python tools/behaviour_demo.py check  NAME     # folder complete, world parses, sources counted
python tools/behaviour_demo.py record NAME     # X_ITE 16.7.1, headless Chromium (needs X_ITE_DIR, NODE_PATH)
python tools/behaviour_demo.py judge  NAME     # every stream, worst gap, PASS / FAIL against demo.json
python tools/behaviour_demo.py show   NAME --out DIR    # a real Blender 5.3 window; DIR/host-eyes.json
```

`tests/test_behaviour_sim.py::DemoJudgeTests` judges every demo folder that has a trace, so adding a demo adds its
test with no shared list to edit. `tools/behaviour_eyetest.py` finds demo worlds by name and runs `act.py` after its
standard steps (import, editor, play, click, drags, flights, stop, restore). The act calls only `rig.mouse`,
`rig.key`, `rig.type_key`, `rig.shot`, `rig.screen_point`, `rig.note`; it reports `rig.note(name, "act_ok", bool)`,
and a false `act_ok` fails the Host-eyes witness.

### Definition of done

1. `check`, `record`, `judge` pass: every compared stream agrees with X_ITE within the judge's tolerances (0.002
   exact, 0.08 followers) and each has at least one X_ITE event.
2. Each node type in `judges` is really exercised: the world sends on its ROUTEs, and a deliberately wrong version
   of any simulator code you add or change is rejected by the judge (at least three mutants per new machine or
   replay path, run by hand and listed in the README with their failing streams; restore the code after).
3. `show` passes: the Host-eyes witness is `pass`, `act_ok` is true, `not_applied` is empty (every ROUTE shows on
   Blender data), Stop puts everything back. Look at the screenshots before claiming anything about the look.
4. The full suite in Blender 5.3 (`.github/scripts/run_tests_in_blender.py`, `-b`) has no new failure.
   (`test_import_extreme_scale_bpy.test_inverted_helper` fails on macOS arm64 on main too; it is not yours.)
5. README.md: what the demo shows, how to play it in Blender (Import X3D with the behaviour graph, Play), the
   judge table (streams, agree, worst gap), mutants, what was not checked, and **Findings for Loom** (numbered,
   each with its evidence). Do not edit x3d.loom: findings are folded back centrally (Loom numbering collides
   when several pull requests number in parallel).
6. One pull request from the hagsmac fork to hagopjay/x3d-blender-io `main`, after a leak sweep (no home
   paths, emails, session links, keys).

### Rules

- Stay in your demo folder, plus only the shared files your demo's section names. Do not edit
  `docs/BEHAVIOUR_GRAPH.md` (the README carries your text), `import_x3d.py`, `extract.py`, `emit_x3d40.py`,
  `ir.py`, `validate.py`, `matrix_safety.py`, `mapping/*`, `tools/io_sync/*`, or the add-on version. If the
  importer drops something your demo needs, say so in the README; do not work round it in the importer.
- Add Blender tests for any Play change in a new file `tests/test_behaviour_demo_NAME_bpy.py`, not in the shared
  test files. The one shared line you may edit is the `unjudged` list in
  `tests/test_behaviour_sim.py::test_the_probe_covers_what_the_simulator_runs` (remove the types your demo judges).
- Never skip, disable or loosen a test to get green. No force-push. Nothing goes to an outside project.
- Every number names its instrument. Say plainly what was not checked.

## 1. Workbench: drag, turn, spin

A warm workshop bench under one lamp. Three toys, each a drag sensor, each with something that follows it.

| Toy | Sensor | What follows |
|---|---|---|
| **Fader**: a knob on a 2 m track | PlaneSensor, `minPosition -1 0`, `maxPosition 1 0` (x only) | the knob (`translation_changed`); a toy car on a parallel rail, through a PositionChaser (`duration 0.8`), so it lags and catches up |
| **Dial**: a big brass knob | CylinderSensor (`autoOffset true`) | the dial (`rotation_changed`); `isActive` true starts a colour sweep: BooleanFilter, TimeTrigger, a 2 s TimeSensor, a ColorInterpolator (amber, rose, teal), a **ColorChaser** (`duration 0.6`) into the lamp shade's `emissiveColor` and the bench light's `color` |
| **Globe** | SphereSensor | the globe (`rotation_changed`); a moon on an arm, through an OrientationChaser, trailing the globe's turn |

Recorder: a drags file (`drags.json`) with one drag per toy (the fader end to end and back past both limits; the
dial three quarters of a turn; the globe a diagonal sweep), TouchSensors beside each drag sensor for the press point
(as in `probe-drag`). `clicks` 0.

New code you may need, and the only shared files you may touch:
- `tools/behaviour_sim_judge.py`: replay PlaneSensor drags from the recorded pointer in `_drag_actions` (the
  Cylinder and Sphere paths are the model; X_ITE's PlaneSensor: `X_ITE/src/x_ite/Components/PointingDeviceSensor/PlaneSensor.js`).
- `source/behaviour_sim.py`: the PlaneSensor drag and the ColorChaser, only where the judge shows a disagreement.
- `source/behaviour_play.py`: only if a PlaneSensor drag does not already move the fader in the window.

Judges: `PlaneSensor`, `ColorChaser`. The act drags each toy through the event queue (screenshot at mid-drag),
then checks the car moved after the fader, the lamp changed colour, and the moon turned.

Wow beats for the README screenshots: the car chasing the fader; the lamp sweeping amber to teal as the dial turns;
the moon swinging after the globe.

## 2. Piano: type and it plays

A grand piano seen from above the keyboard, a music stand with a sheet, and a line of 3D text above the keys.
Typing in the Blender window plays it.

| Input | Sensor | What happens |
|---|---|---|
| any key down | KeySensor `isActive` | a hammer strikes: BooleanFilter, TimeTrigger, a 0.25 s TimeSensor, a PositionInterpolator dipping the hammer bar; the stand lamp flashes (ScalarInterpolator into `intensity` or `transparency`) |
| Shift / Ctrl / Alt | KeySensor `shiftKey`, `controlKey`, `altKey` | the three pedals light while held (`visible` of a glow on each) |
| arrows, F-keys | KeySensor `actionKeyPress` | an IntegerTrigger or IntegerSequencer chain you choose; show it on Blender data |
| typing | StringSensor `enteredText` | the line above the keys shows what is typed so far |
| Enter | StringSensor `finalText` | the line is stamped onto the sheet (a second text); Backspace deletes when `deletionAllowed` |

X3D cannot route "the A key" to "the A string" without a Script; say so in the README as a finding, and keep the
demo honest: one hammer for every key, pedals for modifiers, text for what was typed.

Recorder: a keys file (`keys.json`), e.g. `{"keys": [{"type": "Hello"}, {"press": "Shift+A"}, {"press": "ArrowUp"},
{"press": "Backspace"}, {"press": "Enter"}], "gap_ms": 150}`, typed by Playwright into the X3D canvas. `clicks` 0.

New code, and the only shared files you may touch:
- `tools/behaviour_sim_judge.cjs`: a `--keys FILE` option (after the positional arguments; `behaviour_demo.py
  record` already passes it) that focuses the canvas and types the plan, logging every key event with X_ITE's
  time, as drags log the pointer.
- `tools/behaviour_sim_judge.py`: replay keys into the simulator's KeySensor and StringSensor (they are
  caller-driven now) so their outputs are produced by the simulator and compared, not copied from the trace.
- `source/behaviour_sim.py`: KeySensor and StringSensor from raw keys (X_ITE:
  `Components/KeyDeviceSensor/KeySensor.js`, `StringSensor.js`): key names, action key codes, modifiers,
  `deletionAllowed`, `finalText` on Enter.
- `source/behaviour_play.py`: forward key events from the modal operator to KeySensors and StringSensors while
  playing (Esc still stops), and show a Text node's `string` on the Blender text object the importer made, if it
  made one (if not, say so; that is the importer's call).

Judges: `KeySensor`, `StringSensor`. The act types through the event queue with `rig.type_key` (letters, digits,
space, Enter; modifiers via `rig.key`) and checks the hammer moved, a pedal lit, and the text reads what was typed.

## 3. Orrery: a clockwork sky

A brass orrery on a dark stage: a sun, four planets on arms, two with moons, all turning at their own rates. A star
chart on the back wall scrolls with the year.

| Part | Nodes | Notes |
|---|---|---|
| orbits | a looping TimeSensor per planet (cycleInterval 4 s to 20 s), OrientationInterpolator into each arm's `rotation` | moons are nested Transforms with their own clock |
| fly to a planet | TouchSensor on each planet, TimeTrigger, a 3 s TimeSensor, PositionInterpolator and OrientationInterpolator into the Viewpoint's `position` and `orientation` | Play moves the scene camera (since the proximity work); clicking another planet flies there |
| star chart | the year clock drives a **PositionInterpolator2D**; a **PositionChaser2D** smooths it into the chart's TextureTransform `translation` | if Play cannot show a TextureTransform yet, add that target (below) |
| pause | a lever (TouchSensor, BooleanToggle) into the year clock's `enabled` or pause/resume | all orbits that share the year clock stop |

Recorder: clicks on one planet (`clicks` 2: fly there, fly back is a second planet or the sun), `seconds` 12.

New code, and the only shared files you may touch:
- `source/behaviour_play.py`: TextureTransform `translation` / `rotation` / `scale` as a Play target (the Mapping
  node of the material the importer made), restored on Stop, if it is not one already.

Judges: `PositionInterpolator2D`, `PositionChaser2D`. The act lets the orrery run (screenshots every 1.5 s), clicks a
planet and checks the camera flew, the arms turned, and the chart moved.

Wow beats: the whole orrery turning in the viewport while the node editor glows beside it; the camera swooping to
the clicked planet.

## Template: hello-switch

`tests/behaviour/demos/hello-switch/`: a TouchSensor on a red button, BooleanFilter, BooleanToggle into a
PointLight's `on` and a halo's `visible`. Judged: 2 of 2 streams agree with X_ITE 16.7.1 (worst gap 0). The act
presses the button three times in the window and checks the lamp toggled.
