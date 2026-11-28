# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D RigidBodyPhysics, read from the document into plain data (no bpy here; ``physics_blender`` makes the Blender side).

What a scene says about its physics: each RigidBodyCollection with its world fields, its bodies (where they are, how heavy,
how they start moving, what they collide with) and its joints, every field at the X3D 4.0 default when the file does not
set it (defaults from x3d.py 4.0.65.8, which follows X3DUOM 4.0; ``appliedParameters`` is "BOUNCE" as in the standard).

The reading of the contact parameters (CollisionCollection) follows the standard, not one browser:

* ``bounce`` is the coefficient of restitution of a contact, applied when ``appliedParameters`` has "BOUNCE".
* ``frictionCoefficients`` is the contact's Coulomb friction (first direction), applied when ``appliedParameters`` has
  "FRICTION_COEFFICIENT-2" or "USER_FRICTION". The standard gives no friction when neither is applied; this reading then
  uses 0.25, which is what X_ITE 16.8.1 and Blender both make of two bodies at their own default friction of 0.5.

X_ITE 16.8.1 sets ``bounce`` and the friction coefficient on each body, and Bullet multiplies the two bodies' values at a
contact, so in X_ITE a contact gets bounce squared and friction squared (and X_ITE reads only the spelling
"FRICTION_COEFFICIENT_2"). ``physics_blender`` gives each body the square root, so a contact gets the authored value.

Everything the document asks for that the Blender rigid body world cannot do is listed in ``Physics.losses`` with the node
and the field, so the importer's loss report names it. Nothing here runs code from the file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --- X3D 4.0 defaults (x3d.py 4.0.65.8 / X3DUOM 4.0) --------------------------------------------------------------------

PI = 3.141592653          # the standard writes the default joint stops with this many digits

COLLECTION_DEFAULTS = {
    "enabled": True, "gravity": (0.0, -9.8, 0.0), "iterations": 10, "preferAccuracy": False, "errorCorrection": 0.8,
    "constantForceMix": 0.0001, "maxCorrectionSpeed": -1.0, "contactSurfaceThickness": 0.0, "autoDisable": False,
    "disableTime": 0.0, "disableLinearSpeed": 0.0, "disableAngularSpeed": 0.0,
}
BODY_DEFAULTS = {
    "enabled": True, "fixed": False, "position": (0.0, 0.0, 0.0), "orientation": (0.0, 0.0, 1.0, 0.0),
    "linearVelocity": (0.0, 0.0, 0.0), "angularVelocity": (0.0, 0.0, 0.0), "useFiniteRotation": False,
    "finiteRotationAxis": (0.0, 1.0, 0.0), "autoDamp": False, "linearDampingFactor": 0.001, "angularDampingFactor": 0.001,
    "mass": 1.0, "centerOfMass": (0.0, 0.0, 0.0), "inertia": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    "useGlobalGravity": True, "autoDisable": False, "disableTime": 0.0, "disableLinearSpeed": 0.0,
    "disableAngularSpeed": 0.0,
}
COLLIDER_DEFAULTS = {
    "enabled": True, "appliedParameters": ("BOUNCE",), "bounce": 0.0, "minBounceSpeed": 0.1,
    "frictionCoefficients": (0.0, 0.0), "slipFactors": (0.0, 0.0), "softnessConstantForceMix": 0.0001,
    "softnessErrorCorrection": 0.8, "surfaceSpeed": (0.0, 0.0),
}
JOINT_DEFAULTS = {
    "BallJoint": {"anchorPoint": (0.0, 0.0, 0.0)},
    "SingleAxisHingeJoint": {"anchorPoint": (0.0, 0.0, 0.0), "axis": (0.0, 1.0, 0.0), "minAngle": -PI, "maxAngle": PI,
                             "stopBounce": 0.0, "stopErrorCorrection": 0.8},
    "SliderJoint": {"axis": (0.0, 1.0, 0.0), "minSeparation": 0.0, "maxSeparation": 1.0, "sliderForce": 0.0,
                    "stopBounce": 0.0, "stopErrorCorrection": 1.0},
    "DoubleAxisHingeJoint": {"anchorPoint": (0.0, 0.0, 0.0), "axis1": (1.0, 0.0, 0.0), "axis2": (0.0, 1.0, 0.0),
                             "minAngle1": -PI, "maxAngle1": PI, "desiredAngularVelocity1": 0.0,
                             "desiredAngularVelocity2": 0.0, "maxTorque1": 0.0, "maxTorque2": 0.0, "stop1Bounce": 0.0,
                             "stop1ConstantForceMix": 0.001, "stop1ErrorCorrection": 0.8,
                             "suspensionErrorCorrection": 0.8, "suspensionForce": 0.0},
    "UniversalJoint": {"anchorPoint": (0.0, 0.0, 0.0), "axis1": (1.0, 0.0, 0.0), "axis2": (0.0, 1.0, 0.0),
                       "stop1Bounce": 0.0, "stop1ErrorCorrection": 0.8, "stop2Bounce": 0.0, "stop2ErrorCorrection": 0.8},
    "MotorJoint": {"autoCalc": False, "axis1Angle": 0.0, "axis1Torque": 0.0, "axis2Angle": 0.0, "axis2Torque": 0.0,
                   "axis3Angle": 0.0, "axis3Torque": 0.0, "enabledAxes": 1, "motor1Axis": (1.0, 0.0, 0.0),
                   "motor2Axis": (0.0, 1.0, 0.0), "motor3Axis": (0.0, 0.0, 1.0)},
}
JOINT_TYPES = tuple(JOINT_DEFAULTS)
PRIMITIVES = ("Box", "Sphere", "Cylinder", "Cone")
UNSET_FRICTION = 0.25     # neither friction parameter applied: what X_ITE 16.8.1 and Blender both give (0.5 x 0.5)

# Fields the Blender rigid body world has no place for. A field is reported only when the file sets it to something
# other than its default (and, for the contact fields, only when appliedParameters turns them on).
UNSUPPORTED_COLLECTION_FIELDS = ("preferAccuracy", "errorCorrection", "constantForceMix", "maxCorrectionSpeed",
                                 "disableTime")
UNSUPPORTED_BODY_FIELDS = ("centerOfMass", "inertia", "useFiniteRotation", "disableTime")
APPLIED_ONLY = {"SLIP-1": "slipFactors", "SLIP-2": "slipFactors", "SPEED-1": "surfaceSpeed", "SPEED-2": "surfaceSpeed",
                "ERROR_REDUCTION": "softnessErrorCorrection", "CONSTANT_FORCE": "softnessConstantForceMix"}


@dataclass
class Shape:
    """One collidable shape of a body: its geometry and where it sits in the body's frame."""
    kind: str                             # Box, Sphere, Cylinder, Cone, or the geometry's element name
    params: dict                          # size / radius / height / convex as authored
    local: tuple                          # 4x4 row-major matrix: shape frame in the body frame
    shape_element: object = None          # the Shape element (the importer made a Blender object from it)
    collidable_element: object = None


@dataclass
class Body:
    name: str
    element: object
    fields: dict
    shapes: list = field(default_factory=list)


@dataclass
class Joint:
    type: str
    name: str
    element: object
    fields: dict
    body1: str | None = None
    body2: str | None = None


@dataclass
class Collection:
    name: str
    element: object
    fields: dict
    collider: dict | None
    bodies: list = field(default_factory=list)
    joints: list = field(default_factory=list)

    def contact(self):
        """(restitution, friction, rolling friction) a contact between two bodies of this collection should get, read as
        the standard says (module docstring)."""
        c = self.collider or {}
        enabled = c.get("enabled", True)
        applied = set(c.get("appliedParameters", ())) if enabled else set()
        bounce = c.get("bounce", 0.0) if "BOUNCE" in applied else 0.0
        mu = UNSET_FRICTION
        if applied & {"FRICTION_COEFFICIENT-2", "FRICTION_COEFFICIENT_2", "USER_FRICTION"}:
            mu = c.get("frictionCoefficients", (0.0, 0.0))[0]
        return max(0.0, min(1.0, bounce)), max(0.0, mu), 0.0


@dataclass
class Physics:
    collections: list = field(default_factory=list)
    losses: list = field(default_factory=list)     # (node description, field, why)

    def lose(self, what, field_name, why):
        self.losses.append((what, field_name, why))


# --- reading fields ---------------------------------------------------------------------------------------------------

def _numbers(text):
    out = []
    for token in text.replace(",", " ").split():
        try:
            value = float(token)
        except ValueError:
            continue
        if math.isfinite(value):
            out.append(value)
    return out


def _mfstring(text):
    """An MFString as written in XML ('"BOUNCE" "FRICTION_COEFFICIENT-2"'), or a bare word."""
    text = text.strip()
    if '"' not in text:
        return tuple(text.split())
    parts, inside, cur = [], False, []
    for ch in text:
        if ch == '"':
            if inside:
                parts.append("".join(cur))
                cur = []
            inside = not inside
        elif inside:
            cur.append(ch)
    return tuple(parts)


def read_fields(element, defaults):
    """The fields of ``defaults`` as the element sets them (typed like the default), the rest at their defaults; also the
    names the element set explicitly."""
    values, explicit = dict(defaults), set()
    for name, default in defaults.items():
        if not element.hasAttribute(name):
            continue
        raw = element.getAttribute(name)
        explicit.add(name)
        if isinstance(default, bool):
            values[name] = raw.strip().lower() == "true"
        elif isinstance(default, int):
            nums = _numbers(raw)
            values[name] = int(nums[0]) if nums else default
        elif isinstance(default, float):
            nums = _numbers(raw)
            values[name] = nums[0] if nums else default
        elif isinstance(default, tuple) and default and isinstance(default[0], str):
            values[name] = _mfstring(raw)
        elif isinstance(default, tuple):
            nums = _numbers(raw)
            values[name] = tuple(nums) if len(nums) == len(default) else default
    return values, explicit


# --- small matrix helpers (row-major 4x4 tuples, no bpy) ----------------------------------------------------------------

def rotation_matrix(axis_angle):
    x, y, z, a = axis_angle
    n = math.sqrt(x * x + y * y + z * z)
    if n == 0 or a == 0:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    x, y, z = x / n, y / n, z / n
    c, s, t = math.cos(a), math.sin(a), 1 - math.cos(a)
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def frame(translation, axis_angle):
    r = rotation_matrix(axis_angle)
    return tuple(tuple(r[i]) + (translation[i],) for i in range(3)) + ((0.0, 0.0, 0.0, 1.0),)


def mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)) for i in range(4))


IDENTITY = frame((0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))


def is_identity(m, eps=1e-9):
    return all(abs(m[i][j] - IDENTITY[i][j]) <= eps for i in range(4) for j in range(4))


# --- the document walk --------------------------------------------------------------------------------------------------

def _elements(node):
    return [c for c in node.childNodes if getattr(c, "nodeType", None) == c.ELEMENT_NODE]


class _Defs:
    """DEF names of the document, so a USE resolves to the element it names (physics nodes are references, not copies)."""

    def __init__(self, root):
        self.by_name = {}
        stack = [root]
        while stack:
            el = stack.pop()
            if el.hasAttribute("DEF"):
                self.by_name.setdefault(el.getAttribute("DEF"), el)
            stack.extend(_elements(el))

    def real(self, el):
        if el.hasAttribute("USE"):
            return self.by_name.get(el.getAttribute("USE"))
        return el


def _container(el, default):
    return el.getAttribute("containerField") if el.hasAttribute("containerField") else default


def _name(el, fallback):
    return el.getAttribute("DEF") or el.getAttribute("USE") or fallback


def _shapes(defs, collidable_el, physics, body_name, local=IDENTITY, depth=0):
    """The Shapes a CollidableShape / CollidableOffset brings, each with its frame in the body (offsets nest)."""
    real = defs.real(collidable_el)
    if real is None or depth > 32:
        physics.lose(f"RigidBody {body_name}", "geometry", "a USE that names nothing, or offsets nested too deep")
        return []
    fields, _ = read_fields(real, {"enabled": True, "translation": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 1.0, 0.0)})
    here = mat_mul(local, frame(fields["translation"], fields["rotation"]))
    if not fields["enabled"]:
        physics.lose(f"RigidBody {body_name}", "geometry", f"{real.tagName} enabled FALSE: not collided")
        return []
    if real.tagName == "CollidableOffset":
        out = []
        for child in _elements(real):
            if child.tagName in ("CollidableShape", "CollidableOffset"):
                out += _shapes(defs, child, physics, body_name, here, depth + 1)
        return out
    out = []
    for child in _elements(real):
        if child.tagName != "Shape":
            continue
        shape = defs.real(child)
        if shape is None:
            continue
        for geom in _elements(shape):
            if geom.tagName in ("Appearance", "MetadataBoolean", "MetadataDouble", "MetadataFloat", "MetadataInteger",
                                "MetadataSet", "MetadataString", "ProtoInstance"):
                continue
            geom = defs.real(geom) or geom
            params = {k: geom.getAttribute(k) for k in ("size", "radius", "height", "bottomRadius", "convex")
                      if geom.hasAttribute(k)}
            out.append(Shape(geom.tagName, params, here, shape_element=child, collidable_element=collidable_el))
            break
    return out


def read_physics(root):
    """Every RigidBodyCollection under ``root`` (a DOM element, normally the X3D or Scene element)."""
    physics = Physics()
    defs = _Defs(root)
    stack = [root]
    found = []
    while stack:
        el = stack.pop()
        if el.tagName == "RigidBodyCollection" and not el.hasAttribute("USE"):
            found.append(el)
            continue          # a collection inside a collection is not a thing
        if el.tagName == "ProtoDeclare":
            if any(e.tagName == "RigidBodyCollection" for e in el.getElementsByTagName("RigidBodyCollection")):
                physics.lose(f"ProtoDeclare {el.getAttribute('name')}", "RigidBodyCollection",
                             "physics inside a PROTO is not imported")
            continue
        stack.extend(reversed(_elements(el)))
    for index, el in enumerate(found):
        name = _name(el, f"RigidBodyCollection{index + 1}")
        fields, explicit = read_fields(el, COLLECTION_DEFAULTS)
        collider = None
        for child in _elements(el):
            if child.tagName == "CollisionCollection" and _container(child, "collider") == "collider":
                real = defs.real(child)
                if real is not None:
                    collider, _explicit = read_fields(real, COLLIDER_DEFAULTS)
                    _report_collider(physics, name, collider)
        col = Collection(name, el, fields, collider)
        for field_name in UNSUPPORTED_COLLECTION_FIELDS:
            if field_name in explicit and fields[field_name] != COLLECTION_DEFAULTS[field_name]:
                physics.lose(f"RigidBodyCollection {name}", field_name, "Blender's rigid body world has no such setting")
        if not fields["enabled"]:
            physics.lose(f"RigidBodyCollection {name}", "enabled", "FALSE: the collection is imported and does not run")
        body_names = {}
        for b_index, child in enumerate(_elements(el)):
            if child.tagName != "RigidBody":
                continue
            real = defs.real(child)
            if real is None:
                continue
            b_name = _name(real, f"{name}.body{b_index + 1}")
            b_fields, b_explicit = read_fields(real, BODY_DEFAULTS)
            body = Body(b_name, real, b_fields)
            for g in _elements(real):
                if g.tagName in ("CollidableShape", "CollidableOffset") and _container(g, "geometry") == "geometry":
                    body.shapes += _shapes(defs, g, physics, b_name)
            for field_name in UNSUPPORTED_BODY_FIELDS:
                if field_name in b_explicit and b_fields[field_name] != BODY_DEFAULTS[field_name]:
                    physics.lose(f"RigidBody {b_name}", field_name, "Blender's rigid bodies have no such setting")
            if not b_fields["useGlobalGravity"]:
                physics.lose(f"RigidBody {b_name}", "useGlobalGravity",
                             "FALSE: Blender applies the world's gravity to every body")
            for field_name in ("forces", "torques"):
                if real.hasAttribute(field_name) and any(_numbers(real.getAttribute(field_name))):
                    physics.lose(f"RigidBody {b_name}", field_name, "constant forces and torques are not imported")
            if not body.shapes:
                physics.lose(f"RigidBody {b_name}", "geometry", "no collidable geometry: the body is not imported")
            col.bodies.append(body)
            body_names[id(real)] = b_name
        for child in _elements(el):
            if child.tagName not in JOINT_TYPES:
                continue
            real = defs.real(child)
            if real is None:
                continue
            j_fields, _ = read_fields(real, JOINT_DEFAULTS[real.tagName])
            joint = Joint(real.tagName, _name(real, f"{name}.{real.tagName}"), real, j_fields)
            for b in _elements(real):
                if b.tagName == "RigidBody":
                    target = defs.real(b)
                    slot = _container(b, "")
                    if slot in ("body1", "body2") and target is not None:
                        setattr(joint, slot, body_names.get(id(target)))
            if joint.body1 is None or joint.body2 is None:
                physics.lose(f"{real.tagName} {joint.name}", "body1/body2",
                             "a joint needs two bodies of its collection (X_ITE needs them too)")
            col.joints.append(joint)
        physics.collections.append(col)
    if len(physics.collections) > 1:
        physics.lose("RigidBodyCollection", "(several)",
                     "Blender has one rigid body world per scene: all collections run in it, with the first one's "
                     "gravity and solver settings")
    return physics


def _report_collider(physics, collection_name, collider):
    applied = set(collider.get("appliedParameters", ()))
    what = f"CollisionCollection of {collection_name}"
    if "FRICTION_COEFFICIENT_2" in applied:
        physics.lose(what, "appliedParameters", "FRICTION_COEFFICIENT_2 is X_ITE's spelling; the standard's is "
                     "FRICTION_COEFFICIENT-2 (read as the same here)")
    fc = collider.get("frictionCoefficients", (0.0, 0.0))
    if applied & {"FRICTION_COEFFICIENT-2", "FRICTION_COEFFICIENT_2"} and abs(fc[0] - fc[1]) > 1e-9:
        physics.lose(what, "frictionCoefficients", "a second friction direction: Blender's friction is isotropic, the "
                     "first value is used")
    if "BOUNCE" in applied and collider.get("bounce", 0.0) > 0 and collider.get("minBounceSpeed", 0.1) > 0:
        physics.lose(what, "minBounceSpeed", "Blender bounces at any speed")
    for parameter, field_name in APPLIED_ONLY.items():
        if parameter in applied:
            physics.lose(what, field_name, f"appliedParameters {parameter}: Blender has no such contact parameter")


# --- what Bullet makes of a shape's mass (for the start-up impulse; see physics_blender.launch) -------------------------

def principal_inertia(collision_shape, dims, mass, margin=0.04):
    """Bullet's principal moments of inertia for a Blender collision shape with these bounding dimensions (x, y, z of the
    object's local box), as btBoxShape / btSphereShape / btPolyhedralConvexShape compute them: a sphere is 0.4 m r^2, and
    every other shape uses its local box (convex shapes with the margin added on each side)."""
    if collision_shape == "SPHERE":
        r = max(dims) / 2.0
        i = 0.4 * mass * r * r
        return (i, i, i)
    pad = 0.0 if collision_shape == "BOX" else 2.0 * margin
    lx, ly, lz = (d + pad for d in dims)
    return (mass / 12.0 * (ly * ly + lz * lz), mass / 12.0 * (lx * lx + lz * lz), mass / 12.0 * (lx * lx + ly * ly))
