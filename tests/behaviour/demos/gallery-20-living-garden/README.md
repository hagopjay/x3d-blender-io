# Gallery 20: living garden

**Idea.** Four brown seed mounds on a lawn. Click one and a plant grows from it: the stem shoots up with a small
overshoot, two leaves unfurl, the bud rises and opens eight petals while its colour goes from bud green to the flower's
own (red, yellow, pink, violet). Each mound is its own chain, so the garden fills as you click. Meanwhile two bees (wings
on a 0.14 s clock) and two butterflies (0.55 s clock) fly looping paths, two clouds drift, and a 30 s day clock goes
noon, golden hour, dusk, night, dawn: it tints the sun light, a sky backdrop and the grass, and at dusk eight fireflies
wander and blink.

**Graph.** Per mound: `TouchSensor` → `BooleanFilter` → `TimeTrigger` → a 5 s `Grow` clock → six interpolators (stem
scale, head rise, leaf scale fanned to two leaves, bud scale, ONE `OrientationInterpolator` `Open` fanned to all eight
petals, one `ColorInterpolator` `Bloom` fanned to the eight petal materials' `baseColor` and `emissiveColor`). Flyers:
a clock → a 29-key PositionInterpolator and OrientationInterpolator (look-at heading) → the body; a fast clock → two
mirrored OrientationInterpolators → the wings. `Day` clock → three ColorInterpolators (sky, sun, grass) and eight
`BooleanSequencer`s (set_fraction from the same clock) → each firefly's `visible`; each firefly also has its own
wander clock and PositionInterpolator. 205 nodes, 228 ROUTEs, 96 ROUTE sources, built by `build.py`; no assets.

**Play.** Import with "Behaviour graph" on, press Play, click the brown mounds (the sensor is on the mound; once a
plant is growing a second click on it does nothing). Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Contract | `tools/behaviour_demo.py check gallery-20-living-garden` | 205 nodes, 228 ROUTEs, 96 ROUTE sources = `streams` |
| Live window | `tools/behaviour_demo.py show`, Blender 5.3; the eye test pressed mound 0, the act pressed mounds 1 and 2, mound 3 left alone; 146 s watched | Host-eyes **pass**; `act_ok` **true**; `not_applied` empty, `not_simulated` empty |
| Growth | stem scale read from Blender | clicked 0, 1, 2 went 0.01 → 1.0; unclicked 3 stayed 0.01; petal pose changed on 0, 1, 2 and not on 3; head heights 2.75, 3.45, 2.55 (3 stayed at 0.17) |
| Flyers | positions and wing poses sampled each 0.1 s step | all four flyers covered 10.3 to 12.4 m; 129 distinct wing poses |
| Dusk | count of visible fireflies | up to 6 of 8 showed at once |
| Look | the act's screenshots read by eye | lawn, brown mounds, three grown flowers with petal discs, bees and butterflies over them, clouds, sky switching between pale blue, tan and dark blue across shots, tiny yellow firefly dots at night |

**Not checked / not confirmed.** The solid viewport draws every object with the eye rig's orange selection outline, so
true petal colours are hard to read: the red and violet flowers look right, the yellow one reads olive in stills, and I
did not confirm the pink. The sky is a backdrop box, not the Background node, so a strip above the camera frame shows
Blender's own viewport colour. Scene lights are ignored by the solid view, so the sun tint is only seen through the
colours routed to the materials (the DirectionalLight colour is routed but its effect was not looked at). X_ITE was not
run. The wings are thin boxes, so the flap reads in the data (129 poses) more than in a still.

## Findings for Loom

1. **One interpolator fanned to many nodes works live**: a single `OrientationInterpolator` drove eight petal
   rotations and a `ColorInterpolator` sixteen material fields without any slowdown; the whole 205-node scene ran its
   act in 146 s wall clock for 40 s of ticks (the player's step is about 0.36 s here).
2. **`BooleanSequencer` driven by a looping clock's `fraction_changed`** (not a trigger) gives time-of-day-gated
   behaviour (fireflies blink only between fraction 0.46 and 0.88) with no extra trigger nodes.
3. **The eye test's click lands on the first sensed mesh (mound 0)**, so the act cannot assume mound 0 is still
   unplanted; it leaves a different mound (3) as the unclicked control.
4. **A background colour cannot be animated by ROUTE** (`skyColor` is an MFColor); the demo tints a backdrop box's
   material instead.
