# Gallery 03: Rube Goldberg machine

**Idea.** One click on the red button cascades through ten timed stages along a 22 m bench while the camera rides
with the action: button dip, six dominoes tipping in turn, a ball down a ramp, a seesaw that throws a pebble in an arc,
a lever that raises a flag, a bell that rings and flashes gold, a lamp that lights, a rocket, a ring of twelve
fireworks, a banner that unrolls and cycles colour.

**Graph.** Per stage a TimeSensor `StageN`, a BooleanFilter `DoneN` and a TimeTrigger `GoN`. `StageN.isActive` →
`DoneN.set_boolean`; `DoneN.inputNegate` (true when the stage ends) → `Go(N+1).set_boolean`; `GoN.triggerTime` →
`StageN.startTime`. The button's TouchSensor → BooleanFilter `Press` → `Go0`, and `Go0` also starts the `Tour` clock
that drives Viewpoint `position` and `orientation` through one key per stage and ends in a wide shot. The stages'
effects are Position, Orientation and Color interpolators into Transforms and materials, and `Stage6.isActive` straight
into the lamp's `on`, `Stage8.isActive` into twelve sparks' `visible`. 97 nodes, 109 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play, click the red button (start of the bench). About 14 s later
the camera ends on a wide shot of the whole machine; click the button again to run it again.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-03-rube-goldberg`, Blender 5.3, two runs (the eye test's click, then the act's own real click on the button) | Host-eyes **pass**; `act_ok` true: in both runs every one of 11 watched objects (button, domino, ball, seesaw, pebble, lever, flag, bell, rocket, a spark, banner) took 3 or more distinct poses, the camera moved; `not_applied` empty; Stop restores |
| Look | screenshots read by eye | mid-run wide shot shows the rocket, the ring of twelve coloured sparks, bell, lamp and the banner; see `act-again-09` |

Not checked: X_ITE judging (none); the stage hand-offs are timed by the simulator, not compared with another player.

## Findings for Loom

1. **A chain of TimeSensors works as a sequencer:** `isActive` → BooleanFilter `inputNegate` → TimeTrigger →
   next `startTime` (`inputNegate` fires `true` when the input falls; `inputFalse` would send `false`, which TimeTrigger
   ignores, see gallery 01).
2. **The eye test clicks before the act.** `behaviour_eyetest.py` clicks the first sensed mesh in its standard steps,
   so a demo's act starts with the machine already running (0.6 s in). The act rides that run, then clicks itself
   when the tour ends.
3. **One DEF can tag several Blender objects.** A DEF'd Transform's unnamed child Transforms get the DEF too (the
   Play binding takes the outermost). An act that looks an object up by `x3d_def` must watch every object that
   carries it, or by name it can pick the nested copy (`Rocket.001`) that never moves.
4. **A Transform's rotated parent changes its local frame.** The button sits under a Cylinder, so its Blender
   `location` reads `(0, 0.3, 0)` (the mesh's rotated axes), though Play moves it correctly.
5. The Viewpoint's bind pose must equal the tour's first key, or the eye test's restore check (finding 2 of
   gallery 02) reports "not restored".
