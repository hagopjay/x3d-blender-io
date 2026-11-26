# Gallery 23: dance floor

18 stick-and-ball dancers (6 columns x 3 rows) on floor tiles that flash with the beat. Three buttons in front of the
stage (cyan, magenta, green) pick the choreography: a Mexican wave, a disco point, a twirl. Exactly one runs at a time.

## The graph in one paragraph
Each dancer has nested limbs: a Root (stretch and turn), torso, head, two arms each carrying a forearm, two legs. For
every choreography and every COLUMN there is a small clock group: one TimeSensor plus ONE interpolator per limb type
(Hop, Spin, ArmL, ArmR, Elbow, LegL, LegR, Head) and one ColorInterpolator for the tiles. The column's phase lag is baked
into its keys (wave: 0.12 cycle per column; disco: odd columns half a cycle behind; twirl: 0.1 per column), and each
interpolator fans out by ROUTE to the same limb of the 3 dancers in that column. A button's TouchSensor goes to a
BooleanFilter whose `inputTrue` enables the 6 clocks of its choreography and, through a second BooleanFilter, whose
`inputNegate` (false) disables the 12 clocks of the other two. 351 nodes, 816 ROUTEs, 189 ROUTE sources. Regenerate with
`python build.py`.

## How to play it
Import with the behaviour graph and Play. The wave (A) runs first. Click the cyan, magenta or green pad to switch to the
wave, the disco point or the twirl; clicking the running one changes nothing. The eye test's own click happens first.

## Checked
| Instrument | Result |
|---|---|
| `behaviour_demo.py check` | 351 nodes, 816 ROUTEs, 189 sources; matches demo.json |
| Host-eyes (real Blender 5.3 window) | pass (grade C is the witness's own grade for this run), `not_applied` empty, restored true |
| act (Blender data: elbow height of the first row, root turn, tile colour; 50 samples per 10 s) | act_ok true. Wave: neighbouring columns correlate 0.59 (lagged, not identical), root turn 0.40 rad, brightest tile cyan (0.15, 0.89, 0.99). Disco: neighbours -0.955, next-but-one 1.00, turn 0.50, tile magenta (0.98, 0.15, 0.80). Twirl: turn 3.13 rad, tile green (0.15, 0.99, 0.86). Back to wave: 0.56, 0.40, cyan again |
| Screenshots (read by eye) | wave: a ridge of raised arms rolling across the left columns while the right ones stand; disco: every dancer's arms out in a line with tiles magenta; twirl: arms swept out and dancers turned, tiles green. The three look clearly different |

## NOT checked
- Whether two choreographies ever ran together for a moment: the act only samples 5 times a second after a 1.5 s
  settle, and judges the pattern (antiphase and no big turn in disco), not each TimeSensor's `enabled`.
- Hop is a vertical STRETCH of the dancer (a scale), not a jump: the eye test compares translations before Play and
  after Stop, and a translation animation caught mid-air makes `restored` false. So the feet never leave the floor.
- Switching mid-dance snaps limbs to the new choreography's pose; no easing was tried.
- The solid viewport shows the tiles' colour but not any light; the eye test selects every object, so the screenshots
  carry orange outlines (the rig, not the demo). Not looked at in Material Preview or a render.
- No X_ITE record or judge run (the task did not ask for it); the run takes about 10 minutes because of the 816 ROUTEs.

## Findings for Loom
1. `PRESS.inputTrue -> clocks.enabled` plus `PRESS.inputTrue -> OFF.set_boolean`, `OFF.inputNegate -> otherClocks.enabled`
   is a clean one-of-three radio selector from plain BooleanFilters; no BooleanToggle is needed, and the negate output
   needs the second filter because `inputNegate` fires on the filter's own input only.
2. The eye test captures its "before Play" translations AFTER Play has started, so a demo whose first frame has a
   translation animation already off the rest pose reports `restored: false` even though Stop restores correctly
   (`not_restored` was empty). Drive such motion with rotation or scale, or fix the capture order.
3. Importer bakes disabled looping TimeSensors as keyed animations ("play-once, disabled or delayed start is not kept");
   the behaviour graph still switched them on and off correctly.
4. Root rotation read in the act needs the parent's world rotation divided out (the importer's Z-up turn sits at the top).
