# Gallery 02: disco floor

**Idea.** An 8x8 floor of 64 tiles. One 6 s clock sends a rainbow ripple out of the centre; each tile hops as the wave
passes; a mirror ball turns; the camera orbits the floor; click the red DJ deck for a strobe light.

**Graph.** One looping TimeSensor `Beat`. Each tile has a ColorInterpolator (24 keys, hue lagging by distance from the
centre) into the tile's `emissiveColor` and `baseColor`, and a PositionInterpolator (the hop) into its `translation`.
A 24 s `Orbit` clock drives a PositionInterpolator and an OrientationInterpolator (a look-at at every key) into the
Viewpoint's `position` and `orientation`. `BallClock` → OrientationInterpolator → the ball's `rotation`. TouchSensor
`DeckTouch` → BooleanFilter → BooleanToggle → PointLight `Strobe.on`. 268 nodes, 329 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play. The camera orbits by itself; click the deck when it comes into
view. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-02-disco-floor`, Blender 5.3, real click on the deck | Host-eyes **pass**; `act_ok` true: 36 of 64 tile heights changed, the first row's colours changed, the camera moved 7.9 m, strobe on; `not_applied` empty |
| Look | screenshot read by eye (solid viewport): a rainbow diamond of tiles, ripples visibly offset, ball and red deck | tiles read as colour only because `baseColor` is routed too |

Not checked: X_ITE judging (none; `streams` is the ROUTE-source count); how the strobe looks in a rendered view.

## Findings for Loom

1. **Solid viewport shows `baseColor`, not `emissiveColor`.** First run routed only `emissiveColor` and every tile
   looked black in the default solid view. Routing the same ColorInterpolator to `baseColor` as well makes Play visible.
2. **Eye test records the "before" pose after Play starts.** The restore check compares against the first applied
   frame, not the bind pose, so a Viewpoint whose bind pose differs from the interpolator's first key reports "not
   restored" although Stop did restore the bind pose. The demo sets the bind pose equal to key 0. (`not_restored` is
   empty, `restored` false: the two use different baselines.)
3. A camera that orbits means the clickable deck is often off screen: the act polls `rig.screen_point` until it is in view.
