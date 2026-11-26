# Gallery 17: ripple city

A 10 x 10 city of towers on a rainbow travelling wave. Heights and colours roll across the grid; one click on the gold
pedestal swaps the ripple that spreads out in rings from the centre for a diagonal sweep from one corner.

## The graph in one paragraph
Towers are grouped into classes: 7 rings by distance from the centre, 19 diagonals by `i + j`. Each class has ONE
PositionInterpolator (its height, sent to the tower's `scale`) and ONE ColorInterpolator (sent to both `baseColor` and
`emissiveColor`), phase shifted by the class index, and each is ROUTEd to every tower of its class, so 100 towers need
52 animations. Two TimeSensors (`ClockA` rings, `ClockB` diagonals) play the two families. The pedestal's TouchSensor
goes through a BooleanFilter and a BooleanToggle whose output enables one clock and disables the other.
256 nodes, 655 ROUTEs, 56 ROUTE sources. Regenerate with `python build.py`.

## How to play it
Start it (Play). It runs by itself (a 6 s wave). Click the gold pedestal in front of the city to flip between rings and
the diagonal sweep; each click flips again. The eye test's own click happens first, so the world is already in the
diagonal mode when the act begins.

## Checked
| Instrument | Result |
|---|---|
| `behaviour_demo.py check` | 256 nodes, 655 ROUTEs, 56 sources; matches demo.json |
| Host-eyes (real Blender 5.3 window) | pass; `not_applied` empty |
| act (reads tower scales from Blender data) | act_ok true. Diagonal mode: 40 distinct poses in 8 s, towers of one diagonal never differ (0.0), diagonals differ by 1.79 (sum of scale). Ring mode: 30 poses, in-ring spread 0.0, between rings 1.81. Back to diagonal: 15 poses in 3 s, spread 0.0 |
| Screenshots (read by eye) | ring mode shows a lit-up hollow wave of tall towers around a low centre; diagonal mode a tilted sweep from low to tall corner; colours differ across the grid |

## NOT checked
- The solid viewport shades the tower sides dark, so the saturated colours show mostly on the tops; the look is less
  vivid than the data (colours are routed to baseColor and emissiveColor) suggests. Not tried in Material Preview or a render.
- The eye test's `moved_while_playing` only watches translation, so it reports nothing for this scale-driven world
  (host-eyes still passes); the act's data check is the evidence of motion.
- Only 2 mode flips and a couple of minutes of run; long-run drift not examined.

## Findings for Loom
- The player applies Transform `scale` through `matrix_basis`; the importer maps X3D y to another Blender axis, so a
  check on `obj.scale.z` sees nothing move. Use an axis-agnostic read (the sum of the components) when watching scale.
- `ModeOut.inputNegate -> ClockA.enabled` plus a direct `toggle_changed -> ClockB.enabled` is enough to hand one
  playback between two clocks, and the newly enabled clock overwrites the interpolators' outputs at once.
