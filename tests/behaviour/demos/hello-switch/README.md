# Hello switch (template demo)

The smallest behaviour demo, and the template for the others (`docs/BEHAVIOUR_DEMOS.md`): press the red button and
the lamp on the post toggles, with its halo.

Graph: TouchSensor `Button` `isActive` → BooleanFilter `Press` → `inputTrue` → BooleanToggle `Toggle` →
`toggle_changed` → PointLight `Bulb.on` and Transform `Halo.visible`.

Play it in Blender: File > Import > X3D with "Behaviour graph" on, press Play in the X3D Behaviour editor, click
the button in the 3D view. Esc stops and puts everything back.

## Checked

| What | Instrument | Result |
|---|---|---|
| Judge | X_ITE 16.7.1, headless Chromium (SwiftShader), 3 real clicks; `tools/behaviour_demo.py judge hello-switch` | 2 of 2 streams agree (Press.inputTrue, Toggle.toggle_changed), worst gap 0 |
| The test catches mistakes | `DemoJudgeTests`, by hand: a wrong stream count, a false `judges` claim, a world X_ITE did not record (`toggle="true"`) | all three fail the test |
| Live window | `tools/behaviour_demo.py show hello-switch --with probe-drag probe-proximity`, Blender 5.3, 1600 x 1000, real clicks through the event queue | three presses: lamp off, on, off, halo with it (`act_ok` true); Host-eyes pass, 3 of 3 worlds |

Not checked: how the lamp looks to a person; the TouchSensor's own outputs are replayed, not compared (the judge
compares what the graph computes from them).
