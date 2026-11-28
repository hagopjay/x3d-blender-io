# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D RigidBodyPhysics as a Blender rigid body world (``physics_model`` reads the document; this makes the Blender side).

What maps, and how (docs/PHYSICS.md has the measurements):

* **World.** Gravity (through the import's axis conversion), solver iterations = ``iterations``, and sub-steps chosen so a
  step lasts 1 / (60 x iterations) s whatever the scene's frame rate: the step X_ITE 16.8.1 takes at 60 frames a second
  (it divides each frame into ``iterations`` sub-steps). Free fall then matches the discrete answer of semi-implicit Euler
  at that step in both (measured). One world per scene: a second collection's bodies join the first one's world.
* **Bodies.** ``fixed`` is PASSIVE, the rest ACTIVE with ``mass``. Box and Sphere are Blender's BOX and SPHERE; every other
  geometry is its convex hull, or the mesh itself when the geometry says ``convex FALSE`` (ElevationGrid always), as
  X_ITE does. Damping is ``linearDampingFactor`` / ``angularDampingFactor`` when ``autoDamp`` is TRUE and none otherwise
  (Blender's own defaults, 0.04 and 0.1, would slow every body). ``autoDisable`` is Blender's deactivation.
  ``contactSurfaceThickness`` is the collision margin when it is not 0.
* **Contacts.** Each body gets the square root of the collection's bounce and friction (see ``physics_model``), because
  Bullet multiplies the two bodies' values at a contact.
* **Starting velocity.** Blender has no initial velocity, and a body that is animated and then let go starts at rest
  (measured). A body that starts moving is given its ``linearVelocity`` and ``angularVelocity`` by MOTOR constraints to a
  passive anchor that break at exactly the impulse that velocity needs (mass x speed; the principal moment x angular
  speed about each principal axis), so they act in the first sub-step only. The anchor and the launch constraints are
  helpers, in the collection "X3D physics helpers", and are not exported.
* **Joints.** BallJoint is POINT, SingleAxisHingeJoint HINGE (its stops when they are not the default -pi..pi, which is
  read as no stop, as ODE and X_ITE do), SliderJoint SLIDER with its separation stops, DoubleAxisHingeJoint and
  UniversalJoint GENERIC with the third rotation locked. Linked bodies do not collide with each other (X_ITE does the
  same). MotorJoint, joint motors, stop bounce and error correction are listed as losses.

Every Blender object that is a body or a joint carries the authored X3D fields as JSON (``x3d_rigid_body``,
``x3d_rigid_joint``) so the export can write them back.
"""

from __future__ import annotations

import json
import logging
import math

import bpy
from mathutils import Matrix, Vector

from .physics_model import (JOINT_DEFAULTS, PI, is_identity,
                            principal_inertia)

logger = logging.getLogger(__name__)

HELPERS = "X3D physics helpers"
HELPER_PROPERTY = "x3d_physics_helper"
BODY_PROPERTY = "x3d_rigid_body"
JOINT_PROPERTY = "x3d_rigid_joint"
WORLD_PROPERTY = "x3d_rigid_body_collection"
HOLDER_PROPERTY = "x3d_rigid_body_holder"
X_ITE_STEP_FPS = 60.0
CONVEX_TYPES = {"IndexedFaceSet", "IndexedTriangleSet", "TriangleSet", "IndexedQuadSet", "QuadSet",
                "IndexedTriangleFanSet", "IndexedTriangleStripSet", "TriangleFanSet", "TriangleStripSet"}


def _override(scene, ob=None):
    kw = {"scene": scene}
    if ob is not None:
        kw.update(object=ob, active_object=ob, selected_objects=[ob])
    view_layer = bpy.context.view_layer if bpy.context.view_layer is not None else scene.view_layers[0]
    kw["view_layer"] = view_layer
    if ob is not None:
        # Blender 5.1.2 ignores the override's object: rigidbody.constraint_add then acted on the view layer's active
        # object (a body, not the new empty) and the next line crashed. Make the object active as well.
        try:
            view_layer.objects.active = ob
        except (RuntimeError, ReferenceError):
            pass
    return bpy.context.temp_override(**kw)


def _helpers(scene):
    col = bpy.data.collections.get(HELPERS)
    if col is None:
        col = bpy.data.collections.new(HELPERS)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    col.hide_render = True
    return col


def _jsonable(fields):
    return json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in fields.items()})


def ensure_world(scene):
    if scene.rigidbody_world is None:
        with _override(scene):
            bpy.ops.rigidbody.world_add()
    world = scene.rigidbody_world
    if world.collection is None:
        world.collection = bpy.data.collections.new("RigidBodyWorld")
    if world.constraints is None:
        world.constraints = bpy.data.collections.new("RigidBodyConstraints")
    return world


def configure_world(scene, world, collection, matrix):
    f = collection.fields
    g = matrix.to_3x3() @ Vector(f["gravity"])
    scene.gravity = g
    scene.use_gravity = True
    iterations = max(1, min(1000, int(f["iterations"])))
    world.solver_iterations = iterations
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    world.substeps_per_frame = max(1, int(round(X_ITE_STEP_FPS * iterations / fps)))
    world.enabled = bool(f["enabled"])
    world.time_scale = 1.0
    world.point_cache.frame_start = scene.frame_start
    world.point_cache.frame_end = max(scene.frame_end, world.point_cache.frame_end)
    scene[WORLD_PROPERTY] = _jsonable(f)


def _shape_type(shape):
    if shape.kind == "Box":
        return "BOX"
    if shape.kind == "Sphere":
        return "SPHERE"
    if shape.kind == "ElevationGrid":
        return "MESH"
    if shape.kind in CONVEX_TYPES and shape.params.get("convex", "true").strip().lower() == "false":
        return "MESH"
    return "CONVEX_HULL"


def _add_rigid_body(scene, ob):
    if ob.rigid_body is None:
        with _override(scene, ob):
            bpy.ops.rigidbody.object_add()
    return ob.rigid_body


def _body_settings(rb, body, contact, collection_fields, scale):
    f = body.fields
    rb.type = "PASSIVE" if f["fixed"] else "ACTIVE"
    rb.mass = max(1e-6, f["mass"])
    restitution, friction, _rolling = contact
    rb.restitution = math.sqrt(restitution)
    rb.friction = math.sqrt(friction)
    if f["autoDamp"]:
        rb.linear_damping = max(0.0, min(1.0, f["linearDampingFactor"]))
        rb.angular_damping = max(0.0, min(1.0, f["angularDampingFactor"]))
    else:
        rb.linear_damping = 0.0
        rb.angular_damping = 0.0
    auto = f["autoDisable"] or collection_fields["autoDisable"]
    rb.use_deactivation = bool(auto)
    if auto:
        rb.deactivate_linear_velocity = f["disableLinearSpeed"] or collection_fields["disableLinearSpeed"]
        rb.deactivate_angular_velocity = f["disableAngularSpeed"] or collection_fields["disableAngularSpeed"]
    thickness = collection_fields["contactSurfaceThickness"]
    if thickness > 0:
        rb.use_margin = True
        rb.collision_margin = thickness * scale


def _anchor(scene, helpers):
    ob = helpers.objects.get("X3D physics anchor")
    if ob is not None:
        return ob
    me = bpy.data.meshes.new("X3D physics anchor")
    me.from_pydata([(-.005, -.005, -.005), (.005, -.005, -.005), (0, .005, -.005), (0, 0, .005)], [],
                   [(0, 1, 2), (0, 1, 3), (1, 2, 3), (2, 0, 3)])
    ob = bpy.data.objects.new("X3D physics anchor", me)
    helpers.objects.link(ob)
    ob.location = (0.0, 0.0, -1.0e4)
    ob.hide_render = True
    ob[HELPER_PROPERTY] = "anchor"
    rb = _add_rigid_body(scene, ob)
    rb.type = "PASSIVE"
    rb.collision_collections = [False] * 20
    return ob


def _motor(scene, helpers, ob, anchor, axis, speed, threshold, kind, name):
    e = bpy.data.objects.new(name, None)
    helpers.objects.link(e)
    e.empty_display_size = 0.05
    e[HELPER_PROPERTY] = f"launch {kind}"
    rot = axis.normalized().to_track_quat("X", "Z").to_matrix().to_4x4()
    e.matrix_world = Matrix.Translation(ob.matrix_world.translation) @ rot
    with _override(scene, e):
        bpy.ops.rigidbody.constraint_add()
    c = e.rigid_body_constraint
    c.type = "MOTOR"
    c.object1, c.object2 = ob, anchor
    if kind == "linear":
        c.use_motor_lin, c.motor_lin_target_velocity, c.motor_lin_max_impulse = True, speed, 1.0e9
    else:
        c.use_motor_ang, c.motor_ang_target_velocity, c.motor_ang_max_impulse = True, speed, 1.0e9
    c.use_breaking, c.breaking_threshold = True, threshold
    c.disable_collisions = True
    return e


def launch(scene, helpers, ob, body, matrix):
    """Give the body its authored starting velocities (module docstring): one breaking MOTOR per direction that needs one."""
    f = body.fields
    if f["fixed"] or ob.rigid_body is None or ob.rigid_body.type != "ACTIVE":
        return []
    made = []
    m3 = matrix.to_3x3()
    v = m3 @ Vector(f["linearVelocity"])
    w = m3 @ Vector(f["angularVelocity"])
    w = w / max(1e-12, m3.median_scale) if w.length else w    # angular speed does not scale with length
    if v.length > 0:
        anchor = _anchor(scene, helpers)
        made.append(_motor(scene, helpers, ob, anchor, v, v.length, ob.rigid_body.mass * v.length, "linear",
                           f"launch {ob.name} linear"))
    if w.length > 0:
        anchor = _anchor(scene, helpers)
        dims = ob.dimensions
        moments = principal_inertia(ob.rigid_body.collision_shape, tuple(dims), ob.rigid_body.mass,
                                    ob.rigid_body.collision_margin)
        rot = ob.matrix_world.to_3x3().normalized()
        for i in range(3):
            axis = rot.col[i].normalized()
            component = w.dot(axis)
            if abs(component) < 1e-12:
                continue
            direction = axis if component > 0 else -axis
            made.append(_motor(scene, helpers, ob, anchor, direction, abs(component), moments[i] * abs(component),
                               "angular", f"launch {ob.name} angular {'xyz'[i]}"))
    return made


def _compound(scene, collection_bpy, body, objects, frame_world):
    """A body of several shapes (or one placed off the body's frame): an object at the body frame, COMPOUND, with the shape
    objects as its rigid children."""
    me = bpy.data.meshes.new(body.name)
    holder = bpy.data.objects.new(body.name, me)
    holder[HOLDER_PROPERTY] = True       # a body with no geometry of its own: the export writes it as the RigidBody only
    collection_bpy.objects.link(holder)
    holder.matrix_world = frame_world
    for child in objects:
        world = child.matrix_world.copy()
        child.parent = holder
        child.matrix_parent_inverse = holder.matrix_world.inverted()
        child.matrix_world = world
    return holder


def _constraint(scene, helpers, joint, ob1, ob2, matrix, physics, collection_name):
    f = joint.fields
    m3 = matrix.to_3x3()
    e = bpy.data.objects.new(f"{joint.type} {joint.name}", None)
    helpers.objects.link(e)
    e.empty_display_size = 0.15
    anchor = matrix @ Vector(f.get("anchorPoint", (0.0, 0.0, 0.0)))
    if joint.type == "SliderJoint":
        anchor = ob2.matrix_world.translation.copy()
    axis_x = axis_z = None
    if joint.type == "SingleAxisHingeJoint":
        axis_z = m3 @ Vector(f["axis"])
    elif joint.type == "SliderJoint":
        axis_x = m3 @ Vector(f["axis"])
    elif joint.type in ("DoubleAxisHingeJoint", "UniversalJoint"):
        axis_x = m3 @ Vector(f["axis1"])
    rot = Matrix()
    if axis_z is not None and axis_z.length > 0:
        rot = axis_z.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
    elif axis_x is not None and axis_x.length > 0:
        rot = axis_x.normalized().to_track_quat("X", "Z").to_matrix().to_4x4()
    e.matrix_world = Matrix.Translation(anchor) @ rot
    with _override(scene, e):
        bpy.ops.rigidbody.constraint_add()
    c = e.rigid_body_constraint
    c.object1, c.object2 = ob1, ob2
    c.disable_collisions = True
    what = f"{joint.type} {joint.name}"
    defaults = JOINT_DEFAULTS[joint.type]
    if joint.type == "BallJoint":
        c.type = "POINT"
    elif joint.type == "SingleAxisHingeJoint":
        c.type = "HINGE"
        lo, hi = f["minAngle"], f["maxAngle"]
        if not (lo <= -PI + 1e-6 and hi >= PI - 1e-6):
            c.use_limit_ang_z = True
            c.limit_ang_z_lower, c.limit_ang_z_upper = max(-math.pi, lo), min(math.pi, hi)
    elif joint.type == "SliderJoint":
        c.type = "SLIDER"
        axis = (m3 @ Vector(f["axis"])).normalized()
        scale = m3.median_scale
        start = (ob2.matrix_world.translation - ob1.matrix_world.translation).dot(axis)
        c.use_limit_lin_x = True
        c.limit_lin_x_lower = f["minSeparation"] * scale - start
        c.limit_lin_x_upper = f["maxSeparation"] * scale - start
        if f["sliderForce"]:
            physics.lose(what, "sliderForce", "a slider force is not imported")
    else:
        c.type = "GENERIC"
        for axis in "xyz":
            setattr(c, f"use_limit_lin_{axis}", True)
            setattr(c, f"limit_lin_{axis}_lower", 0.0)
            setattr(c, f"limit_lin_{axis}_upper", 0.0)
        a1 = (m3 @ Vector(f["axis1"])).normalized()
        a2 = (m3 @ Vector(f["axis2"])).normalized()
        third = a1.cross(a2)
        if third.length > 1e-6:
            # lock the rotation about the direction neither axis turns about, in the constraint frame (x = axis1)
            local = rot.to_3x3().inverted() @ third.normalized()
            lock = "xyz"[max(range(3), key=lambda i: abs(local[i]))]
            setattr(c, f"use_limit_ang_{lock}", True)
            setattr(c, f"limit_ang_{lock}_lower", 0.0)
            setattr(c, f"limit_ang_{lock}_upper", 0.0)
        if joint.type == "DoubleAxisHingeJoint":
            lo, hi = f["minAngle1"], f["maxAngle1"]
            if not (lo <= -PI + 1e-6 and hi >= PI - 1e-6):
                c.use_limit_ang_x = True
                c.limit_ang_x_lower, c.limit_ang_x_upper = max(-math.pi, lo), min(math.pi, hi)
            for name in ("desiredAngularVelocity1", "desiredAngularVelocity2", "maxTorque1", "maxTorque2",
                         "suspensionForce"):
                if f[name] != defaults[name]:
                    physics.lose(what, name, "joint motors and suspension are not imported")
    for name in ("stopBounce", "stopErrorCorrection", "stop1Bounce", "stop1ErrorCorrection", "stop2Bounce",
                 "stop2ErrorCorrection", "stop1ConstantForceMix", "suspensionErrorCorrection"):
        if name in f and f[name] != defaults[name]:
            physics.lose(what, name, "Blender's constraints have no stop bounce or error correction")
    e[JOINT_PROPERTY] = json.dumps({"type": joint.type, "name": joint.name, "body1": joint.body1, "body2": joint.body2,
                                    "collection": collection_name,
                                    "fields": {k: (list(v) if isinstance(v, tuple) else v) for k, v in f.items()}})
    return e


def apply(physics, scene, collection_bpy, shape_objects, collection_matrices, scale=1.0):
    """Make the Blender rigid body world for ``physics`` (a physics_model.Physics).

    shape_objects: {id(Shape element): Blender object the importer made for it}; collection_matrices: {id(collection
    element): Matrix from the collection's coordinates to Blender's world (axis conversion and enclosing Transforms)}.
    Returns {"bodies": {name: object}, "joints": [...], "launch": [...]}; the losses are added to ``physics.losses``."""
    made = {"bodies": {}, "joints": [], "launch": []}
    if not physics.collections:
        return made
    world = ensure_world(scene)
    helpers = _helpers(scene)
    first = True
    for col in physics.collections:
        # collection coordinates (the file's lengths) to Blender's world: the import scale, then axes and Transforms
        matrix = collection_matrices.get(id(col.element), Matrix()) @ Matrix.Scale(scale, 4)
        if first:
            configure_world(scene, world, col, matrix)
            first = False
        contact = col.contact()
        objects_by_body = {}
        for body in col.bodies:
            if not body.fields["enabled"]:
                physics.lose(f"RigidBody {body.name}", "enabled", "FALSE: imported as geometry, not as a body")
                continue
            obs = [shape_objects.get(id(s.shape_element)) for s in body.shapes]
            pairs = [(s, o) for s, o in zip(body.shapes, obs) if o is not None]
            if not pairs:
                if body.shapes:
                    physics.lose(f"RigidBody {body.name}", "geometry", "its shapes made no Blender object")
                continue
            frame_world = matrix @ Matrix.Translation(body.fields["position"]) @ _rotation(body.fields["orientation"])
            if len(pairs) == 1 and is_identity(pairs[0][0].local):
                shape, ob = pairs[0]
                rb = _add_rigid_body(scene, ob)
                rb.collision_shape = _shape_type(shape)
                if rb.collision_shape == "MESH":
                    rb.mesh_source = "BASE"
            else:
                ob = _compound(scene, collection_bpy, body, [o for _s, o in pairs], frame_world)
                rb = _add_rigid_body(scene, ob)
                rb.collision_shape = "COMPOUND"
                for shape, child in pairs:
                    crb = _add_rigid_body(scene, child)
                    crb.collision_shape = _shape_type(shape)
                    crb.type = "ACTIVE"
            _body_settings(rb, body, contact, col.fields, scale)
            ob[BODY_PROPERTY] = json.dumps({"name": body.name, "collection": col.name,
                                            "fields": json.loads(_jsonable(body.fields)),
                                            "shapes": [s.kind for s in body.shapes]})
            objects_by_body[body.name] = ob
            made["bodies"][body.name] = ob
        for body in col.bodies:
            ob = objects_by_body.get(body.name)
            if ob is not None:
                made["launch"] += launch(scene, helpers, ob, body, matrix)
        for joint in col.joints:
            ob1, ob2 = objects_by_body.get(joint.body1), objects_by_body.get(joint.body2)
            if joint.type == "MotorJoint":
                physics.lose(f"MotorJoint {joint.name}", "(node)", "MotorJoint is not imported (X_ITE 16.8.1 has none)")
                continue
            if ob1 is None or ob2 is None:
                continue
            made["joints"].append(_constraint(scene, helpers, joint, ob1, ob2, matrix, physics, col.name))
    return made


def _rotation(axis_angle):
    x, y, z, a = axis_angle
    axis = Vector((x, y, z))
    if axis.length == 0 or a == 0:
        return Matrix()
    return Matrix.Rotation(a, 4, axis.normalized())
