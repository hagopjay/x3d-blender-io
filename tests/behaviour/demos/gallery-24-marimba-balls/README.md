# Gallery 24: marimba played by falling balls

**Idea.** Ten coloured bars of descending length, a rail overhead with a ball parked above each bar. Three buttons in front
pick a song. A song is a schedule of drops: ball k is released so it lands on bar n_k at time t_k. The ball falls, hits the
bar, hops three times and is lifted back to the rail; the struck bar dips and flashes white. Click any bar to strike it
yourself.

**Graph.** Per bar n: `TouchSensor` (`touchTime` -> bar clock), a bar `Transform` dipped by a `PositionInterpolator` and
flashed by a `ColorInterpolator` into the material's `baseColor` and `emissiveColor` (the ball shares the bar's
`Appearance` by `USE`, so it flashes too), and the ball's chain: `Rel` (TimeTrigger) -> fall clock `FallClk` (0.45 s, a
quadratic-drop `PositionInterpolator`) whose end (`isActive` -> `BooleanFilter.inputNegate` -> TimeTrigger `Hit`) is the
landing: `Hit` starts both the bar clock and the 1.5 s `BounceClk` (hops, rest, lift to the rail). A song is a looping
master `TimeSensor` plus one `BooleanSequencer` per ball it uses on `fraction_changed`; the sequencer's `true` (from the
ball's release time until just before its next release, so a late player step cannot skip a note) fans in to that ball's
`Rel`. Songs: 1 climb (0..9 at 0.45 s, then a three-bar chord), 2 zigzag (outside-in, swung 0.35/0.6 s), 3 skips and
accelerating (even bars up, odd bars down). A button: `TouchSensor` -> `BooleanFilter` `Press`; `Press.inputTrue` ->
`TimeTrigger` -> song `startTime`, one `BooleanFilter` hop later -> song `enabled` (so the new lap really starts at the
click), -> its lamp `visible`, and -> `BooleanFilter` `Off` whose `inputNegate` (false) fans out to the other two songs'
`enabled` and lamps. Only one master clock runs. 191 nodes, 243 ROUTEs, 168 ROUTE sources (`check`), built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play. Song 1 plays. Click the gold, cyan or magenta disc in front for
song 1, 2 or 3 (the white lamp above shows which). Click a bar to strike it. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-24-marimba-balls`, Blender 5.3, the act clicks buttons 2, 3, 1 with real mouse events and then a bar; the eye test's own click struck bar 0 | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Melody | per song, one lap watched on `player.now` from the press; each bar's world height read from Blender every 0.05 s, a dip below rest by 0.08 counted as a landing | landings matched to the designed time (a dip of the right bar 0.3 s before to 2.0 s after it): song 2 9 of 10, song 3 9 of 10, song 1 12 of 13; order of landings 0.9 s or more apart: 0 inversions in 29, 26 and 53 pairs |
| Two songs, two orders | order of matched dips | all three songs gave different landing orders (5,6,4,7,3,8,9,1,0 / 0,4,6,8,9,7,5,3,1 / 0,1,3,4,5,6,7,8,9,0,4,8; a bar the player's coarse step missed is absent) |
| One song at a time | lamp visibility sampled every 0.05 s | exactly one lamp lit in every sample of all three laps |
| Balls | ball world height | every ball dropped below 1.5 and was lifted back to the rail in each lap (10 of 10) |
| Bar click | a real click on bar 9 (not due in the song for seconds) | bar 9 dipped (other bars dipped too: the song was playing) |
| Headless | the simulator (`source/behaviour_sim.py`) driven with random 0.15-0.7 s steps, buttons pressed by `post` | the same landing order and a lap that starts at the press |
| Look | `best.png` and the other screenshots read by eye | a rail with a row of coloured balls, balls mid-fall and sitting on bars, a rainbow row of bars falling in length, three coloured discs and a white lamp. The solid viewport shows `baseColor`, so the bars look duller than the flash colours; the white flash itself I could not see in a still. |

**Timing is coarse.** The player's clock stepped every 0.3 to 0.65 s here (largest step in a lap 0.63 to 0.64 s, with a
screenshot in the lap; I did not measure a quiet median). Each stage of the chain (release, fall, landing, bar clock) rounds
up to a step, so a bar dips about 1.2 s (median 1.16 to 1.23 s) after the designed landing time. The tune keeps its order and
its rough rhythm, but swung 0.35 s gaps blur and two adjacent notes can land in one step.

Not checked: X_ITE judging (no trace recorded, none claimed); the white flash and the glow on screen; behaviour when a song
is switched while a ball is in flight (the old ball finishes its fall and lift by itself; the new song's ball for the same bar
would restart its fall mid-lift); the Schematron or a render oracle.

## Findings for Loom

1. **A `TimeTrigger` to `startTime` and a `true` to `enabled` in the same event cascade race.** Restarting a looping,
   disabled `TimeSensor` with `Press.inputTrue` -> `TimeTrigger` -> `startTime` and `Press.inputTrue` -> `enabled` made
   the sensor start at its old phase, then ignore the new `startTime` (it was already active). The simulator drains its queue
   breadth-first, so `enabled` arrives one hop before `startTime`. Fix in the world: send `enabled` through one extra
   `BooleanFilter`. Found by driving the simulator headless; reproduced live. X_ITE may order the two differently.
2. **A looping `TimeSensor`'s phase counts from `startTime`, not from `enabled`.** Enabling a sensor with `startTime` 0
   starts it mid-lap at `now mod cycleInterval`; a song needs its `startTime` set first.
3. **A `BooleanSequencer` jumped over a short window loses the event.** With 0.4 s windows and player steps up to 0.65 s
   notes were skipped. Holding `true` until the next release time (a cumulative gate) cannot skip.
4. **A ROUTE to the `startTime` of a busy `TimeSensor` is dropped silently**, so a ball released again while it is still
   in its 1.95 s fall-and-lift cycle is ignored; the songs space repeat hits of one bar by 2 s or more.
5. **`Appearance USE` shared between a bar and its ball imports fine**, and a `ColorInterpolator` into the shared
   material's `baseColor` and `emissiveColor` recolours both.
6. **Player stepping slows with node count and with screenshots** (0.3 to 0.65 s steps at 191 nodes); not reduced here.
