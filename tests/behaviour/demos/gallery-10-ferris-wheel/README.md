# Gallery 10: Ferris wheel

**Idea.** A night-fair wheel. The wheel turns once in 18 s and its twelve coloured cabins stay upright as they ride
round: one OrientationInterpolator turns the wheel, a second one holds the same angles negated, and that single output
is routed to all twelve cabins. 24 rim bulbs chase round (BooleanSequencers on one 1.5 s clock). Click the ticket
booth to stop the wheel and the bulbs; click again to start them.

**Graph.** `Spin` clock → `Turn` → `Wheel.rotation`; → `Level` → `Cab0..11.rotation` (12 ROUTEs from one node).
`Chase` clock → `Flash0..23` (BooleanSequencer, each on for a quarter lap, offset round the rim) → `Bulb0..23.visible`.
TouchSensor `BoothTouch` → BooleanFilter `BoothPress` → BooleanToggle `Halt` → BooleanFilter `Running` → `inputNegate` →
`Spin.enabled` and `Chase.enabled` (the first click sends true, negated it disables). 69 nodes, 68 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play. Click the red booth (right of the wheel). Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-10-ferris-wheel`, Blender 5.3, two real clicks on the booth (the eye test's own click had already stopped it), 15 s | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Stops and starts | the wheel's rotation, sampled 10 times a second | 1 distinct pose while stopped, 90 while running, 1 again after the second click |
| Cabins stay upright | each cabin's world orientation against its first pose, over 9 s of running | turned 0.0 deg at most, while a cabin travelled 8.4 m |
| Bulbs chase | the set of visible bulbs, sampled | 24 different patterns |
| Look | screenshot while running, read by eye | a wheel of 24 rim bars and 12 spokes, 12 coloured cabins hanging upright, an A-frame and the red booth with a yellow roof |

Not checked: X_ITE judging (none); the bulb glow in a rendered view (solid viewport only).

## Findings for Loom

1. **One interpolator output can drive a dozen targets:** twelve ROUTEs from `Level` kept every cabin upright with no
   per-cabin node. The sum of the wheel's turn and the negated turn is exactly zero in Blender (0.0 deg).
2. **A TimeSensor's `enabled` is driven by a ROUTE and obeyed in Play**; stopping and starting a looping clock this
   way works (unlike `startTime` on an active clock, gallery 01).
3. **A DEF'd Transform with many unnamed children: the importer copies the DEF onto every child object** (here 36 objects
   carry `x3d_def = Wheel`). Acts must watch them all, or pick the one that changes.
4. In Blender world space the cabin's local Z is not vertical (the importer rotates for Y-up to Z-up), so "upright"
   has to be measured as no change in world orientation, not as an axis test.
