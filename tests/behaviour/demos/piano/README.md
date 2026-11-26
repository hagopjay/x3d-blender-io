# Piano: type and it plays

A grand piano seen from above its keyboard, a music stand with a sheet, a stand lamp, three pedals and a line of 3D
text above the keys. Press keys in the Blender window and the piano answers. `docs/BEHAVIOUR_DEMOS.md` is the spec;
`hello-switch` is the template.

The world is written by `build.py` (`python tests/behaviour/demos/piano/build.py` writes `piano.x3d` and `keys.json`).

## Play it

File > Import > X3D with "Behaviour graph" on, press Play in the X3D Behaviour editor. While it plays the keyboard
belongs to the world (Esc stops, and puts everything back).

| You do | Sensor | What happens |
|---|---|---|
| any key | KeySensor `isActive` | BooleanFilter, TimeTrigger, a 0.25 s TimeSensor, a PositionInterpolator: the red hammer bar dips; the same clock drives a ScalarInterpolator into the stand lamp glow's `transparency`: the lamp flashes |
| hold Shift, Alt, Ctrl | KeySensor `shiftKey`, `altKey`, `controlKey` | the soft, sostenuto and sustain pedal light up (the `visible` of a glow on each) |
| an arrow, Home, PageUp, an F key | KeySensor `actionKeyPress`, `actionKeyRelease` | the code (F1 to F12 are 1 to 12, Home 13, End 14, PageUp 15, PageDown 16, Up 17, Down 18, Left 19, Right 20) goes into an IntegerTrigger, and out as `triggerValue` when the key comes up; see finding 6 |
| click the sheet | TouchSensor into `StringSensor.enabled` | the sheet takes the keyboard: the blue light on the right of the key slip comes on, the amber one on the left goes out |
| type | StringSensor `enteredText` | what you typed |
| Backspace | StringSensor `deletionAllowed` | deletes a character; the brass lever on the right of the stand (click it) forbids or allows it, and its green light says which |
| Enter | StringSensor `finalText`, `isActive` | stamps the line; `isActive` going false hands the keyboard back to the KeySensor (a BooleanFilter into `Keys.enabled`) |

Only one key device sensor listens at a time (finding 2), so the world has two modes and the sheet is the switch. Type at
least one character before Enter, or the sheet keeps the keyboard (Enter with nothing typed sends `finalText` and leaves
`isActive` as it was).

**Where the typed line shows.** In a browser: the Text above the keys and the Text on the sheet, through a three-line
Script each (finding 1). In Blender: Play does not run Scripts, so the Texts keep their first strings
("type here", "click the sheet and type") and the typed line is drawn over the viewport and on the status bar from the
StringSensor's own outputs. The Script nodes are listed as "Not played" when you press Play, by design.

## Graph

```
Keys (KeySensor)  isActive ─► Strike (BooleanFilter) ─► StrikeTrigger (TimeTrigger) ─► HammerClock (TimeSensor 0.25 s)
                                                                 ├─► HammerDip (PositionInterpolator) ─► Hammer.translation
                                                                 └─► LampFlash (ScalarInterpolator)   ─► GlowPaint.transparency
                  shiftKey / altKey / controlKey ─► SoftGlow / SostGlow / SustainGlow .visible
                  actionKeyPress ─► ActionCode.integerKey;  isActive ─► KeyUp (BooleanFilter) ─inputNegate─► ActionCode.set_boolean
                  ActionCode.triggerValue ─► LastAction.integerKey;  actionKeyRelease ─► ReleaseCode.integerKey
                  keyPress / keyRelease ─► EchoKey (Script) ─► CaptionText.string
                  enabled_changed ─► KeysLight.visible
SheetTouch ─► SheetPress (BooleanFilter) ─inputTrue─► Typed.enabled
Typed (StringSensor)  isActive ─► TypingDone (BooleanFilter) ─inputNegate─► Keys.enabled
                      enteredText ─► EchoLine (Script) ─► LineText.string;  finalText ─► EchoSheet (Script) ─► SheetText.string
                      enabled_changed ─► TypeLight.visible
LockTouch ─► LeverPress (BooleanFilter) ─► Allow (BooleanToggle, starts true) ─► Typed.deletionAllowed, AllowedLight.visible
```

## Checked

| What | Instrument | Result |
|---|---|---|
| Judge | X_ITE 16.7.1 in headless Chromium (SwiftShader), 94 real key events typed by Playwright 1.63 into the canvas (`keys.json`), each logged with X_ITE's own clock; `python tools/behaviour_demo.py judge piano` | 24 of 24 streams agree, each with at least one X_ITE event, worst gap 0 (table below) |
| KeySensor and StringSensor | the simulator now runs them from the raw keys (`Simulation.key`): `key`, `which`, `charCode`, `keyCode` as X_ITE's own handlers read them; the judge replays the logged keys and compares what they send, it no longer copies it from the trace | judged: `KeySensor`, `StringSensor` (removed from the `unjudged` list in `tests/test_behaviour_sim.py`) |
| The test catches mistakes | 20 deliberately wrong versions, run by hand (table below) | 20 of 20 rejected; the code was restored after each (`git diff` of `source/` and `tools/` empty) |
| Play, no window | `tests/test_behaviour_demo_piano_bpy.py` (Blender 5.3, `-b`): Blender key names, release as the key that went down, hammer, pedals, the Integer chain, the two modes, the lever, Stop, a world without key sensors | 10 of 10 pass |
| Live window | `python tools/behaviour_demo.py show piano`, Blender 5.3, 1600 x 1000, real events through the window's queue (`--enable-event-simulate`) | Host-eyes `pass`, `act_ok` true, `not_applied` empty, Stop restores (`restored` true, `not_restored` empty) |
| Full suite | `Blender -b --factory-startup --python-exit-code 1 --python .github/scripts/run_tests_in_blender.py`, Blender 5.3, macOS arm64 | 1115 tests, one failure: `test_import_extreme_scale_bpy.test_inverted_helper`, which fails on main on this machine too |

What the act measured in the live window (Blender data, read through the event queue's own effects):

| Check | Measured |
|---|---|
| a key (`a`): the hammer dips and comes back | `Hammer.matrix_basis` moved 0.06 Blender units at most (sampled every 0.04 s; the X3D dip is 0.07 m), back to rest within 1e-4 |
| the lamp flashes | the glow material's Alpha rose from 0 to 0.86 (X3D transparency 1 to 0.1; sampled, so the peak is a lower bound) |
| the pedals | holding Shift, Ctrl or Alt lights exactly its own pedal (`visible` of `SoftGlow`, `SustainGlow`, `SostGlow`), all three together light all three, and all are dark again on release |
| arrow and F keys | `ActionCode.triggerValue` read 17 (Up), 2 (F2), 19 (Left) in turn |
| click the sheet, type `Hi Pianos`, Backspace, ` 88`, Enter | `enteredText` read `Hi Pianos`, `Hi Piano`, then `finalText` `Hi Piano 88`; the lights went `[keys, type]` = `[off, on]` and back to `[on, off]`; the next key struck the hammer again |

I looked at the screenshots (`piano-act-1-strike`, `-2-pedals`, `-3-typing`, `-4-stamped`, kept locally with the witness): the hammer
bar sits red over the keys, the pedals light amber, the typed line shows in yellow at the bottom of the viewport and on
the status bar. Not a judgement of taste: the lid reads as a flat dark wall from this camera, the lamp flash is faint, and
the Texts above the keys and on the sheet never change in Blender (see above).

### Judge table

X_ITE and simulator event counts are after the judge keeps the last event of each time stamp (X_ITE sent two events in one
millisecond for a tap faster than 1 ms); the clock and interpolator rows have more simulator events than X_ITE ones because
X_ITE under SwiftShader draws few frames: the judge compares each of X_ITE's events with the simulator's at the same time
stamp and does not require the simulator to be silent between them.

| Stream | X_ITE | Simulator | Compared | Worst gap |
|---|---:|---:|---:|---:|
| Keys.isActive | 31 | 32 | 31 | 0 |
| Keys.shiftKey | 4 | 4 | 4 | 0 |
| Keys.altKey | 2 | 2 | 2 | 0 |
| Keys.controlKey | 2 | 2 | 2 | 0 |
| Keys.actionKeyPress | 5 | 5 | 5 | 0 |
| Keys.actionKeyRelease | 5 | 5 | 5 | 0 |
| Keys.keyPress | 10 | 10 | 10 | 0 |
| Keys.keyRelease | 13 | 13 | 13 | 0 |
| Keys.enabled_changed | 9 | 9 | 9 | 0 |
| Typed.enabled_changed | 6 | 6 | 6 | 0 |
| Typed.isActive | 6 | 6 | 6 | 0 |
| Typed.enteredText | 20 | 20 | 20 | 0 |
| Typed.finalText | 3 | 3 | 3 | 0 |
| Strike.inputTrue | 16 | 16 | 16 | 0 |
| StrikeTrigger.triggerTime | 16 | 16 | 16 | 0 |
| HammerClock.fraction_changed | 34 | 71 | 34 | 0 |
| HammerDip.value_changed | 34 | 71 | 34 | 0 |
| LampFlash.value_changed | 34 | 71 | 34 | 0 |
| KeyUp.inputNegate | 31 | 32 | 31 | 0 |
| ActionCode.triggerValue | 16 | 16 | 16 | 0 |
| SheetPress.inputTrue | 3 | 3 | 3 | 0 |
| TypingDone.inputNegate | 6 | 6 | 6 | 0 |
| LeverPress.inputTrue | 2 | 2 | 2 | 0 |
| Allow.toggle_changed | 2 | 2 | 2 | 0 |

Not in the table: the two TouchSensors (their `isActive` is replayed from X_ITE, as in `hello-switch`) and the three Scripts
(X_ITE ran them: `EchoLine.line` 20 events, `EchoKey.line` 23, `EchoSheet.line` 3, kept in the trace as evidence; the simulator
does not run Scripts, and the judge lists them under `not_simulated_sources` instead of comparing them).

The recorded plan (`keys.json`): `a`, Enter, Escape, Tab, Delete, Home, PageDown, Shift+A, Control+b, Alt+c, ArrowUp, F2,
ArrowLeft; hold Shift and click the sheet (the KeySensor is disabled with a modifier held), let go, type `Hello Pianos`,
Backspace, click the lever, Backspace (refused), click the lever, `!`, Backspace, `!`, Enter; `z`; click the sheet, `ok`, Enter;
click the sheet, Enter (nothing typed), `x`, Backspace, Backspace (nothing left to delete), Escape (leaves typing); `q`.

### Mutants (run by hand, then restored)

Each row: one change to `source/behaviour_sim.py` or to the replay in `tools/behaviour_sim_judge.py`, then
`python tools/behaviour_demo.py judge piano`. All 20 fail the judge. Streams that failed (only the first ones for the long lists):

| # | Wrong version | Failing streams |
|---|---|---|
| K1 | Shift and Control swapped | Keys.shiftKey, Keys.controlKey |
| K2 | arrow Up is code 18 | Keys.actionKeyPress, ActionCode.triggerValue, Keys.actionKeyRelease |
| K3 | a key up does not end `isActive` | Keys.isActive, Strike.inputTrue, StrikeTrigger.triggerTime, HammerClock, HammerDip, LampFlash, KeyUp, ActionCode |
| K4 | Enter is `"\r"` not `"\n"` | Keys.keyPress, Keys.keyRelease |
| K5 | a key down does not set `isActive` | Keys.isActive, Strike.inputTrue, StrikeTrigger.triggerTime, HammerClock, HammerDip, LampFlash, KeyUp, ActionCode |
| S1 | Backspace ignores `deletionAllowed` | Typed.enteredText, Typed.finalText |
| S2 | Enter also sends `enteredText ""` | Typed.enteredText |
| S3 | Enter does not clear the text | Typed.finalText |
| S4 | Escape does not end `isActive` | Typed.isActive, TypingDone.inputNegate, Typed.enteredText and the Keys streams after it |
| S5 | Backspace on empty text sends an event | Typed.enteredText |
| S6 | Backspace tests `text or isActive` instead of `isActive and text` | Typed.enteredText |
| E1 | enabling one sensor leaves the other enabled | Keys.isActive, Strike.inputTrue, Keys.shiftKey, Keys.keyPress, Keys.enabled_changed, Typed.enabled_changed, Typed.isActive, Typed.enteredText, Typed.finalText, ... |
| E2 | disabling a KeySensor does not release its held modifiers | Keys.isActive, Keys.shiftKey, KeyUp.inputNegate, ActionCode.triggerValue |
| E3 | a disabled sensor still hears keys | Keys.isActive, Strike.inputTrue, Keys.shiftKey, Keys.keyPress, Typed.isActive, Typed.enteredText, ... |
| E4 | the `enabled false` the other sensor is given is not sent | Keys.enabled_changed, Typed.enabled_changed |
| R1 | the replay drops key ups | Keys.isActive, Keys.shiftKey, Keys.altKey, Keys.controlKey, Keys.actionKeyRelease, Keys.keyRelease, KeyUp, ... |
| R2 | the replay sends keys 0.5 s late | 21 of 24 streams (everything the keys cause) |
| R3 | the replay zeroes the key code | 21 of 24 streams |
| R4 | the replay sends only the first key of each time stamp | Keys.isActive, Strike.inputTrue, KeyUp.inputNegate, ActionCode.triggerValue, ... |
| R5 | the keys are not replayed (the old caller-driven behaviour) | 21 of 24 streams |

Two of my first mutants were accepted at first and made the plan better: "Enter does not clear the text" (no second typing
session and no Enter with nothing typed in the plan) and a Backspace that fires on empty text (no double Backspace). The plan
now has both, and S3 and S5 reject them.

## Not checked

- How it looks to a person: the screenshots were looked at, nothing more. The lamp flash is faint in the viewport (peak
  alpha 0.86 sampled at 0.04 s), and the lid reads as a wall from the camera.
- The typed line on a Blender Text object: not possible (findings 1 and 8). It is on the status bar and over the viewport.
- Anything but a US layout with Chromium's keyboard (Playwright sends `key`, `which`, `keyCode`, no composition); key
  repeat (holding a key down), CapsLock, AltGraph, Insert, the Meta key, IME; a Mac Option key making other characters.
- A same-millisecond press and release: X_ITE's callbacks fire twice but the judge keeps the last per time stamp, so a tap
  that fast cannot show a wrong `isActive` order. The plan's keys are 150 ms apart, the taps themselves 1 to 15 ms.
- `StringSensor` when disabled while active (X_ITE's `release` does nothing there; the simulator does the same, but the
  plan never leaves it mid-word).
- Esc in the window stops Play (the contract); X_ITE's Esc clears a StringSensor. The simulator has the X_ITE rule
  (judged, `Escape` in the plan) but a person cannot reach it in Blender.
- Other Blender versions than 5.3; other window sizes; a window another application has focus in.
- The act reads the Integer chain from the simulator's outputs, not from a scene object (finding 6).

## Findings for Loom

1. **A StringSensor cannot drive a Text without a Script.** `ROUTE StringSensor.enteredText -> Text.string` joins an
   SFString to an MFString. X_ITE 16.7.1 refuses it: its console says `Bad ROUTE specification: source field type must match
   destination field type of fields named "enteredText" and "string"` and sends nothing (measured: a 6-line world loaded
   in headless Chromium with a console listener, 2026-11-26; the warning is not part of the recorded trace). The graph module already agrees:
   `Behaviour.route` raises `type-mismatch` and `validate` of the same file reports `type-mismatch`. The spec's "the line
   shows what is typed" therefore needs a Script (`EchoLine`, `EchoSheet`: `line = new MFString(value)`), which X_ITE
   runs and Play does not. Evidence: `x_ite.json` events of `EchoLine.line` follow every `Typed.enteredText` event one for one.
2. **Only one key device sensor is enabled at a time.** X_ITE's `X3DKeyDeviceSensorNode.enable()` sets every other
   enabled KeySensor and StringSensor to `enabled` false (and `release()` sends their modifiers and `isActive` false). A
   world with both and neither `enabled="false"` gets the later one only: measured with a KeySensor and a StringSensor in
   one world, the KeySensor never sent `isActive`. The demo uses the rule as a feature (the sheet and `TypingDone` switch
   the mode) and the simulator models it (`_KeyDevice._enable`, judged by `Keys.enabled_changed`, `Typed.enabled_changed`
   and mutants E1 to E4). Evidence: the `enabled_changed` events of both sensors in `x_ite.json`, e.g. `Keys.enabled_changed`
   false at the same time stamp as `Typed.enabled_changed` true.
3. **`enteredText` is not cleared by an event.** On Enter X_ITE sends `finalText`, clears `enteredText` with `.set("")`,
   which sends nothing, and ends `isActive`. A Text fed by `enteredText` keeps the old line until the next character,
   which sends `""` then the new text as one event (the last value of a field set twice in one key event is the one sent).
   Evidence: judged stream `Typed.enteredText` (no event at Enter); mutants S2 and S3.
4. **`isActive` is per key, not per "a key is held".** Every key up ends it, even while Shift is still held, and every key
   down starts it; Shift itself starts it. A "key is down" light on `isActive` flickers per key; use `shiftKey`/`controlKey`/
   `altKey` for held modifiers. Evidence: `Keys.isActive` and `Keys.shiftKey` events of Shift+A in `x_ite.json`.
5. **Enter with nothing typed leaves the StringSensor in charge.** `finalText` is sent (empty) but `isActive` was
   already false, so no event hands the keyboard back; the demo's way back (`TypingDone`) only works after a character.
   Evidence: the Enter-with-nothing step of `keys.json`: `Typed.finalText` has 3 events, `Typed.isActive` 6 (2 per typed word).
6. **An SFInt32 key code has nowhere visible to go.** `actionKeyPress` can reach `IntegerTrigger.integerKey` and `triggerValue`
   can reach another `integerKey`, `Switch.whichChoice` or `LOD`; nothing turns an integer into a float or a Bool without a Script,
   and Play has no `Switch` target. So the Integer chain is judged against X_ITE but shown in Blender only as the editor's
   glow on `ActionCode` and as `Simulation.outputs` (what the act reads). A `Switch.whichChoice` target in Play would give it a body.
7. **The eye test's standard step clicks the first object a sensor senses.** For this demo that is the sheet, which puts the
   world in typing mode before `act.py` starts; the act reads the mode and the lever and puts both right. A demo whose
   sensors change mode should not rely on the standard click.
8. **The graph did not bind Text; it does now (outside this demo's files, at the lead's request).** The importer makes a FONT
   object for each Text (named by the Shape's or Transform's DEF, its curve data by the Text's DEF, `body` the string), but
   `behaviour_graph.BINDING_OF` had no Text kind, so the import dropped every ROUTE into one. `BINDING_OF` now has
   `"Text": "text"` (its own line) and `behaviour_nodes.import_graph`'s resolver finds the FONT object by the curve's DEF,
   outermost carrier first. Import keeps `EchoLine.line -> LineText.string` and the other two (test in
   `tests/test_behaviour_demo_piano_bpy.py`). **Export still drops them**: `emit_x3d40.py`'s `def_of_target` has no `text`
   branch, so a ROUTE into a Text is written out as "left out because an end is not in the file". That file is not this
   PR's to edit; the exporter needs a `text` case (and to write the Text's DEF) before a round trip keeps the ROUTE. The same gap exists for TextureTransform (found by the orrery demo). The failing export test is deliberately not in this PR; the exporter's owner gets it.
   Play does not write a Text's string yet (`not_applied` would say so); no simulated node sends an MFString into one.
9. **`Play` swallows the keyboard while the graph has a KeySensor or StringSensor.** Blender shortcuts do nothing during Play
   (Esc still stops); a graph without key sensors passes everything through, as before.
