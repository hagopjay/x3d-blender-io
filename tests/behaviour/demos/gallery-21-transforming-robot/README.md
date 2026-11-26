# Gallery 21: transforming robot

**Idea.** A plain orange cube sits on a round platform. Click it and it unfolds panel by panel, origami style: two legs
swing down from the sides while the body rises, the front panels swing open into arms and the forearms unfold, the flat
lid on top extrudes into a head, the antenna stands up, the eyes and the chest lamp light (the lamp then pulses), the
robot waves with its right hand, then dances (bounce, twist, arms flapping in turn, head turning, a foot tapping).
Click again and it folds back into the cube.

**Graph.** TouchSensor `Touch` (it senses everything under `Body`, so any panel is clickable) → BooleanFilter `Press`
(`inputTrue`) → BooleanToggle `Flip` → BooleanFilter `Dir`: `inputTrue` → TimeTrigger `GoUnfold`, `inputNegate` →
`GoFold`. `GoUnfold` starts `U1`; each clock's `isActive` → BooleanFilter `EdgeN.inputNegate` → TimeTrigger `GoN+1` →
next clock, so six clocks run end to end (legs 2.2 s, arms 1.8, head 1.2, lights 1.0, wave 2.4, dance 3.0). Stage 1-4
are OrientationInterpolators / PositionInterpolators / BooleanSequencers on the hinge Transforms. The fold is ONE clock
`F` (3 s) → ScalarInterpolator `Rev` (1 → 0) → `set_fraction` of the same stage 1-4 interpolators, so the robot plays them
backwards at once; the wave and dance interpolators start and end at the rest pose so need no reverse. `Flip` also
enables the looping `Pulse` clock for the chest lamp. Hinges nest `Robot > Bounce > Body > ShoulderY > ShoulderZ > Elbow >
Wrist` (seven deep) and `Body > Hip > Knee > Ankle`. 93 nodes, 128 ROUTEs, 69 ROUTE sources, built by `build.py`.
`build.py` also asserts (same maths as the keys) that the feet clear the platform during the leg swing (min ankle height 0.09 m).

**Play.** Import with "Behaviour graph" on, press Play, click the cube; click it again after the dance (about 12 s) to fold.
Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-21-transforming-robot`, Blender 5.3; the eye test's own click, then the act | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| Unfold | world positions of DEF'd objects, sampled on the player clock (`player.now`), 48 samples | body rose 0.78 → 2.66 m, head 2.02 → 4.05 m, wrist reached 2.37 m out from the body and 4.94 m high (the wave); at the end eyes and chest lamp shown |
| Lights and dance | visibility and scale of `Eyes`, `ChestLamp`, world z of `Bounce` | chest lamp scale seen at 27 distinct values 1.01-1.58 (pulse); `Bounce` moved 0.28 m |
| Fold | a real second click (`rig.mouse` on the torso), sampled for 4.6 s | body back to 0.78 m, wrist 0.77 m from the body, eyes and lamp hidden |
| Look | screenshots read by eye (`act-unfold-020`, `-070`, `-unfolded`, `-folded`) | a cube with side panels and flat lid; legs down with the body up; right arm raised in the wave; the folded state is a cube with panel edges, a lamp ring and two orange hands at its sides. The robot is small in the viewport (about a third of its height). |

## Not checked

- Occlusion/intersection mid-transform beyond what the screenshots show (six moments only); the forearm folded onto the
  upper arm and the zig-zag shin are offset in depth by hand and were only eyeballed.
- Clicking **during** the unfold: the toggle flips and the fold would fight the running stages (no lock). Not tested.
- The antenna and the glow are small in the screenshots; the eye colour in solid view is baseColor only.
- X_ITE judging (no `x_ite.json` recorded; this demo is not in `judges`).
- The act's first look at the folded cube is lost: the eye test's click starts the unfold before the act, so the folded
  pose is seen only in the final fold shot and the eye test's own import shots.

## Findings for Loom

1. **One ScalarInterpolator 1 → 0 on a second clock plays any set of interpolators backwards**: a fold costs one
   clock and one interpolator instead of a second chain; it works because several ROUTEs may feed one `set_fraction`.
2. **A TouchSensor placed under a group senses all its nested geometry** in the Blender player, so a click on any panel
   of the folded cube toggles it; sensing only the torso would have been blocked by the arm panels in front of it.
3. **BooleanToggle → BooleanFilter (`inputTrue` / `inputNegate`) → two TimeTriggers** gives a clean click-to-start,
   click-to-reverse switch with no Script.
4. The act's per-sample cost was dominated by scanning `scene.objects` for DEFs on every sample (29 samples in 12 s
   became 48 once the lists were cached); look objects up once.
