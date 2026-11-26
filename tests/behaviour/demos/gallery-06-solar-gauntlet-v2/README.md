# Gallery 06 v2: solar gauntlet, a camera flight lighting ten gates (corrected copy)

A copy of [`gallery-06-solar-gauntlet`](../gallery-06-solar-gauntlet/) (which is left as it was) with three changes, all
made in `build.py`:

1. **A full turn is four keys.** The six prominences' `Arc0..Arc5` were keys `0 0.5 1` with angles `a, a + 3.1416,
   a + 6.2832`: two steps of exactly pi. In X_ITE 16.8.1 and in the simulator each arc turns forward for half a cycle and
   backward for the other half (net turn per cycle in the simulator: 0.0 rad), so the prominences wobble instead of
   spinning. v2 uses keys `0 0.3333 0.6667 1` with four angles 2.0944 apart: forward all the way, +2 pi per cycle.
2. **Every ROUTE is written after the nodes it names.** The original wrote the six `Flare -> Arc -> Prom` ROUTEs before the
   prominence nodes; X_ITE 16.8.1 drops them (zero events on `Arc0..5` in its recording of the original as written).
3. **A viewer driver for the judge**: `ProximitySensor Cam` of size -1 (the viewer's pose, as `probe-proximity.x3d` does) and
   a Transform `CamEcho` it is routed to, so the ten gate sensors can be judged. Nothing in the scene shows it.

Graph: 74 nodes, 59 ROUTEs.

## Checked

| What | Instrument | Result |
|---|---|---|
| Whole world agrees | `tools/behaviour_sim_judge.py` on `x_ite.json` (X_ITE 16.8.1, headless Chromium, software GL, 27 s: one flight and a few frames over) | 55 of 55 compared streams agree (ten gates' ProximitySensor, clocks and swells, the six arcs, the flight) |
| Direction | signed turn about +z between consecutive events | X_ITE: 117 to 119 steps per arc, 0 backward, net +12.5 to +24.2 rad in 27 s; simulator: 1,621 steps, 0 backward |

Not checked: the live Blender window (`act.py` is the original's and was not run on v2). The generic demo judge
(`DemoJudgeTests` in `tests/test_behaviour_sim.py`) picks this folder up through its `x_ite.json`.
