# Gallery 11: day-night village

**Idea.** A diorama on a 24 s day. A sun and a moon ride opposite ends of one rotating arm; the sun light cools from white
through orange to deep blue; 24 windows in 12 houses switch on one by one at dusk and off at dawn; 20 stars come out;
a three-car train circles the village and its headlight burns at night. No clicks: the day just runs.

**Graph.** `Day` clock → `Sky` (OrientationInterpolator) → `SkyArm.rotation`; → `SunTint` (ColorInterpolator, 9 keys) →
DirectionalLight `SunLight.color`; → 24 `LampN` and 20 `TwinkleN` BooleanSequencers (each on at its own time between
0.25 and 0.40 of the day and off between 0.62 and 0.74) → `WinN.visible` and `StarN.visible`; → `Beam` → PointLight
`Headlight.on`. A 12 s `Lap` clock → three (PositionInterpolator, OrientationInterpolator) pairs, each lagging the
last by 3.5 % of the lap → `Car0..2`. 105 nodes, 106 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play and watch one day. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-11-day-night-village`, Blender 5.3, 26 s watched, sampled 10 times a second | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| The day | visible windows, stars, the light's colour, the sky arm's pose, the first car's world position | windows lit 0 to 24 with 45 switch-on events (24 at dusk, more as the 26 s watch ran into the next dusk); stars 0 to 20; 28 different light colours; 41 arm poses; the train spanned 16.3 m |
| Look | screenshots at 14 s and 18 s, read by eye | the village of 12 houses with a sun or moon sphere crossing above; **the day-night mood does not show**: the solid viewport uses Blender's own lighting, not the scene light, and the small window boxes are lost under the selection outline. The data is the evidence here. |

Not checked: how it looks in a rendered view (the light colours would show there); X_ITE judging (none).

## Findings for Loom

1. **Light `color` from a ColorInterpolator is applied** in Play (28 distinct values seen on the light data), but the
   solid viewport does not show it. A demo whose point is light needs a material-preview or rendered viewport to look right.
2. **Many BooleanSequencers on one clock is a cheap scheduler:** 44 of them with different on/off times gave a staggered
   dusk with no triggers.
3. The eye test's selection outline hides small emissive shapes in its screenshots (see gallery 08).
