# Gallery 07: spirograph (recorded attempt: the look is not confirmed)

**Idea.** Three nested rotating arms (Transforms inside Transforms, one OrientationInterpolator each, 1, -3 and 7 turns
per 20 s) carry a pen; forty beads replay the pen's path from one precomputed curve, each a little later (a
PositionInterpolator per bead with shifted keys), with a rainbow ColorInterpolator down the tail.

**Graph.** One looping TimeSensor `Clock` → `Turn0..2` → `Arm0..2` `rotation`; → `Trace0..39` → `Bead0..39` `translation`;
→ `Rainbow0..39` → `BeadPaint` `baseColor` and `emissiveColor`. 167 nodes, 206 ROUTEs, 188 KB, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play. Esc stops. Heavy: the live run takes several minutes in Blender.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-07-spirograph`, Blender 5.3, 22 s watched | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Two paths agree | pen's world position (three nested Transforms) against bead 0 (replayed curve), sampled 220 times | max and mean gap 0.15 m, constant: it is the three 0.05 m z offsets the arms are stacked with, so x and y agree |
| Look | screenshots at 10 s and 18 s, read by eye | **not convincing**: the arm moves between the two frames but the bead strand looks almost the same in both, and I could not tell a spirograph from it. I did not find out why. |

Not checked: why the tail looks static between frames (bead 0 provably tracks the pen; the rest of the beads were not
sampled over time); the beads' colours (the viewport selection outline hides them in the eye-test frames); X_ITE.

## Findings for Loom

1. **Size matters for the live window:** 40 PositionInterpolators with 145 keys each (167 nodes) made the eye test
   several times slower than the earlier demos (under 1 minute for 04, several minutes here). A bead trail wants a
   smaller design (fewer keys, or fewer beads).
2. The nested-Transform composition (arm in arm in arm) matches a closed-form curve in Play, to the z offset.
