# Gallery 14: slot machine

**Idea.** Pull the lever. Three reels spin and slow one after another and all stop on the red 7; the sign pulses, twelve lamps
flash and fourteen coins fly out of the tray. It is deterministic: a toy that always pays out.

**Graph.** TouchSensor `LeverTouch` → BooleanFilter `Press` → TimeTrigger `GoSpin` → `Spin` (4 s) and `Pull` (0.7 s, the lever
swings down and back). `Spin.isActive` → BooleanFilter `SpinDone` → `inputNegate` → TimeTrigger `GoWin` → `Win` (3 s). Each reel
shows one of 6 symbols: 18 BooleanSequencers `Show<reel><symbol>` on `Spin.fraction_changed`, change times `t_stop * (j/n)^2` so the
gaps grow (the reel slows); reels stop at 2, 3 and 4 s after 14, 17 and 20 steps, the last step being the red 7 (symbol 0).
Twelve `Chase` sequencers run the lamps round during the spin, twelve `Flash` sequencers flash them in the win; a
ColorInterpolator pulses the sign; fourteen coins each get a PositionInterpolator fountain arc on `Win` and `Win.isActive` →
`visible`. 112 nodes, 138 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play, click the lever (right of the cabinet) and watch. Pull it again when it
is done. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-14-slot-machine`, Blender 5.3; the eye test's click pulled the lever once, then the act pulled it again with a real click; times read from the simulator's clock (`player.now`) | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Reels | symbol shown by each reel, every 0.05 s of wall time, second pull | 10, 12 and 16 symbol changes; the reels' last changes at 2.07, 3.04 and 4.16 s (designed 2, 3, 4); all three end on symbol 0 (also after the first pull) |
| Deceleration | gaps between changes | the longest late gap beats the longest early gap on every reel (e.g. 0.19 s early, 0.59 s late). **Coarse:** the player's clock advanced in steps of about 0.19 s (median 0.187 s), so changes faster than that are merged and the early gaps all read as 0.19 s |
| Jackpot | lamps, coins | 12 of 12 lamps lit at once; 14 of 14 coins in flight at once |
| Look | screenshot mid-spin, read by eye (after a fix, below) | a red cabinet with a white reel window showing a red 7 tile, a bell and a cherry, a red lever ball, a gold sign. Coins are small in frame. |

**A mistake worth noting.** The first version put the reels and window inside the cabinet box. Every data check passed (the
objects were there, visible and changing) while the screenshot showed a plain red box. I fixed the cabinet depth and window
position, reran, and only then looked at the reels. A data check cannot see occlusion.

Not checked: X_ITE judging (none); the sign pulse's colours (solid viewport).

## Findings for Loom

1. **Switch `whichChoice` is not applied by Play** (nothing in `behaviour_play.py` or `behaviour_graph.py` handles it), so a
   reel cannot cycle by `whichChoice`. This demo uses one BooleanSequencer per symbol driving `visible` instead.
2. **The player's clock steps at about 5 Hz in this world** (median 0.187 s over 7 s of the second pull; 112 nodes, a live
   window taking screenshots). Anything faster than that cannot be seen from Blender data; a demo's own timing checks should
   read `player.now` and expect that granularity.
3. Chaining as in galleries 03 and 13 (`isActive` → `inputNegate` → TimeTrigger) works again: lever, spin, win.
