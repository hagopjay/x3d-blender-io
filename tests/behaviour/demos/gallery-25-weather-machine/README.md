# Gallery 25: weather machine

**Idea.** A small island (house, five pines, a lighthouse) in a sea, under a sky you control with four buttons on a panel in
front: **RAIN**, **SNOW**, **STORM**, **SUN**. Exactly one weather runs at a time (a green pilot lamp shows which).
RAIN: 60 blue streaks fall past the island on three clocks while 18 splash rings pulse on the grass; clouds swell and grey.
SNOW: 36 flakes drift down on sway paths, the grass and both roof boards fade to white. STORM: the clouds swell to twice
their size and go near black, the sky goes violet, three lightning bolts, a white back plate, a white-out strip and a
point light flash in a pattern, and a beam sweeps round from the lighthouse. SUN: the clouds shrink to white puffs, the
sky clears, a sun with turning rays shows, four birds with flapping wings fly across, and a rainbow of seven arcs is drawn
one arc after another.

**Graph.** Per button: `TouchSensor` -> `P` (BooleanFilter on `isActive`). `P.inputTrue` -> its own gate `G.set_boolean`
(true), -> `N` (BooleanFilter) whose `inputNegate` (false) goes to the other three gates, and -> a `TimeTrigger` that
starts a 0.8 s one-shot clock. `G.inputNegate` -> `H` -> `H.inputNegate` is the weather's state: it goes by ROUTE to the
`enabled` of that weather's clocks (RAIN: `RainA/B/C` 0.9, 1.1, 1.3 s and `SplashClk`; SNOW: `SnowA/B` 7 s and 9 s;
STORM: `StormClk` 8 s and `SweepClk` 4 s; SUN: `SunSpin`, `BirdClk`, `FlapClk`), to the group Transform's `visible`, and to
the pilot lamp's `visible`. Fall paths: 12 shared PositionInterpolators for the 60 drops (3 clocks x 4 phases of the same
fall, built as a looping sawtooth shifted by a quarter cycle), 8 for the 36 flakes (2 clocks x 4 phases), 4 scale
interpolators for the 18 splashes. The one-shot clock of each button drives a `ScalarInterpolator` that holds that
weather's number (0, 1/3, 2/3, 1) and sets the fraction of eight shared interpolators whose four keys are rain, snow,
storm, sun (ground, roof, leaf, sky, sea and cloud colours, sun light colour, cloud scale); a ColorChaser or PositionChaser
(2.5 s) after each smooths the change into the materials, the DirectionalLight and the five clouds' `scale`. STORM:
three BooleanSequencers on `StormClk` give the flashes. SUN: a one-shot `Reveal` clock and seven BooleanSequencers show the
arcs; a falling `inputFalse` edge of the storm and sun state hides the flash plates, bolts, light and arcs when their
weather ends. 267 nodes, 323 ROUTEs, 106 ROUTE sources, built by `build.py`; procedural only.

**Play.** Import with "Behaviour graph" on, press Play, click the four round buttons on the panel (left to right: RAIN,
SNOW, STORM, SUN; the sun is the yellow one). Clicking the weather already on does nothing visible. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Contract | `tools/behaviour_demo.py check gallery-25-weather-machine` | 267 nodes, 323 ROUTEs, 106 ROUTE sources = `streams` |
| Live window | `tools/behaviour_demo.py show gallery-25-weather-machine`, Blender 5.3 | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Rain (pressed 2 times) | Blender data after 3 s + 5 s of player clock: objects with `x3d_def` `DropN`, `SplashN` | 60 of 60 drops shown and moved in a 0.9 s window; 18 of 18 splash rings shown and scaling; flakes, birds, arcs, flash plates all 0 |
| Snow | same, `FlakeN` | 36 of 36 flakes shown and moved; drops 0; the grass `Base Color` read (0.95, 0.97, 1.0) and the roof (0.96, 0.97, 1.0) |
| Storm | same, 9 s watched | flash plates and bolts: up to 3 shown at once (back plate, white-out strip and the big bolt), none in any other weather; the beam's `BeamArm` had 36 distinct poses; cloud world scale 2.0; grass (0.12, 0.28, 0.14) |
| Sun | same, 5 s after 3.2 s | 7 of 7 arcs shown; 4 of 4 birds shown and moving; cloud scale 0.45; grass (0.3, 0.65, 0.25) |
| Exactly one | after each press: pilot lamps shown | exactly the pressed weather's lamp; every other weather's counters were 0 in all five presses (SNOW, RAIN, STORM, SUN, RAIN) |
| Look | screenshots `act-*.png` read by eye | sun state: blue sky, rainbow behind the island, sun with rays, birds, small white clouds. Rain: blue streaks over a grey sky. Storm: violet sky and black clouds. Snow: the island and roofs white. |

## Not checked

- X_ITE judging: none (`judges` is empty; no trace recorded).
- The solid viewport shows `baseColor`, ignores scene lights and draws transparency opaque: the PointLight's flash is not
  visible, only the white plates. The eye test's selection outline covers small things (drops, birds, splashes); the rain
  streaks read as blue dashes. I did not catch a flash frame in a screenshot (shots were not timed to a flash); the data
  (up to 3 plates shown at once) is the evidence.
- The scene is small in the harness window: the 16:9 camera frame inside a wide 3D view leaves the island at about 40 % of
  its width. A larger window would show it better; the Viewpoint is `fieldOfView 0.95` from (0, 5, 19.5).
- The splash rings are flat discs at the ground, hard to see from this camera.
- The first press is made by the eye test before the act; I read the weather then (RAIN) rather than assuming it.
- Pressing a button during the 0.8 s tone change of another, or two buttons within a tick, was not tried.

## Findings for Loom

1. **`visible="false"` on a group Transform is not applied at import**, only on shapes (`PilotRain` and the flash plates
   were hidden, `RainGrp`, `SnowGrp`, `StormGrp` and `BoltA..C`, which have children, were not: the importer's
   `made_before` test skips an Empty that a child already made). So at Play start every weather showed at once. Workaround
   used here: a 100000 s looping `Boot` clock sends one `false` through a BooleanSequencer to the idle groups.
2. **Showing a group shows everything under it** (`_show` recurses): a child with its own `visible="false"` is un-hidden
   when its parent is shown. Elements that need their own visibility (flash plates, bolts, arcs) must sit outside the
   toggled group.
3. **`BooleanFilter.inputFalse` carries `false`** (not `true`), as in the spec; so `inputFalse` is the "just turned off"
   edge as a false event and can go straight to `visible`. `inputNegate` of a true is the way to make a false from a press.
4. **A ROUTE from one clock-state to several `enabled` fields plus `visible` is a cheap mutual exclusion:** 4 weathers x
   (P, N, G, H) filters and 12 clock ROUTEs, no Script.
5. **A constant-per-weather table through a `ScalarInterpolator` selector** (one-shot clock -> const value -> `set_fraction`
   of a 4-key interpolator -> chaser) gave eight smooth fades from one press with 8 interpolators instead of 4 x 8.
6. A USE'd `Appearance` shares one DEF'd material node for the ROUTE: the roof colour read from `RoofL` went white in SNOW, and the same ROUTE targets `RoofR`, the trees and the cloud puffs by USE (I read only `RoofL`, the grass and the cloud scale from Blender data, not each tree).
7. A Transform holding only a `Shape DEF=...` collapses into the mesh object and the mesh takes the Shape's DEF
   (`Splash0` became `SplashShape`): wrap the first, DEF'ing shape in an extra Transform to keep the Transform's DEF.
