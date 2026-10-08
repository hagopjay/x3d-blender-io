# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-structure fixture for the X3D 4.0 path: hierarchy, lights, camera, text, animation.

Run inside Blender or with the ``bpy`` wheel::

    blender --background --python tools/scene_fixture.py -- /tmp/scene.x3d
"""

from __future__ import annotations

import math
import os
import sys

import bpy


def build_scene_fixture() -> dict:
    """Populate the current scene and return the created objects by role."""
    objects = {}
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 24
    scene.render.fps = 24
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.05, 0.1, 0.2)

    # Parent empty with a child cube (hierarchy)
    bpy.ops.object.empty_add(location=(2.0, 0.0, 1.0))
    parent = bpy.context.active_object
    parent.name = "Rig"
    parent.rotation_euler = (0.0, 0.0, math.radians(45.0))
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    child = bpy.context.active_object
    child.name = "ChildCube"
    child.data.name = "ChildCubeMesh"
    child.parent = parent
    child.location = (1.0, 0.0, 0.0)  # local offset
    objects["parent"] = parent
    objects["child"] = child

    # Lights
    bpy.ops.object.light_add(type="POINT", location=(0.0, -3.0, 4.0))
    point = bpy.context.active_object
    point.name = "KeyLight"
    point.data.energy = 1.0
    point.data.color = (1.0, 0.9, 0.8)
    objects["point"] = point

    bpy.ops.object.light_add(type="SPOT", location=(-3.0, 0.0, 4.0))
    spot = bpy.context.active_object
    spot.name = "Spot"
    spot.data.spot_size = math.radians(60.0)
    spot.rotation_euler = (math.radians(40.0), 0.0, 0.0)
    objects["spot"] = spot

    bpy.ops.object.light_add(type="SUN", location=(0.0, 0.0, 10.0))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.rotation_euler = (math.radians(30.0), math.radians(10.0), 0.0)
    objects["sun"] = sun

    # Camera
    bpy.ops.object.camera_add(location=(7.0, -7.0, 5.0), rotation=(math.radians(63.0), 0.0, math.radians(45.0)))
    camera = bpy.context.active_object
    camera.name = "MainCamera"
    camera.data.angle = math.radians(50.0)
    scene.camera = camera
    objects["camera"] = camera

    # Text object (exported as a mesh)
    bpy.ops.object.text_add(location=(-4.0, 2.0, 0.0))
    text = bpy.context.active_object
    text.name = "Label"
    text.data.body = "X3D"
    text.data.extrude = 0.05
    objects["text"] = text

    # Animated cube: translate and rotate over the frame range
    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0.0, 3.0, 0.0))
    mover = bpy.context.active_object
    mover.name = "Mover"
    mover.data.name = "MoverMesh"
    mover.keyframe_insert("location", frame=1)
    mover.keyframe_insert("rotation_euler", frame=1)
    mover.location = (3.0, 3.0, 1.0)
    mover.rotation_euler = (0.0, 0.0, math.radians(90.0))
    mover.keyframe_insert("location", frame=24)
    mover.keyframe_insert("rotation_euler", frame=24)
    scene.frame_set(1)
    objects["mover"] = mover

    return objects


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    output = argv[0] if argv else os.path.abspath("scene_fixture.x3d")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_scene_fixture()
    bpy.ops.export_scene.x3d(
        filepath=output, x3d_version="X3D40", use_hierarchy=True, use_animation=True, use_selection=False
    )
    print("wrote", output)


if __name__ == "__main__":
    main()
