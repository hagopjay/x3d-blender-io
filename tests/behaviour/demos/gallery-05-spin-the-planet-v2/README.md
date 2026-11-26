# Gallery 05 v2: spin the planet, five moons chase its turn (corrected copy)

A copy of [`gallery-05-spin-the-planet`](../gallery-05-spin-the-planet/) (which is left as it was) with two changes, both
made in `build.py`, and nothing else:

1. **A full turn is four keys.** Each moon's tumble `Tum0..Tum4` was keys `0 0.5 1` with angles `0, 3.1416, 6.2832` about
   one axis: two steps of exactly pi, which have no shortest way round. X_ITE 16.8.1 and the simulator both turn all five
   **backwards** (about -6.3 rad per cycle, no step forward). v2 uses keys `0 0.3333 0.6667 1` with angles `0, 2.0944,
   4.1888, 6.2832`: every step is 2.0944 rad (a third of a turn), forward, +2 pi per cycle. The graph check warns about the old
   spelling (`Behaviour.warnings()`, code `half-turn`) and is quiet on this one.
2. **Every ROUTE is written after the nodes it names.** The original wrote the sixteen star `Twinkle/Blink` ROUTEs before
   their nodes; X_ITE 16.8.1 drops such a ROUTE (the stars never twinkled there). Same graph, now in a legal order.

Graph: unchanged otherwise (80 nodes, 58 ROUTEs).

## Checked

| What | Instrument | Result |
|---|---|---|
| Turns agree | `tools/behaviour_sim_judge.py` on `x_ite_turns.json` (X_ITE 16.8.1, headless Chromium, software GL, 7 s, no clicks) | `Tum0..4.value_changed`: 64 events each, worst gap 0 |
| Direction | signed turn about +z between consecutive events | X_ITE: 64 to 66 steps, 0 backward, net +22.0 / 14.7 / 11.0 / 8.8 / 7.3 rad in 7 s (+2 pi per cycle of 2 to 6 s); simulator: 421 steps, 0 backward |
| Warning | `tests/test_behaviour_halfturn.py` | 5 warnings on the original, none on v2 |

Not checked: the live Blender window (`act.py` is the original's and was not run on v2). `x_ite_turns.json` is not named
`x_ite.json` on purpose: 8 streams of the star timers (`Blink0, 1, 4, 6, 10, 13, 14` and `Twinkle4`) differ by one event
because X_ITE sends fraction 1 and then the new fraction in one time stamp when a looping TimeSensor wraps and the
simulator sends only the new one; `tests/test_behaviour_halfturn.py` pins that those are the only streams that differ.
The streams judged are 50 of 52: the two of the SphereSensor are not recorded (no clicks).
