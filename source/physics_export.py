# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender's rigid body world written back as X3D RigidBodyPhysics (the X3D 4.0 export; physics_blender is the import).

``extract`` reads the scene into plain data at export time; ``physics_xml`` writes it. What is written:

* one RigidBodyCollection (gravity through the export's axis conversion, ``iterations`` = the solver iterations) with one
  CollisionCollection: ``bounce`` and ``frictionCoefficients`` are what a contact between two of the bodies gets in
  Blender (Bullet multiplies the two bodies' values), "BOUNCE" and "FRICTION_COEFFICIENT_2" applied, ``minBounceSpeed`` 0.
  When the bodies differ, the median contact value is written and a diagnostic says so (X3D has one per collection).
* a RigidBody per body, at its starting pose (the object's own location and rotation, which the simulation does not
  change), with ``mass``, ``fixed`` (PASSIVE, or an ACTIVE body that is animated or not dynamic), damping
  (``autoDamp``), deactivation (``autoDisable``), and the starting velocities the import read (``x3d_rigid_body``).
  Its collidable is the Blender collision shape: Box and Sphere, Cylinder and Cone turned from Blender's Z axis to X3D's
  Y axis, and an IndexedFaceSet of the mesh for a convex hull (``convex`` TRUE), a mesh or a capsule; a compound body has
  one collidable per child.
* the joints Blender can say in X3D: POINT as BallJoint, HINGE as SingleAxisHingeJoint (its limits as min/maxAngle),
  SLIDER as SliderJoint (its limits as separations), and the GENERIC constraints the import made from a
  DoubleAxisHingeJoint or UniversalJoint, as they were read. Others are listed in the export's diagnostics.
* ROUTEs from each body's position and orientation to the Transform that shows it: the objects that follow the body
  (the import's Copy Location / Copy Rotation / Child Of constraints) or, when none does, the body's own Transform.

The import's helpers (the anchor and the start-up motors, the "X3D physics helpers" collection) are not written.
"""

from __future__ import annotations

import json
import math
import statistics

HELPER_PROPERTY = "x3d_physics_helper"
BODY_PROPERTY = "x3d_rigid_body"
JOINT_PROPERTY = "x3d_rigid_joint"
WORLD_PROPERTY = "x3d_rigid_body_collection"
FOLLOW_PREFIX = "X3D ROUTE "


def is_helper(obj) -> bool:
    """An object the export writes as physics, not as a Transform: the import's helpers and constraint empties."""
    return HELPER_PROPERTY in obj.keys() or getattr(obj, "rigid_body_constraint", None) is not None


def _fmt(v):
    v = float(v)
    if not math.isfinite(v):
        v = 0.0
    text = f"{v:.7g}"
    return "0" if text in ("-0", "0") else text


def _fmt3(v):
    return " ".join(_fmt(x) for x in v)


def _axis_angle(quat):
    axis, angle = quat.to_axis_angle()
    if angle == 0 or axis.length == 0:
        return (0.0, 0.0, 1.0, 0.0)
    return (axis.x, axis.y, axis.z, angle)


def _authored(obj):
    try:
        return json.loads(obj[BODY_PROPERTY])
    except Exception:
        return {}


def _start_matrix(obj):
    """The body's pose when the simulation starts: its own transform (the simulation only moves the evaluated copy)."""
    if obj.parent is None:
        return obj.matrix_basis.copy()
    return obj.matrix_world.copy()


def _mesh_ifs(obj, scale):
    me = obj.data
    if me is None or not hasattr(me, "vertices"):
        return None
    points = [tuple(v.co[i] * scale[i] for i in range(3)) for v in me.vertices]
    faces = [tuple(p.vertices) for p in me.polygons]
    if not points or not faces:
        return None
    return {"points": points, "faces": faces}


def _collidable(obj, local_matrix=None):
    """(geometry dict, translation, rotation) of one Blender collision shape, in the body's frame."""
    from mathutils import Matrix
    rb = obj.rigid_body
    loc, rot, scale = (local_matrix or Matrix()).decompose()
    s = obj.scale if local_matrix is None else scale
    dims = [d for d in obj.dimensions]
    shape = rb.collision_shape
    turn = (1.0, 0.0, 0.0, math.pi / 2)        # X3D's Cylinder/Cone axis is Y; Bullet's is Z
    if shape == "BOX":
        geom = {"kind": "Box", "size": dims}
        frame_rot = _axis_angle(rot)
    elif shape == "SPHERE":
        geom = {"kind": "Sphere", "radius": max(dims) / 2.0}
        frame_rot = _axis_angle(rot)
    elif shape in ("CYLINDER", "CONE"):
        from mathutils import Quaternion, Vector
        geom = {"kind": "Cylinder" if shape == "CYLINDER" else "Cone",
                "radius": max(dims[0], dims[1]) / 2.0, "height": dims[2]}
        frame_rot = _axis_angle(rot @ Quaternion(Vector(turn[:3]), turn[3]))
    else:
        ifs = _mesh_ifs(obj, s)
        geom = {"kind": "IndexedFaceSet", "convex": shape != "MESH", **(ifs or {"points": [], "faces": []})}
        frame_rot = _axis_angle(rot)
    return geom, tuple(loc), frame_rot


def extract(scene, exported, global_matrix=None):
    """The scene's rigid body world as plain data, or None. ``exported``: the objects the export writes."""
    from mathutils import Matrix
    world = getattr(scene, "rigidbody_world", None)
    if world is None or world.collection is None:
        return None
    M = global_matrix if global_matrix is not None else Matrix()
    m3 = M.to_3x3()
    names = {o.name for o in exported}
    diagnostics = []
    members = [o for o in world.collection.objects if o.rigid_body is not None]
    compound_children = {o.name for o in members
                         if o.parent is not None and o.parent.rigid_body is not None
                         and o.parent.rigid_body.collision_shape == "COMPOUND"}
    bodies = []
    frictions, restitutions = [], []
    for obj in members:
        if obj.name in compound_children or HELPER_PROPERTY in obj.keys():
            continue
        if obj.name not in names and not any(c.name in names for c in obj.children):
            continue
        rb = obj.rigid_body
        authored = _authored(obj)
        fields = authored.get("fields", {})
        start = M @ _start_matrix(obj)
        loc, rot, _scale = start.decompose()
        animated = bool(rb.kinematic) or not rb.enabled
        fixed = rb.type == "PASSIVE" or animated
        if animated and rb.type == "ACTIVE":
            diagnostics.append(f"Rigid body {obj.name}: animated or not dynamic in Blender, written as fixed")
        collidables = []
        if rb.collision_shape == "COMPOUND":
            for child in obj.children:
                if child.rigid_body is None:
                    continue
                local = _start_matrix(obj).inverted() @ (_start_matrix(obj) @ child.matrix_parent_inverse
                                                          @ child.matrix_basis if child.parent is obj else child.matrix_world)
                collidables.append(_collidable(child, local))
        else:
            if rb.collision_shape == "CAPSULE":
                diagnostics.append(f"Rigid body {obj.name}: a capsule is written as its mesh (X3D has no capsule)")
            collidables.append(_collidable(obj))
        body = {
            "object": obj.name,
            "name": authored.get("name") or obj.name,
            "position": tuple(loc), "orientation": _axis_angle(rot),
            "mass": rb.mass, "fixed": fixed,
            # the velocities the import read, in the file's own axes (the export's default axes are the import's)
            "linearVelocity": tuple(fields.get("linearVelocity", (0.0, 0.0, 0.0))),
            "angularVelocity": tuple(fields.get("angularVelocity", (0.0, 0.0, 0.0))),
            "autoDamp": rb.linear_damping > 0 or rb.angular_damping > 0,
            "linearDampingFactor": rb.linear_damping, "angularDampingFactor": rb.angular_damping,
            "autoDisable": bool(rb.use_deactivation),
            "disableLinearSpeed": rb.deactivate_linear_velocity, "disableAngularSpeed": rb.deactivate_angular_velocity,
            "collidables": collidables,
        }
        bodies.append(body)
        frictions.append(rb.friction * rb.friction)
        restitutions.append(rb.restitution * rb.restitution)
    if not bodies:
        return None
    mu = statistics.median(frictions)
    e = statistics.median(restitutions)
    if max(frictions) - min(frictions) > 1e-6 or max(restitutions) - min(restitutions) > 1e-6:
        diagnostics.append("Rigid bodies have different friction or bounce: X3D has one CollisionCollection per "
                           f"RigidBodyCollection, the median contact values are written (friction {mu:.4g}, bounce {e:.4g})")
    by_object = {b["object"]: b for b in bodies}
    joints = []
    for obj in scene.objects:
        c = obj.rigid_body_constraint
        if c is None or HELPER_PROPERTY in obj.keys():
            continue
        b1 = by_object.get(c.object1.name if c.object1 else "")
        b2 = by_object.get(c.object2.name if c.object2 else "")
        if b1 is None or b2 is None:
            diagnostics.append(f"Rigid body constraint {obj.name}: needs two exported bodies, not written")
            continue
        world_m = M @ obj.matrix_world
        anchor = tuple(world_m.translation)
        axes = world_m.to_3x3().normalized()
        authored = {}
        try:
            authored = json.loads(obj[JOINT_PROPERTY])
        except Exception:
            pass
        j = {"name": authored.get("name") or obj.name, "body1": b1["name"], "body2": b2["name"], "anchorPoint": anchor}
        if c.type == "POINT":
            j["type"] = "BallJoint"
        elif c.type == "HINGE":
            j["type"] = "SingleAxisHingeJoint"
            j["axis"] = tuple(axes.col[2])
            if c.use_limit_ang_z:
                j["minAngle"], j["maxAngle"] = c.limit_ang_z_lower, c.limit_ang_z_upper
        elif c.type == "SLIDER":
            j["type"] = "SliderJoint"
            axis = axes.col[0]
            j["axis"] = tuple(axis)
            p1 = (M @ _start_matrix(c.object1)).translation
            p2 = (M @ _start_matrix(c.object2)).translation
            start = (p2 - p1).dot(axis.normalized())
            if c.use_limit_lin_x:
                j["minSeparation"], j["maxSeparation"] = start + c.limit_lin_x_lower, start + c.limit_lin_x_upper
            else:
                j["minSeparation"], j["maxSeparation"] = -1.0e4, 1.0e4
                diagnostics.append(f"Slider {obj.name}: no limits in Blender, written with separations of +-10 km "
                                   "(X3D's default is 0 to 1)")
        elif c.type == "GENERIC" and authored.get("type") in ("DoubleAxisHingeJoint", "UniversalJoint"):
            j["type"] = authored["type"]
            j["axis1"] = tuple(axes.col[0])
            fields = authored.get("fields", {})
            a2 = fields.get("axis2")
            j["axis2"] = tuple(a2) if a2 else tuple(axes.col[1])
            for k in ("minAngle1", "maxAngle1"):
                if k in fields:
                    j[k] = fields[k]
        else:
            diagnostics.append(f"Rigid body constraint {obj.name} ({c.type}): X3D has no such joint, not written")
            continue
        joints.append(j)
    # who shows each body: the objects that follow it, else the body itself
    followers = {}
    for obj in exported:
        for con in obj.constraints:
            target = getattr(con, "target", None)
            if target is not None and con.name.startswith(FOLLOW_PREFIX) and target.name in by_object:
                followers.setdefault(target.name, set()).add(obj.name)
    routes = []
    for b in bodies:
        shown = sorted(followers.get(b["object"], ()))
        if not shown and b["object"] in names and not bpy_get(b["object"], "x3d_collidable_only"):
            shown = [b["object"]]
        for target in shown:
            routes.append((b["name"], target))
    gravity = tuple(m3 @ scene.gravity) if scene.use_gravity else (0.0, 0.0, 0.0)
    try:
        collection_fields = json.loads(scene.get(WORLD_PROPERTY, "{}"))
    except Exception:
        collection_fields = {}
    return {"name": collection_fields.get("name") or "RigidBodyWorld", "gravity": gravity,
            "iterations": world.solver_iterations, "enabled": bool(world.enabled), "bounce": e, "friction": mu,
            "bodies": bodies, "joints": joints, "routes": routes, "diagnostics": diagnostics}


def bpy_get(name, key):
    import bpy
    obj = bpy.data.objects.get(name)
    return obj is not None and bool(obj.get(key))


def _geometry_xml(geom, indent):
    k = geom["kind"]
    if k == "Box":
        return f'{indent}<Box size="{_fmt3(geom["size"])}" />\n'
    if k == "Sphere":
        return f'{indent}<Sphere radius="{_fmt(geom["radius"])}" />\n'
    if k == "Cylinder":
        return f'{indent}<Cylinder radius="{_fmt(geom["radius"])}" height="{_fmt(geom["height"])}" />\n'
    if k == "Cone":
        return f'{indent}<Cone bottomRadius="{_fmt(geom["radius"])}" height="{_fmt(geom["height"])}" />\n'
    index = " ".join(" ".join(str(i) for i in f) + " -1" for f in geom["faces"])
    points = ", ".join(_fmt3(p) for p in geom["points"])
    return (f'{indent}<IndexedFaceSet convex="{"true" if geom["convex"] else "false"}" coordIndex="{index}">\n'
            f'{indent}  <Coordinate point="{points}" />\n{indent}</IndexedFaceSet>\n')


def physics_xml(physics, defs, indent, transform_def):
    """The RigidBodyCollection and its ROUTEs. ``defs`` is the emitter's DEF table; ``transform_def(object_name)`` the
    DEF of the Transform the emitter wrote for an object."""
    if not physics:
        return ""
    world_def = defs.get("rigidbodycollection", physics["name"], "", physics["name"])
    body_defs = {b["name"]: defs.get("rigidbody", b["name"], "", b["name"]) for b in physics["bodies"]}
    out = [f'{indent}<RigidBodyCollection DEF="{world_def}" gravity="{_fmt3(physics["gravity"])}" '
           f'iterations="{int(physics["iterations"])}"{"" if physics["enabled"] else " enabled=\"false\""}>\n']
    i2, i3, i4, i5 = indent + "  ", indent + "    ", indent + "      ", indent + "        "
    # "FRICTION_COEFFICIENT_2": the spelling of X3DUOM-generated tools (x3d.py, X3DJSAIL), which the export's x3d.py
    # check enforces, and of X_ITE; the standard's text and XSD documentation spell it "FRICTION_COEFFICIENT-2"
    out.append(f'{i2}<CollisionCollection containerField="collider" appliedParameters=\'"BOUNCE" "FRICTION_COEFFICIENT_2"\' '
               f'bounce="{_fmt(physics["bounce"])}" minBounceSpeed="0" '
               f'frictionCoefficients="{_fmt(physics["friction"])} {_fmt(physics["friction"])}" />\n')
    for b in physics["bodies"]:
        attrs = [f'DEF="{body_defs[b["name"]]}"', 'containerField="bodies"', f'position="{_fmt3(b["position"])}"',
                 f'orientation="{_fmt3(b["orientation"])}"', f'mass="{_fmt(b["mass"])}"']
        if b["fixed"]:
            attrs.append('fixed="true"')
        if any(b["linearVelocity"]):
            attrs.append(f'linearVelocity="{_fmt3(b["linearVelocity"])}"')
        if any(b["angularVelocity"]):
            attrs.append(f'angularVelocity="{_fmt3(b["angularVelocity"])}"')
        if b["autoDamp"]:
            attrs += ['autoDamp="true"', f'linearDampingFactor="{_fmt(b["linearDampingFactor"])}"',
                      f'angularDampingFactor="{_fmt(b["angularDampingFactor"])}"']
        if b["autoDisable"]:
            attrs += ['autoDisable="true"', f'disableLinearSpeed="{_fmt(b["disableLinearSpeed"])}"',
                      f'disableAngularSpeed="{_fmt(b["disableAngularSpeed"])}"']
        out.append(f'{i2}<RigidBody {" ".join(attrs)}>\n')
        for geom, loc, rot in b["collidables"]:
            place = ""
            if any(abs(x) > 1e-12 for x in loc):
                place += f' translation="{_fmt3(loc)}"'
            if rot[3] != 0:
                place += f' rotation="{_fmt3(rot)}"'
            out.append(f'{i3}<CollidableShape containerField="geometry"{place}>\n{i4}<Shape containerField="shape">\n')
            out.append(_geometry_xml(geom, i5))
            out.append(f'{i4}</Shape>\n{i3}</CollidableShape>\n')
        out.append(f"{i2}</RigidBody>\n")
    for j in physics["joints"]:
        attrs = [f'DEF="{defs.get("rigidjoint", j["name"], "", j["name"])}"', 'containerField="joints"']
        if j["type"] != "SliderJoint":
            attrs.append(f'anchorPoint="{_fmt3(j["anchorPoint"])}"')
        for k in ("axis", "axis1", "axis2"):
            if k in j:
                attrs.append(f'{k}="{_fmt3(j[k])}"')
        for k in ("minAngle", "maxAngle", "minSeparation", "maxSeparation", "minAngle1", "maxAngle1"):
            if k in j:
                attrs.append(f'{k}="{_fmt(j[k])}"')
        out.append(f'{i2}<{j["type"]} {" ".join(attrs)}>\n'
                   f'{i3}<RigidBody USE="{body_defs[j["body1"]]}" containerField="body1" />\n'
                   f'{i3}<RigidBody USE="{body_defs[j["body2"]]}" containerField="body2" />\n'
                   f'{i2}</{j["type"]}>\n')
    out.append(f"{indent}</RigidBodyCollection>\n")
    for body_name, target in physics["routes"]:
        to = transform_def(target)
        out.append(f'{indent}<ROUTE fromNode="{body_defs[body_name]}" fromField="position" toNode="{to}" toField="set_translation" />\n')
        out.append(f'{indent}<ROUTE fromNode="{body_defs[body_name]}" fromField="orientation" toNode="{to}" toField="set_rotation" />\n')
    return "".join(out)
