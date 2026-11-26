# Gallery 09: clockwork bird

**Idea.** A brass bird flies a banking figure-eight round a clock tower on a 12 s loop; its wings flap on
SquadOrientationInterpolators; its wind-up key turns; two gears with teeth mesh and turn; the tower's clock hand ticks.
Click the music box and its lid lifts and three golden notes float up.

**Graph.** `Fly` clock → PositionInterpolator and OrientationInterpolator (73 keys each; the heading follows the velocity
and banks into the turn) → the bird's `translation` and `rotation`. `Wingbeat` (0.5 s loop) → two
SquadOrientationInterpolators `FlapR` and `FlapL` (mirrored) → `WingR`/`WingL` `rotation`. `Wind`, `Tick` clocks →
OrientationInterpolators → key, hand and gears. TouchSensor `BoxTouch` → BooleanFilter → TimeTrigger → 2.4 s
`Tune` clock → lid rotation, three note PositionInterpolators and `Tune.isActive` → the notes' `visible`.
31 nodes, 30 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play, click the red music box (right of the tower). Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-09-clockwork-bird`, Blender 5.3, a real click on the box, 15 s watched | Host-eyes **pass**; `act_ok` true: the bird covered 10.1 m across its loop, both wings took more than 100 distinct poses, the gear 126, all three notes showed; `not_applied` empty (the Squad is simulated and shown) |
| Look | screenshot at 7 s, read by eye | tower and music box on grass; the bird up left, banked with wings out; the gear's ring of teeth. The wing bars are thin and the selection outline clutters the bird, so the flap reads in the data (136 poses), less in a still |

Not checked: X_ITE judging (none); whether the Squad's flap path matches X_ITE's (judged elsewhere).

## Findings for Loom

1. **SquadOrientationInterpolator drives Transform rotation live** in Play (`not_applied` empty) and appears as a node.
2. The eye test's own click presses the music box (the first sensed mesh) a moment before the act: the notes were
   already up, and the act's own click lands while `Tune` is still active, where `startTime` is ignored (see gallery 01).
3. Same as gallery 03: a DEF'd Transform's unnamed child carries the DEF too, so watch every object with that DEF
   (taking only the first one showed a wing that never moved).
