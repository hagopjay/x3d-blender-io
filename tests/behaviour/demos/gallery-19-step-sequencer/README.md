# Gallery 19: step sequencer

**Idea.** A 4 x 8 grid of pads, a light organ. Click a pad to light it. Every lit pad drives an instrument that stands on
it, one kind per row: a bouncing ball (blue), a flashing disc (pink), a growing bar (green), a pulsing, colour-shifting
cone (yellow). Neighbouring pads in a row are a phase step apart, so a full row ripples. A white playhead sweeps the
eight columns in a 4 s loop, lighting the column's glow bar and a white plate on each of its four pads.

**Graph.** Each pad has its own `TouchSensor` → `BooleanFilter` (inputTrue) → `BooleanToggle` (initial `toggle` set to
the pad's starting state, so the first click turns a lit pad off). The toggle output fans out to three places: the lit cap
(`visible`), the voice (`visible`) and that pad's own looping 1 s `TimeSensor` (`enabled`). The pad's clock drives one
interpolator (two for the bar and the cone) shaped by the row and rotated by the column's phase, routed to the voice's
`translation`, `scale` or the cone's colour. The playhead is one 4 s `TimeSensor` → 8 `BooleanSequencer`s (one per
column, true only in its eighth of the lap); each fans out to its column's glow bar and the four pads' flash plates.
297 nodes, 312 ROUTEs, 185 ROUTE sources, built by `build.py`.

**Real logic and staged.** Real: each pad's own gating. A pad that is off has its clock disabled, so its voice does not
run at all; clicking one pad changes only that pad. Staged: X3D has no AND of two events, so the playhead and the pads do
not talk. The sweep lights every column whether or not its pads are lit, and a lit pad pulses on its own clock, not on
the playhead's hit. The beat looks synchronised because the lap (4 s) and the pad lap (1 s) are multiples.

**Play.** Import with "Behaviour graph" on, press Play. Click any pad to light or darken it. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-19-step-sequencer`, Blender 5.3, three clicks by the act after the eye test's own click on pad 0_0 | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Start pattern | cap and voice visibility of all 32 pads, read from Blender objects | 10 lit after the eye test's click (11 by design); cap and voice agree on every pad |
| Gating | pose (translation + scale) of every voice over 5 s at 5 Hz | all 10 lit voices moved (more than 3 poses); all 22 unlit voices stood still (1 pose) |
| Playhead | column glows and flash plates, 25 samples | all 8 columns lit; never 2 at once; every pad of a lit column showed its flash plate |
| Click toggles | 3 clicks (pads 3_0 off→on, 3_3 on→off, 2_4 off→on), state of all 32 pads before/after each | exactly the clicked pad changed, cap and voice together; the lit ones then moved, the darkened one stood still |
| Look | screenshots read by eye | a clear grid; the four instrument kinds are readable, coloured by row, with the white sweep and the click results visible. Row 0's balls are small and bounce past the grid's back edge. |

Not checked: X_ITE judging (no trace recorded, none claimed); that the playhead and a pad's pulse are in time, since they
are not coupled; frame-accurate timing (the player steps at about 5 Hz).

## Findings for Loom

1. **Initial `visible="false"` is not inherited by a nested child Transform at import.** My first bar was an outer
   scaling Transform with an inner one carrying the box; its outer was hidden but the inner stayed visible, and my cap/voice
   consistency check caught it. Fixed by making the bar one leaf Transform with two interpolators (scale and translation).
   Worth a look in the importer (not changed here).
2. **`BooleanToggle` `toggle="true"` as an initial state works:** the first click gave false, the pad went dark.
3. **Gating a per-pad clock with `enabled` from a toggle works** for 32 independent clocks in one live run.
4. X3D cannot AND two events, so "play the pad when the playhead reaches it" needs a node that does not exist; an
   `IntegerSequencer` per pad fed by a shared clock would be the nearest trick but would not see the pad's toggle.
