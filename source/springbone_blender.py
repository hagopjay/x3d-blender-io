# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Spring bones in Blender: SpringBoneChain (x3d.loom ``x3d.springbone``) on an armature, baked to keys, and back to X3D.

Storage: the armature object's ``x3d_springbone`` property, a JSON list of chains in Blender terms::

    {"name": "Ponytail", "roots": ["hair_1"], "exclusions": [], "params": {... X3D field values, X3D axes ...},
     "colliders": [{"name": "HeadCollider", "bone": "head", "shape": "SPHERE", "center": [x, y, z], "axis": [..], ...}]}

Collider ``center`` and ``axis`` are in the bone's own frame (Blender bone space: +Y along the bone). Vectors in
``params`` (gravity, force, wind) keep X3D's axes (+Y up); the bake turns them into Blender's (+Z up) with the add-on's
default axis conversion (X3D forward -Z, up +Y).

Bake (``bake_armature``): every frame of the range is read first (the animated pose, with any earlier bake's action
set aside), then simulated with ``springbone_core`` (the same solver X_ITE runs), then written as quaternion keys into
a copy of the animation named ``<action>_spring``; the source action is kept and ``clear_bake`` puts it back.
"""

from __future__ import annotations

import json
import logging
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import springbone_core as core

logger = logging.getLogger(__name__)

PROPERTY = "x3d_springbone"
SOURCE_ACTION = "x3d_springbone_source_action"
X3D_TO_BLENDER = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))     # (x, y, z) X3D -> (x, -z, y) Blender


def get_chains(armature):
    try:
        return json.loads(armature.get(PROPERTY) or "[]")
    except (TypeError, ValueError):
        return []


def set_chains(armature, chains):
    armature[PROPERTY] = json.dumps(chains, sort_keys=True)


# --- building the solver input from the armature ------------------------------------------------------------------


def _walk(armature, root_name, exclusions):
    """Preorder bone names under root (the solver wants parents first) and their parent indices."""
    bones = armature.data.bones
    names, parents = [], []

    def visit(bone, parent):
        k = len(names)
        names.append(bone.name)
        parents.append(parent)
        for child in bone.children:
            if child.name not in exclusions:
                visit(child, k)

    if root_name in bones:
        visit(bones[root_name], -1)
    return names, parents


def _affine(m):
    """mathutils 4x4 -> solver affine (L row-major, t)."""
    return ([m[0][0], m[0][1], m[0][2], m[1][0], m[1][1], m[1][2], m[2][0], m[2][1], m[2][2]], [m[0][3], m[1][3], m[2][3]])


def _fields(local):
    t, r, _s = local.decompose()
    return {"translation": [t.x, t.y, t.z], "center": [0.0, 0.0, 0.0], "rotation": [r.x, r.y, r.z, r.w],
            "scale": [1.0, 1.0, 1.0], "scaleOrientation": [0.0, 0.0, 0.0, 1.0]}


def _blender_params(params):
    p = dict(params)
    for key in ("gravity", "force", "wind"):
        if key in p:
            p[key] = list(X3D_TO_BLENDER @ Vector(p[key]))
    return p


def _trees(armature, chain):
    excl = set(chain.get("exclusions") or [])
    trees, layouts = [], []
    p = chain.get("params") or {}
    use_tails = not p.get("endLength") and not any(p.get("endOffset") or [])
    for root in chain.get("roots") or []:
        names, parents = _walk(armature, root, excl)
        if not names:
            continue
        has_child = [False] * len(names)
        for par in parents:
            if par >= 0:
                has_child[par] = True
        joints = []
        for k, (name, par) in enumerate(zip(names, parents)):
            j = {"name": name, "parent": par}
            if use_tails and not has_child[k]:
                j["endOffset"] = [0.0, armature.data.bones[name].length, 0.0]     # the leaf's tail
            joints.append(j)
        trees.append({"joints": joints})
        layouts.append(names)
    return trees, layouts


def _parent_world(armature, bone_name):
    pb = armature.pose.bones[bone_name]
    parent = pb.parent.matrix if pb.parent is not None else Matrix.Identity(4)
    return armature.matrix_world @ parent


def _collider_world(armature, collider):
    bone = collider.get("bone")
    if bone and bone in armature.pose.bones:
        return armature.matrix_world @ armature.pose.bones[bone].matrix
    obj = bpy.data.objects.get(collider.get("object") or "")
    return obj.matrix_world.copy() if obj is not None else armature.matrix_world.copy()


def _sample(scene, armature, chains, frames):
    """Read the animated pose of every chain bone (and collider frame) at every frame."""
    samples = []
    for f in frames:
        scene.frame_set(f)
        frame = []
        for chain in chains:
            _trees_desc, layouts = chain["_layout"]
            trees = []
            for names in layouts:
                pose = []
                for name in names:
                    pb = armature.pose.bones[name]
                    parent = pb.parent.matrix if pb.parent is not None else Matrix.Identity(4)
                    pose.append(_fields(parent.inverted() @ pb.matrix))
                trees.append({"parentWorld": _affine(_parent_world(armature, names[0])), "pose": pose})
            colls = []
            for c in chain.get("colliders") or []:
                cw = _collider_world(armature, c)
                colls.append({"shape": c.get("shape", "SPHERE"), "bound": c.get("bound", "OUTSIDE"),
                              "center": c.get("center", [0, 0, 0]), "radius": c.get("radius", 0.5),
                              "radius2": c.get("radius2", 0.0), "height": c.get("height", 0.0),
                              "direction": c.get("direction", "Y"), "axis": c.get("axis", [0, 0, 0]), "world": _affine(cw)})
            frame.append({"trees": trees, "colliders": colls, "reference": _affine(armature.matrix_world)})
        samples.append(frame)
    return samples


def bake_armature(context, armature, frame_start=None, frame_end=None):
    """Simulate every chain on ``armature`` over the frame range and key the result. Returns a receipt dict."""
    scene = context.scene
    chains = get_chains(armature)
    if not chains:
        return {"chains": 0}
    clear_bake(armature)                       # read the source animation, not an earlier bake
    f0 = scene.frame_start if frame_start is None else frame_start
    f1 = scene.frame_end if frame_end is None else frame_end
    frames = list(range(f0, f1 + 1))
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    for chain in chains:
        chain["_layout"] = _trees(armature, chain)
    current = scene.frame_current
    samples = _sample(scene, armature, chains, frames)
    results = []          # per chain: per frame: per tree: rotations
    receipt = {"chains": len(chains), "frames": len(frames), "fps": fps, "steps": [], "hash": []}
    for ci, chain in enumerate(chains):
        trees_desc, layouts = chain["_layout"]
        solver = core.SpringChain(trees_desc, _blender_params(chain.get("params") or {}))
        per_frame, tips = [], []
        for fi, f in enumerate(frames):
            s = samples[fi][ci]
            out = solver.frame({"dt": 0 if fi == 0 else 1 / fps, "time": fi / fps, "trees": s["trees"],
                                "reference": s["reference"], "colliders": s["colliders"]})
            per_frame.append([t["rotations"] for t in out["trees"]])
            tips.append([round(x, 9) for x in out["trees"][0]["positions"][-1]] if out["trees"] else None)
        results.append(per_frame)
        receipt.setdefault("tips", []).append(tips)
        receipt["steps"].append(solver.steps)
        receipt["hash"].append(solver.state_hash())
    # write: a copy of the source action, so the source stays untouched
    ad = armature.animation_data or armature.animation_data_create()
    source = ad.action
    if source is not None:
        armature[SOURCE_ACTION] = source.name
        baked = source.copy()
        baked.name = f"{source.name}_spring"
    else:
        armature[SOURCE_ACTION] = ""
        baked = bpy.data.actions.new(f"{armature.name}_spring")
    ad.action = baked
    keyed = 0
    for ci, chain in enumerate(chains):
        trees_desc, layouts = chain["_layout"]
        for fi, f in enumerate(frames):
            for ti, names in enumerate(layouts):
                rots = results[ci][fi][ti]
                pose = samples[fi][ci]["trees"][ti]["pose"]
                for k, name in enumerate(names):
                    q = rots[k]
                    if q is None:
                        continue
                    bone = armature.data.bones[name]
                    pb = armature.pose.bones[name]
                    parent_rest = bone.parent.matrix_local if bone.parent is not None else Matrix.Identity(4)
                    rest_rel = parent_rest.inverted() @ bone.matrix_local
                    t = Vector(pose[k]["translation"])
                    local = Matrix.Translation(t) @ Quaternion((q[3], q[0], q[1], q[2])).to_matrix().to_4x4()
                    basis = rest_rel.inverted() @ local
                    pb.rotation_mode = "QUATERNION"
                    pb.rotation_quaternion = basis.to_quaternion()
                    pb.keyframe_insert("rotation_quaternion", frame=f, group=name)
                    keyed += 1
    scene.frame_set(current)
    receipt["keys"] = keyed
    receipt["action"] = baked.name
    for chain in chains:
        chain.pop("_layout", None)
    armature["x3d_springbone_receipt"] = json.dumps(receipt)
    return receipt


def clear_bake(armature):
    """Put the source action back (the baked copy stays in bpy.data until it has no users)."""
    name = armature.get(SOURCE_ACTION)
    if name is None:
        return False
    ad = armature.animation_data
    if ad is not None:
        ad.action = bpy.data.actions.get(name) if name else None
    del armature[SOURCE_ACTION]
    return True


# --- import: X3D chains onto the armatures the HAnim import made --------------------------------------------------


def import_chains(chains, joint_bone, losses):
    """chains from springbone_model.read_springbones; joint_bone(DEF) -> (armature, bone name) or (None, None).
    Stores each chain on its armature. Returns {armature name: number of chains}."""
    made = {}
    for chain in chains:
        targets = [joint_bone(d) if d else (None, None) for d in chain["roots"]]
        armatures = {a.name: a for a, _b in targets if a is not None}
        if len(armatures) != 1:
            losses.append((f"SpringBoneChain {chain['name']}", "roots",
                           "its roots are not HAnimJoints of one imported humanoid (Transform chains are not baked yet)"))
            continue
        armature = next(iter(armatures.values()))
        roots = [b for a, b in targets if a is armature]
        excl = [joint_bone(d)[1] for d in chain["exclusions"] if d and joint_bone(d)[0] is armature]
        colliders = []
        for c in chain["colliders"]:
            last = c["ancestors"][-1] if c["ancestors"] else None
            arm, bone_name = joint_bone(last) if last else (None, None)
            entry = {k: c[k] for k in ("name", "shape", "bound", "radius", "radius2", "height", "direction", "enabled")}
            center, axis = Vector(c["center"]), Vector(c["axis"])
            if c["direction"] in ("X", "Y", "Z") and not any(c["axis"]):
                axis = Vector([1.0 if c["direction"] == a else 0.0 for a in "XYZ"])
            if arm is armature:
                # an HAnimJoint's frame at rest is the humanoid's (joints carry centers, not offsets): the armature's
                # space as the HAnim import builds it. Into the bone's own frame:
                rest = armature.data.bones[bone_name].matrix_local
                entry["bone"] = bone_name
                entry["center"] = list(rest.inverted() @ center)
                entry["axis"] = list((rest.to_3x3().inverted() @ axis).normalized())
            else:
                entry["object"] = None
                entry["center"] = list(center)
                entry["axis"] = list(axis)
                losses.append((f"SpringBoneCollider {c['name']}", "ancestors", "not on a joint of this humanoid: kept in world space, fixed"))
            colliders.append(entry)
        if chain["ancestors"]:
            last = chain["ancestors"][-1]
            arm, _b = joint_bone(last)
            if arm is None and last:
                pass        # the humanoid itself or a Transform above it: the armature's own world matrix covers it
        stored = get_chains(armature)
        stored.append({"name": chain["name"], "roots": roots, "exclusions": excl, "params": chain["params"],
                       "colliders": colliders})
        set_chains(armature, stored)
        made[armature.name] = made.get(armature.name, 0) + 1
    return made


# --- export: chains to X3D text for the exporter ------------------------------------------------------------------


def export_plan(armature):
    """What the exporter needs, in armature space (= the HAnimHumanoid's space): per chain the root and exclusion bone
    names, the ancestor bone path, params, and colliders with center/axis turned from bone space to armature space."""
    plan = []
    bones = armature.data.bones
    for chain in get_chains(armature):
        roots = [r for r in chain.get("roots") or [] if r in bones]
        if not roots:
            continue
        first = bones[roots[0]]
        path = []
        b = first.parent
        while b is not None:
            path.append(b.name)
            b = b.parent
        path.reverse()
        colliders = []
        for c in chain.get("colliders") or []:
            bone = c.get("bone")
            if not bone or bone not in bones:
                continue
            rest = bones[bone].matrix_local
            cpath = []
            b = bones[bone]
            while b is not None:
                cpath.append(b.name)
                b = b.parent
            cpath.reverse()
            center = rest @ Vector(c.get("center") or (0, 0, 0))
            axis = (rest.to_3x3() @ Vector(c.get("axis") or (0, 1, 0)))
            axis = axis.normalized() if axis.length > 0 else Vector((0, 1, 0))
            params = {k: c[k] for k in ("shape", "bound", "radius", "radius2", "height", "enabled") if k in c}
            params["center"] = [round(x, 9) for x in center]
            params["axis"] = [round(x, 9) for x in axis]
            colliders.append({"name": c.get("name") or f"{chain['name']}_{bone}_collider", "bone_path": cpath, "params": params})
        plan.append({"name": chain.get("name") or "SpringBoneChain", "roots": roots, "parent_path": path,
                     "exclusions": [e for e in chain.get("exclusions") or [] if e in bones],
                     "params": chain.get("params") or {}, "colliders": colliders})
    return plan


# --- operators and panel ------------------------------------------------------------------------------------------


class X3D_OT_springbone_add(bpy.types.Operator):
    """Make the selected bones the roots of a new spring-bone chain (hair, tail, cloth strip) on this armature"""
    bl_idname = "x3d.springbone_add"
    bl_label = "Add Spring Bone Chain"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(name="Name", default="SpringBoneChain")
    frequency: bpy.props.FloatProperty(name="Frequency (Hz)", default=1.5, min=0.0, soft_max=10.0)
    damping_ratio: bpy.props.FloatProperty(name="Damping ratio", default=0.25, min=0.0, soft_max=2.0)
    stiffness: bpy.props.FloatProperty(name="Stiffness", default=0.05, min=0.0, max=1.0)
    gravity: bpy.props.FloatProperty(name="Gravity (m/s²)", default=9.81, min=0.0, soft_max=30.0)
    radius: bpy.props.FloatProperty(name="Radius (m)", default=0.0, min=0.0, soft_max=0.2)
    angle_limit: bpy.props.FloatProperty(name="Angle limit (°)", default=0.0, min=0.0, max=180.0)

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'ARMATURE'

    def execute(self, context):
        armature = context.object
        # Blender 5 keeps bone selection on pose bones; older versions on bones
        roots = [pb.name for pb in (getattr(context, "selected_pose_bones", None) or [])]
        roots += [b.name for b in armature.data.bones if getattr(b, "select", False) and b.name not in roots]
        if context.active_bone is not None and context.active_bone.name not in roots:
            roots.append(context.active_bone.name)
        selected = set(roots)
        roots = [r for r in roots if not any(p.name in selected for p in armature.data.bones[r].parent_recursive)]
        if not roots:
            self.report({'ERROR'}, "Select the first bone of each chain")
            return {'CANCELLED'}
        chains = get_chains(armature)
        chains.append({"name": self.name, "roots": roots, "exclusions": [], "colliders": [],
                       "params": {"springModel": "FORCE", "frequency": self.frequency, "dampingRatio": self.damping_ratio,
                                  "stiffness": self.stiffness, "gravity": [0.0, -self.gravity, 0.0], "forceUnits": "M_PER_S2",
                                  "gravityRestCompensation": True, "radius": self.radius, "angleLimit": self.angle_limit}})
        set_chains(armature, chains)
        self.report({'INFO'}, f"Spring chain {self.name!r} on {', '.join(roots)}")
        return {'FINISHED'}


class X3D_OT_springbone_collider_add(bpy.types.Operator):
    """Add a collider on the active bone to every spring-bone chain of this armature"""
    bl_idname = "x3d.springbone_collider_add"
    bl_label = "Add Spring Bone Collider"
    bl_options = {'REGISTER', 'UNDO'}

    shape: bpy.props.EnumProperty(name="Shape", items=(('SPHERE', "Sphere", ""), ('CAPSULE', "Capsule", ""), ('PLANE', "Plane", "")))
    radius: bpy.props.FloatProperty(name="Radius", default=0.1, min=0.0)
    radius2: bpy.props.FloatProperty(name="Tip radius", default=0.0, min=0.0)
    along: bpy.props.FloatProperty(name="Centre along bone", default=0.5, min=0.0, max=1.0)

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE' and context.active_bone is not None

    def execute(self, context):
        armature = context.object
        bone = armature.data.bones[context.active_bone.name]
        entry = {"name": f"{bone.name}_collider", "bone": bone.name, "shape": self.shape, "bound": "OUTSIDE",
                 "center": [0.0, bone.length * self.along, 0.0], "axis": [0.0, 1.0, 0.0], "radius": self.radius,
                 "radius2": self.radius2, "height": bone.length if self.shape == 'CAPSULE' else 0.0, "direction": "Y", "enabled": True}
        chains = get_chains(armature)
        for chain in chains:
            chain.setdefault("colliders", []).append(dict(entry))
        set_chains(armature, chains)
        return {'FINISHED'}


class X3D_OT_springbone_bake(bpy.types.Operator):
    """Simulate this armature's spring-bone chains over the scene's frame range and key them (the source action is kept)"""
    bl_idname = "x3d.springbone_bake"
    bl_label = "Bake Spring Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE' and bool(get_chains(context.object))

    def execute(self, context):
        receipt = bake_armature(context, context.object)
        self.report({'INFO'}, f"Baked {receipt.get('chains', 0)} chain(s), {receipt.get('keys', 0)} keys")
        return {'FINISHED'}


class X3D_OT_springbone_clear(bpy.types.Operator):
    """Put back the animation the spring-bone bake started from"""
    bl_idname = "x3d.springbone_clear"
    bl_label = "Clear Spring Bake"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        clear_bake(context.object)
        return {'FINISHED'}


class X3D_PT_springbone(bpy.types.Panel):
    bl_label = "X3D Spring Bones"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        armature = context.object
        for chain in get_chains(armature):
            box = layout.box()
            p = chain.get("params") or {}
            box.label(text=f"{chain.get('name')}: {', '.join(chain.get('roots') or [])}", icon='BONE_DATA')
            if p.get("frequency"):
                box.label(text=f"{p.get('frequency')} Hz, damping ratio {p.get('dampingRatio')}, {p.get('springModel', 'POSITION')}")
            else:
                eq = core.physical_from_tuning(p.get("damping", 0.1), p.get("elasticity", 0.1), p.get("updateRate", 60.0), p.get("springModel", "POSITION"))
                box.label(text=f"damping {p.get('damping', 0.1)}, elasticity {p.get('elasticity', 0.1)} ≈ {eq['frequency']:.2f} Hz, ζ {eq['dampingRatio']:.2f}")
            box.label(text=f"{len(chain.get('colliders') or [])} collider(s)")
        row = layout.row()
        row.operator(X3D_OT_springbone_add.bl_idname, icon='ADD')
        row.operator(X3D_OT_springbone_collider_add.bl_idname, icon='MESH_UVSPHERE')
        row = layout.row()
        row.operator(X3D_OT_springbone_bake.bl_idname, icon='REC')
        row.operator(X3D_OT_springbone_clear.bl_idname, icon='LOOP_BACK')


classes = (X3D_OT_springbone_add, X3D_OT_springbone_collider_add, X3D_OT_springbone_bake, X3D_OT_springbone_clear,
           X3D_PT_springbone)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
