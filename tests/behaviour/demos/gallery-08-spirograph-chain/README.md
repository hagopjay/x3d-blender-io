# Gallery 08: spirograph chain (gallery 07 redone)

Gallery 07 passed but I could not confirm its look; this is the lighter redo, in its own folder (07 is untouched).

**Idea.** Three nested rotating arms (1, -3 and 5 turns per 16 s relative to their parents) carry a pen. A snake of 60
beads draws where it has been.

**What changed from 07, and why.** In 07 each of 40 beads replayed the curve from its own 145-key table, shifted in
time. Headless Play showed those beads did move (bead 0 matched the pen, beads 20 and 39 moved to different places at
each time), so the "static tail" I saw in two screenshots was most likely the beads being spread far apart (pen
speed times a 0.28 s step), not a bug in Play. Here the tail is a chain: bead 0 plays the curve (one 161-key
PositionInterpolator), bead *n* is a PositionChaser (`duration` 0.1 s) whose destination is bead *n-1*'s `value_changed`. One
table instead of forty (71 KB instead of 188 KB; the live run took 2 min instead of several).

**Graph.** TimeSensor `Clock` → `Turn0..2` → `Arm0..2` `rotation` (nested Transforms); → `Path` → `Bead0`; `Follow1..59`
(PositionChasers, chained) → `Bead1..59`; → `Rainbow0..59` → bead `baseColor` and `emissiveColor`. 247 nodes, 306 ROUTEs.

**Play.** Import with "Behaviour graph" on, press Play. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-08-spirograph-chain`, Blender 5.3, 20 s watched | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Pen vs replayed curve | pen's world x,y (three nested Transforms) against bead 0, 180 samples | max gap 0.004 m |
| A connected snake | positions of all 60 beads, 180 samples | head-to-tail distance 0.05 to 7.05 m; tail moved 6.7 m; largest gap between neighbouring beads 2.26 m (at the fast turns; the act's limit is 3.0 m, set from this run, it is this demo's own check) |
| Look | screenshot at 12 s, read by eye | a clear spiked loop of beads trailing the arm; the beads are spaced out (about 0.5 m on slow parts), so it reads as a dotted curve, not a drawn line |

Not checked: the beads' rainbow colours (the eye test's selection outline paints them all orange); X_ITE.

## Findings for Loom

1. **A chain of PositionChasers makes a trail with no tables** (each follows the one before). Cheap in the simulator and in Blender.
2. The viewport selection overlay set by the eye test hides material colours in its screenshots; judge colour from the data.
3. Many large `key`/`keyValue` tables slow the importer and the node tree view (07: several minutes live).
