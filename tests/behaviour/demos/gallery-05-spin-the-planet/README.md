# Gallery 05: spin the planet

**Idea.** Grab a blue planet and spin it. Five moons, each behind its own OrientationChaser (0.4 s to 4 s), swing round
after it: the near fast moon keeps up, the far slow one trails and catches up seconds later. The sun cycles colour,
the moons tumble, sixteen stars twinkle, and a golden ring appears while you hold the planet.

**Graph.** SphereSensor `Spin` (`autoOffset`) `rotation_changed` → the planet's `rotation` and five OrientationChasers
`Swing0..4` (`duration` 0.4, 0.9, 1.6, 2.6, 4.0) `set_destination` → arm Transforms `Arm0..4` `rotation` (each holds a
moon at its own radius, 2.1 to 5.3). `Spin.isActive` → `Ring.visible`. Per moon a looping TimeSensor → OrientationInterpolator
→ the moon's own `rotation`. A 12 s sun clock → ColorInterpolator → the sun light's `color` and its material. Sixteen
TimeSensor → BooleanSequencer → star `visible`. 80 nodes, 58 ROUTEs, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play, press on the planet and drag. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-05-spin-the-planet`, Blender 5.3, a real press and 40-move drag, then release | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Chaser lag | angle between each arm's orientation and the planet's, read from Blender objects 1.3 s after release | share of the gap closed: 1.00, 1.00, 0.96, 0.55, 0.27 for durations 0.4 to 4.0 s (monotone); all gaps 0.0 deg after a further 4.5 s |
| Look | screenshot mid-drag, read by eye | blue planet with green continents, the ring glowing round it, moons spread on wires |

Not checked: not judged against X_ITE here (SphereSensor and OrientationChaser are covered by other demos and the judge).

## Findings for Loom

1. **Sensor to many chasers is a one-ROUTE-per-follower fan-out** and gives a free "trailing" effect; settle time scales
   with `duration` as expected.
2. The sun's `color` ColorInterpolator drives a light and a material from one clock: both apply in Play.
3. Acts that compare orientations should use quaternion `rotation_difference`, not Euler components.
