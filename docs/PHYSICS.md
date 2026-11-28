# X3D RigidBodyPhysics in Blender

The importer makes a file's RigidBodyCollections into Blender's rigid body world, and the X3D 4.0 export writes
Blender's rigid body world back as RigidBodyPhysics. "Rigid body physics" in the import options turns the
import off (``load(physics=False)``, or ``BLENDER_X3D_PHYSICS=0`` for scripts). The physics nodes were the ranked gaps
9, 10, 11 and 25 of [NODE_BOARD.md](NODE_BOARD.md).

- **Code:**
  - `source/physics_model.py`: reads the document, no bpy;
  - `source/physics_blender.py`: makes the Blender side;
  - `source/physics_export.py`: writes it back;
  - the hook is `import_rigid_body_physics` in `source/import_x3d.py`.
- **Instruments:**
  - `tools/physics_record.cjs` (X_ITE);
  - `tools/physics_blender_record.py` (Blender);
  - `tools/physics_judge.py` (the analytic ladder);
  - `tools/physics_receipt.py`;
  - `tools/physics_restitution_sweep.py`;
  - `tools/physics_corpus_sweep.py`.
- **Tests:** `tests/test_physics_model.py` and `tests/test_physics_rigid_bodies_bpy.py`.

**Grades:**
- **C** = measured here (Blender 5.3.0 as the bpy module; X_ITE 16.8.1 in headless Chromium 158 on SwiftShader; one cloud machine, 27 Nov 2026).
- **L** = reasoned.
- **S** = reported elsewhere, not re-run here.

## What maps, and how

| X3D | Blender | Note |
|---|---|---|
| RigidBodyCollection `gravity` | scene gravity, through the import's axis conversion | one rigid body world per scene: a second collection joins the first (loss) |
| `iterations` | solver iterations, and sub-steps so a step lasts 1/(60 x iterations) s | X_ITE 16.8.1 divides each frame into `iterations` sub-steps; at 60 frames a second that is 1/600 s for the default 10. Kept at any frame rate (25 sub-steps at 24 fps) |
| RigidBody `fixed` / `mass` | PASSIVE / ACTIVE with mass | `enabled` FALSE: geometry only (loss) |
| CollidableShape Box, Sphere | BOX, SPHERE | |
| Cylinder, Cone, IndexedFaceSet and the other face sets | CONVEX_HULL; MESH when `convex` FALSE and for ElevationGrid | as X_ITE does |
| several CollidableShapes, or a CollidableOffset | a COMPOUND body: an object at the body's frame with the shapes as rigid children | the holder carries `x3d_rigid_body_holder` |
| CollisionCollection `bounce`, friction | each body gets the **square root** | Bullet multiplies the two bodies' values at a contact; the contact gets the authored value |
| `autoDamp`, damping factors | linear and angular damping, else **0** | Blender's own defaults (0.04, 0.1) would slow every body; a wrong twin proves it |
| `autoDisable`, disable speeds | deactivation | |
| `contactSurfaceThickness` > 0 | collision margin | |
| `linearVelocity`, `angularVelocity` | a breaking MOTOR constraint per direction, to a passive anchor | see "Starting velocities" |
| BallJoint | POINT | |
| SingleAxisHingeJoint | HINGE about the axis, its stops when not -pi..pi | the default range is read as no stop, as ODE and X_ITE read it |
| SliderJoint | SLIDER along the axis, `minSeparation`..`maxSeparation` as limits | |
| DoubleAxisHingeJoint, UniversalJoint | GENERIC: translation locked, the rotation about neither axis locked | motors and suspension: loss |
| MotorJoint | not imported (loss) | X_ITE 16.8.1 has none either |
| ROUTE RigidBody.position / orientation to a Transform | Copy Location / Copy Rotation on the object that stands for the Transform (Child Of with its offset in a flat import) | the usual way a scene shows a body. The ROUTE is no longer an import loss; the body's own collidable becomes a hidden wire stand-in |

**Losses.** Everything a file sets that Blender cannot honour is in the scene's `x3d_import_losses` with kind "physics" and the field named. Examples:
- `preferAccuracy`, `errorCorrection`, `constantForceMix`, `maxCorrectionSpeed`, `disableTime`;
- `centerOfMass`, `inertia`, `useFiniteRotation`, `useGlobalGravity` FALSE, `forces`, `torques`;
- `minBounceSpeed`, slip, surface speed and softness;
- joint stop bounce and error correction.

`X3D_IMPORT_STRICT` does not raise on them: they describe a simulation that runs, not behaviour that was dropped.

### Starting velocities (C)

Blender has no initial velocity for a rigid body.
- **The animated hand-off fails.** A body animated with "Animated" on and then let go starts at rest (measured: 0.0 m/s after a kinematic run-up at 3 m/s).
- **The fix:** the import gives each moving body MOTOR constraints to a passive anchor, which break at exactly the impulse the velocity needs:
  - linear: mass x speed, along the velocity;
  - angular: about each principal axis, its principal moment x that component of the angular velocity, using Bullet's own inertia formulas.

  They act in the first sub-step and are gone.

**Measured:**
- a launch of (3, 0, 4) m/s: (3.000, 0, 4.000) m/s from the first frame;
- 5 rad/s: 5.000;
- with gravity, the body at 0.48 s is where the discrete answer puts a body launched at t = 0, to the 1e-5 m printed.

The anchor and motors are in the collection "X3D physics helpers" and are not exported.

## The ladder (C)

Seven scenes, each with an analytic answer, from x3d.loom's `x3d.physics/rigid-engines` (lib/scenes.js at fc30c89). The measurements are ported unchanged to `tools/physics_judge.py`.

- **Limits:** `tests/physics/limits.json`, committed before the measured run, in the first of this change's commits (sha256 07eb76d0…; the session's commit was f69cb82).
- **Receipt:** `tests/physics/receipts.json`: metrics, verdicts, replays and trace hashes for both engines.
- **Fixed step:** X_ITE is run on a fixed 1/60 s clock by `tools/physics_record.cjs`, the same step as Blender. Its own clock is the frame rate, averaged from zero, so its results depend on how fast the machine draws.

| Scene | Analytic | Blender 5.3 (import) | X_ITE 16.8.1 |
|---|---|---|---|
| free fall, 55 frames | discrete semi-implicit Euler, h = 1/600 | **3.1e-7 m** off | 1.6e-5 m off (float32) |
| drop, bounce 0.5: apex above contact | 1.125 m | **0.008 m** (bounce lost: see below; gate expected to fail) | 0.552 m |
| three-box stack, top height / drift | 2.5 m / 0 | 2.5 / 0.0007 m | 2.5 / 0.0007 m |
| slope 30 deg, mu 0.2: acceleration | 3.19 m/s2 | **3.20** | 2.77 (the standard's spelling: 0.25 a contact); 4.56 with X_ITE's spelling (0.2 squared) |
| pendulum (BallJoint): period error | 0 | **0.20 %** | 0.40 % |
| hinge stop at 1.0 rad: max angle | 1.0 | **1.000** | 3.134 (no hinge stops in X_ITE) |
| slider stop at 1.5 m: max separation | 1.5 | **1.500** | 1.500 |
| billiards, bounce 1: B after / energy error | 3 m/s / 0 % | **3.000 / 0.00 %** | 3.001 / 0.09 % |

- **Gates:** Blender passes 18 of 19, and the one it fails is the one expected to fail. X_ITE passes 16 of 19; it is recorded, not gated.
- **Replays:** each run replays with 0 differing step hashes, Blender in a second import and X_ITE in a fresh page.
- **Wrong twins** (`WrongTwins` in the bpy test): each changes one mapping back to the naive one, and each fails its gate.
  - Blender's default damping fails the pendulum amplitude.
  - Friction given whole to each body fails the slope.
  - No start-up impulse fails the billiards.
  - A hinge without its stop fails the hinge.

## The restitution lottery (C): what Blender cannot do yet

Blender 5.3's solver keeps a bounce only by chance at small steps. `tools/physics_restitution_sweep.py` drops the sphere at the given impact speed through the importer (`tests/physics/restitution_sweep.json`).

Each cell is the effective coefficient against an authored 0.5:

| step | 1 m/s | 2 | 3 | 4 | 6 | 8 | 10 | 12 | 15 |
|---|---|---|---|---|---|---|---|---|---|
| 1/60 s | 0.22 | 0.54 | 0.53 | 0.51 | 0.64 | 0.60 | 0.55 | 0.51 | 0.63 |
| 1/120 s | 0.16 | 0.09 | 0.29 | 0.14 | 0.51 | 0.60 | 0.51 | 0.61 | 0.66 |
| 1/300 s | 0.00 | 0.00 | 0.06 | 0.03 | 0.33 | 0.12 | 0.58 | 0.53 | 0.56 |
| **1/600 s (the import's step)** | 0.00 | 0.02 | 0.00 | 0.04 | 0.03 | 0.04 | 0.00 | 0.31 | 0.53 |
| X_ITE 16.8.1, 1/600 s | 0.30 | 0.26 | 0.41 | 0.37 | 0.28 | 0.39 | 0.30 | 0.41 | 0.28 |

**Neither engine gives 0.5.**
- **Blender** drops the bounce of slow impacts at small steps, and sometimes adds energy. In x3d.loom's Newton's cradle (bounce 1) the first ball climbs to 1.19 m above its rest height after the impacts, against 0.71 m at release (one run, no gate).
- **X_ITE** bounces at every speed, near the square of the authored value plus noise.
- **Why (L):** in Bullet a contact gets restitution only in its first steps. At small steps the contact already exists, still separated, a step or more before the impact (Bullet's contact threshold is a couple of centimetres). The 1/600 s import step and Blender's collision margin (0 to 0.01 tried) changed nothing.
- **Not attempted:** a per-scene coarser step; it would not give 0.5 either (first row).

**Status:** an open limitation, written as a gate expected to fail (`drop-bounce.x3d`, `expect: fail`). If Blender changes, the test says so.

## What X_ITE 16.8.1 does with RigidBodyPhysics (C, read in its source and measured)

- **The step:** 1/max(10, frame rate), averaged over 15 frames from 0 (`RigidBodyCollection.getTimeStep`), cut into `iterations` sub-steps. The physics depends on how fast the browser draws. `tools/physics_record.cjs` replaces `getTimeStep` and steps the collections itself.
- **Leak:** the collection had registered its own update before the scene went live, so it was taken off first (`registered_before_live` in the trace).
- **Squared coefficients:** `bounce` and the friction coefficient are set on every body, and Bullet multiplies them: bounce squared, friction squared. Without the friction parameter, each body has 0.5 (0.25 a contact). Measured: 4.56 m/s2 on the slope = g (sin 30 - 0.04 cos 30).
- **Spelling:** X_ITE reads only `"FRICTION_COEFFICIENT_2"`.
- **No hinge stops:** SingleAxisHingeJoint is a btHingeConstraint with no limits; `minAngle`/`maxAngle` are not read.
- **Collidables are not drawn:** a CollidableShape that is only a RigidBody's geometry is not drawn (RigidBodyCollection is not a grouping node). Scenes show a body through a Transform and a ROUTE, which the import now follows.

## Two things to report upstream (C)

1. **The friction parameter has two spellings in Web3D's own material.**
   - **Hyphen:** the standard's text and the X3D 4.0 XSD documentation write `"FRICTION_COEFFICIENT-2"`, `"SPEED-1"` and `"SLIP-1"`.
   - **Underscore:** the X3DUOM-generated tools (x3d.py 4.0.65.8, X3DJSAIL) and X_ITE write `"FRICTION_COEFFICIENT_2"`.

   The import reads both. The export writes the underscore form, which x3d.py's validation accepts and X_ITE reads. The XSD does not check MFString values.
2. **x3d.py 4.0.65.8 refuses any CollisionCollection with two applied parameters.** It checks the whole MFString `'"BOUNCE" "FRICTION_COEFFICIENT_2"'` against the single-value choices. The export's semantic check now checks such a field value by value (`source/validate.py`, `_each_enumeration_value_valid`), and a wrong value is still refused (test).

## The export (C)

- **Round trip:** import, X3D 4.0 export (the schema and x3d.py checks run inside the export), import again. The ladder metrics are identical on all seven scenes (`RoundTrip`).
- **What is written:** one RigidBodyCollection with one CollisionCollection, a RigidBody per body at its starting pose (the object's own location and rotation, which the simulation does not change), collidables from the collision shapes, the joints, and the ROUTEs to the Transforms that show the bodies.
- **In X_ITE:** the exported scenes play without errors, with X_ITE's own behaviour (no hinge stop, squared friction). Unlike the fixtures, they are drawn, because the ROUTEs drive visible Transforms.

## Real scenes (C)

`tools/physics_corpus_sweep.py` ran over every `.x3d` of hagopjay/x3d.demo (19608b7) and hagopjay/x3d.loom (fc30c89) that names RigidBodyCollection: 79 files, 74 with bodies (`tests/physics/corpus_sweep.json`).

| Measure | Result |
|---|---|
| Imports finished | 79 of 79 |
| Bodies / joints / start-up motors | 1,888 / 592 / 114 |
| ROUTE-following constraints | 1,751 |
| Importer errors | 0 |
| Bodies non-finite or past 1e6 m after 2 s | 0 |
| Physics losses reported | 56 |
| ROUTE losses left | 11 (routes that are not body-to-Transform) |

The losses, by kind:
- `minBounceSpeed` and `preferAccuracy`: 16 files each;
- collection `enabled` FALSE: 4;
- `disableTime`: 4;
- MotorJoint and `useGlobalGravity` FALSE: 2 each;
- the ODE-only fields of the PhysX bridge's experiment;
- one DoubleAxisHingeJoint's motors.

The largest, Flop Lab's default level (255 bodies, 182 joints), imports and runs its 2 s in 23 s; the Galton board (249 bodies) in 26 s.

**Film:** `demo-avalanche.x3d` (45 bodies into a funnel), X_ITE on a fixed clock against Blender with the import, rendered with Cycles: `avalanche_xite_vs_blender.mp4` (in the PR, not in the repository).

## Not done

- A momentum-aware balance or contact witness. The ladder has no test of rolling, spinning tops or stacking under impact.
- Per-body friction in X3D: one CollisionCollection per collection. The export writes the median contact value and says so.
- CollisionSensor still reads bounding boxes (unchanged, `behaviour_play`).
- Constraint motors, MotorJoint, `forces`/`torques`, per-body gravity off.
- The node board was not re-probed: its probe needs the x3d_mcp XSD. After merging, `tools/node_board_probe.py` should move:
  - RigidBodyCollection, RigidBody, CollidableShape, CollidableOffset, CollisionCollection and the four joints to `builds` (read);
  - them and BallJoint, SingleAxisHingeJoint and SliderJoint to `observed` (written).
- A real GPU, another machine, Blender 4.5 LTS.

## Integration with the node board's batches 6 and 7 (28 Nov 2026)

Main took #126 (batches 2 to 8) after this work was cut, and #126 already imported and wrote rigid bodies and joints as Blender constraints, as field records without a simulation model. Both ran on the same file and every body was made twice. The rule now:

- **Import:** `source/physics_blender.py` is the default. #126's importer (`import_rigid_bodies`) runs only with `BLENDER_X3D_PHYSICS=legacy`. `load(physics=False)` keeps only the geometry, as this document says.
- **Export:** a scene the legacy importer made (it carries `x3d_rigid_world`) keeps #126's writer. Every other rigid body world goes through `physics_export`, and the batch 6 and 7 per-object records stand down.
- **Tests:** `test_node_board_batch6_bpy.py`, `test_node_board_batch7_bpy.py` and `test_rigidbody_physics_import_bpy.py` run under `legacy`. Three tests that build bodies in Blender state the new writer's behaviour: numbers are written in their shortest spelling, a scaled body keeps its scale inside the collision shape, a bare GENERIC constraint made in Blender has no X3D joint, and the CollisionCollection's list is empty (the shape sits in the RigidBody's geometry; X_ITE 16.8.1 collides by geometry, which reading of the standard is intended is a held question for Web3D).

### What the 195-case export suite found (C: Blender 5.2.2 binary, bpy 5.1.2 and 5.3.0 wheels, x3d.py 4.0.65.8, SaxonC-HE 13.1.1; 28 Nov 2026)

The suite's Z13 scene has a ground and a ball that are rigid bodies, and the ball also has keyframes. It reached three defects the kit's seven fixtures did not:

1. **The import un-parented every Shape of the file**, not only the shapes of bodies, so the suite's collection instance (Z09) lost its hierarchy: 26 extra Transforms against a budget of 2. Now only shapes inside a RigidBodyCollection are un-parented (`test_the_shapes_that_are_not_bodies_keep_their_parents`).
2. **A body's hidden wire stand-in was written as a Transform of its own**, so each round trip added one (E1 to E2 did not converge: 33 differences). Stand-ins (`x3d_collidable_only`) are now written only in their RigidBody (`test_a_body_stand_in_is_not_written_as_a_transform`). With this, E1 to E2 is 0 in all three profiles.
3. **A Shape's object that the importer had removed made the physics import raise `ReferenceError`**, which the guard swallowed, so on the suite nothing was imported and the round trip silently lost the world. Removed objects are now left out.

Also: `rigidbody.constraint_add` under `temp_override(object=...)` ignores the object on Blender 5.1.2 (it acted on the active object, and the next line segfaulted); the empty is now made active as well. One f-string had a backslash, which Python 3.11 refuses.

### Accepted changes to the committed budgets (documented here, not hidden)

- `tools/io_sync/first_trip_budget.json`, profile main: the ball is a rigid body with keyframes. After the import its follower is both keyed and constrained to the body, so the re-export bakes the combination: one more OrientationInterpolator, one PositionInterpolator whose keyValue differs, ROUTE counts up by 2 to 4 (positions shift as four body ROUTEs now sit in the list). It converges in one trip. Lines that could shrink were left as they are: the suite's meshes are not byte-stable between runs, so tightening them would flake.
- `tools/io_sync/invariant_budget.json`, profile main: the same baked ball, two PositionInterpolator and one OrientationInterpolator route (and their TimeSensor routes) gained. No RigidBody route is lost.
- `tools/schematron/disagreements.json`: the Web3D Schematron's Viewpoint rule counts component statements; the suite now declares RigidBodyPhysics, so "3" becomes "4" (crease, main) and "4" becomes "5" (x41). Same count (7), same grade.
- `mapping/x3d_fields.json` and `docs/MAPPING.md`: 15 attributes of RigidBodyCollection, RigidBody and CollisionCollection, Sphere radius and Box size written by the export now have rows (regenerated by `tools/mapping/build_mapping.py`).

### Known asymmetry (Suspected, not changed here)
A body no ROUTE shows (the ground in a typical file) is drawn after the import, because Blender draws every rigid body, so the first re-export writes it as a Transform with its shape as well as a RigidBody. X_ITE 16.8.1 does not draw a collidable that is only a body's geometry, so the file looks different after one round trip.

