# Gallery 13: countdown launch

**Idea.** Click the red button. A seven-segment display counts 9 down to 0 while eight pad lamps blink faster and faster;
the count ends and the rocket lifts off with a flickering flame, twelve smoke puffs appear one after another, and the
camera shakes and tilts up to follow it.

**Graph.** TouchSensor `ButtonTouch` → BooleanFilter `Press` → TimeTrigger `GoCount` → `Count` (10 s). `Count.isActive` →
BooleanFilter `CountDone` → `inputNegate` (true when the count ends) → TimeTrigger `GoFly` → `Fly` (6 s). The digit is
seven BooleanSequencers `Showa..g` on `Count.fraction_changed`, each on during the seconds whose digit uses its segment
→ `Sega..g.visible`. Eight `BlinkN` sequencers (blink times bunch toward the end) → `LampN.visible`. `Fly` →
PositionInterpolator `Lift` (an accelerating curve) → `Rocket.translation`; `Count` → `OnPad` (constant) → the same field, so
a launch always starts from the pad; a fast `Shake` loop → `Rocket.rotation`; `Fly.isActive` → `Flame.visible`, a
`Flicker` loop → `Flame.scale`; twelve puffs, each with Position, scale and BooleanSequencer on `Fly`. The camera:
`Fly` → `CamFly`, `CamTilt` → Viewpoint `position` and `orientation` (shake growing, tilt following the rocket);
`Count` → `CamHome` (constant), so a second run starts from home. 99 nodes, 125 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play, click the red button (right of the pad). Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-13-countdown-launch`, Blender 5.3, the eye test's own click on the button, then 190 samples 0.1 s apart (nominal 19 s) | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Countdown | the seven segments decoded to a digit at every sample | 9, 8, 7, 6, 5, 4, 3, 2, 1, 0, in order, each once |
| Launch | rocket height, flame, smoke, camera | rocket reached 31.4 m; the flame showed only in the flight; all 12 puffs showed at once; the camera tilted 0.74 rad and moved 0.57 m; pad lamps changed state 176 times |
| Look | screenshots at samples 70 and 110, read by eye | the rocket in the air with a flame cone, grey smoke lumps on the pad, the camera tilted up, the display slab dark after the count. The rocket is small in frame. |

Not checked: a **second launch** (after the flight the camera looks up and the button is out of view, so the act cannot
click it; the `OnPad` and `CamHome` resets are in the graph but untested live); X_ITE judging (none). The act's sample
spacing is a nominal 0.1 s: the flame showed from sample 45 to 72 although a flight is 6 s, so the samples are not
exactly wall-clock seconds (Blender's `yield` timing is loose); the numbers above count samples.

## Findings for Loom

1. **A chain of TimeSensors plus `inputNegate` (gallery 03) launches a staged sequence from one click**, here
   count then flight, and a constant interpolator on the earlier clock is a clean way to reset targets for a rerun.
2. **Seven BooleanSequencers decode a countdown digit** with no Script: a segment's `key`/`keyValue` is just "on during
   these seconds".
3. The act's `yield 0.1` is not a reliable 0.1 s; a demo that must check timing should read the simulator's clock
   (`ctx["player"].now`), not count yields.
