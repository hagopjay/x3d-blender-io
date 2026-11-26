# Gallery 04: jellyfish swarm

**Idea.** A glowing lure you drag with the mouse, and ten jellyfish that follow it, each at its own catch-up speed,
so the swarm trails, bunches and tangles. Each jelly pulses its bell, sways its tentacles and glows on its own clock.

**Graph.** PlaneSensor `Drag` (limits ±4.5 x ±2.4, `autoOffset`) → the lure's `translation` and, in parallel, the
`set_destination` of ten PositionChasers `Chase0..9` (`duration` 0.7 s to 3.4 s) → each jelly's inner Transform
`translation`; each jelly sits in an outer Transform that holds its static offset from the lure. A looping TimeSensor per
jelly (1.4 s to 2.9 s) drives a PositionInterpolator into the bell's `scale` (the pulse), an OrientationInterpolator into
the tentacle group's `rotation` (the sway) and a ColorInterpolator into the skin's `baseColor` and `emissiveColor`.
`Drag.isActive` → PointLight `LureLight.on`. 93 nodes, 92 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play, press on the lure and drag. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-04-jellyfish-swarm`, Blender 5.3, a real press-and-drag (60 pointer moves in a loop) through the event queue, then rest | Host-eyes **pass**; `act_ok` true: all 10 jellyfish moved, the lure travelled 3.0 m; `not_applied` empty. The eye test's own drag step also turned the tentacle groups |
| Look | screenshot at 45 of 60 drag moves, read by eye | ten bells with tentacles bunched round the lure, offset along the path it just took |

Not checked: not judged against X_ITE (the PositionChaser and PlaneSensor are judged by other demos); I did not compare
each jelly's lag to the chaser's `duration` numerically (the numbers printed in `act_numbers` show lag at release 0.8 to
2.4 m, mixed across jellies because their fixed offsets differ).

## Findings for Loom

1. **A chaser per follower is the cheap way to "lag".** Ten different `duration`s on one `translation_changed` event give
   an organic swarm with no Script; the offset lives in a static parent Transform.
2. **Importer names:** the nested Transforms come out as `Transform`, `Transform.001`, ... while the DEF'd lure is
   `Lure.001`; find objects by `x3d_def` (the act does), not by name.
3. Viewport solid shading shows `baseColor`: glow is routed to both `baseColor` and `emissiveColor` (see gallery 02).
