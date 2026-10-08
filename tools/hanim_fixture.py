# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HAnim fixture: a two-bone armature skinning a cylinder, with a posed keyframe.

    blender --background --python tools/hanim_fixture.py -- /tmp/hanim.x3d
"""

from __future__ import annotations

import math
import os
import sys

import bpy


def build_hanim_fixture() -> dict:
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 24
    scene.render.fps = 24

    bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
    armature = bpy.context.active_object
    armature.name = "Rig"
    armature.data.name = "RigData"
    edit_bones = armature.data.edit_bones
    lower = edit_bones[0]
    lower.name = "lower"
    lower.head = (0.0, 0.0, 0.0)
    lower.tail = (0.0, 0.0, 1.0)
    upper = edit_bones.new("upper")
    upper.head = (0.0, 0.0, 1.0)
    upper.tail = (0.0, 0.0, 2.0)
    upper.parent = lower
    upper.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.2, depth=2.0, location=(0.0, 0.0, 1.0))
    skin = bpy.context.active_object
    skin.name = "Arm"
    skin.data.name = "ArmMesh"
    material = bpy.data.materials.new("Skin")
    if not material.use_nodes:
        material.use_nodes = True
    material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.9, 0.7, 0.6, 1.0)
    skin.data.materials.append(material)

    lower_group = skin.vertex_groups.new(name="lower")
    upper_group = skin.vertex_groups.new(name="upper")
    for vertex in skin.data.vertices:
        z = vertex.co.z + 1.0  # cylinder spans z in [-1, 1] locally; shift to [0, 2]
        weight_upper = max(0.0, min(1.0, z - 0.5))
        if weight_upper > 0.0:
            upper_group.add([vertex.index], weight_upper, "REPLACE")
        if weight_upper < 1.0:
            lower_group.add([vertex.index], 1.0 - weight_upper, "REPLACE")
    modifier = skin.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    skin.parent = armature

    # Pose: bend the upper bone 60 degrees about X at frame 24
    bpy.context.view_layer.objects.active = armature
    pose_bone = armature.pose.bones["upper"]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = (0.0, 0.0, 0.0)
    pose_bone.keyframe_insert("rotation_euler", frame=1)
    pose_bone.rotation_euler = (math.radians(60.0), 0.0, 0.0)
    pose_bone.keyframe_insert("rotation_euler", frame=24)
    scene.frame_set(1)
    return {"armature": armature, "skin": skin}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    output = argv[0] if argv else os.path.abspath("hanim_fixture.x3d")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_hanim_fixture()
    bpy.ops.export_scene.x3d(filepath=output, x3d_version="X3D40", use_animation=True, use_selection=False)
    print("wrote", output)


if __name__ == "__main__":
    main()
