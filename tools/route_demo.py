# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build the "Blender ROUTE interaction" demo scene and export it as X3D 4.0.

Every interaction is a custom property (see source/interaction.py); the exported file has TouchSensor,
ProximitySensor, TimeSensor, interpolators and ROUTEs, and no Script. Run with the ``bpy`` wheel or Blender::

    python tools/route_demo.py /tmp/route-demo.x3d
"""

from __future__ import annotations

import importlib
import math
import os
import sys
import tempfile
from pathlib import Path

import bpy

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"


def register_extension():
    package_dir = Path(tempfile.mkdtemp(prefix="x3d_route_demo_")) / "io_scene_x3d"
    package_dir.symlink_to(SOURCE_DIR, target_is_directory=True)
    sys.path.insert(0, str(package_dir.parent))
    importlib.import_module("io_scene_x3d").register()


def material(name, rgb, metallic=0.0, roughness=0.5, emission=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 1.0
    return mat


def add(kind, name, mat, location, scale=(1, 1, 1), **kwargs):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(location=location, **kwargs)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    return obj


def key(obj, frame, **values):
    for path, value in values.items():
        setattr(obj, path, value)
        obj.keyframe_insert(path, frame=frame)


def camera(name, location, target, **props):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = location
    direction = (bpy.context.scene.cursor.location.__class__(target) - cam.location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 28
    for prop, value in props.items():
        cam[prop] = value
    return cam


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 48            # 48 frames at 24 fps: every animation is a 2 s cycle
    scene.render.fps = 24
    scene.render.resolution_x, scene.render.resolution_y = 960, 600

    stone = material("Stone", (0.42, 0.40, 0.38), roughness=0.9)
    door_m = material("Door", (0.55, 0.18, 0.10), metallic=0.3, roughness=0.4)
    green = material("ButtonGreen", (0.05, 0.6, 0.15), emission=(0.0, 0.5, 0.1))
    blue = material("ButtonBlue", (0.1, 0.25, 0.8), emission=(0.0, 0.15, 0.6))
    orange = material("ButtonOrange", (0.95, 0.5, 0.05), emission=(0.8, 0.3, 0.0))
    gold = material("Beacon", (0.9, 0.7, 0.2), metallic=0.35, roughness=0.3, emission=(0.35, 0.25, 0.0))
    teal = material("Spinner", (0.1, 0.6, 0.6), metallic=0.2, roughness=0.3)

    # Cameras first: the first Viewpoint in the file is the one X3D binds at load.
    camera("Start", (0, -11, 4.5), (0, 0, 1.0), x3d_viewpoint_description="Start")
    camera("Overview", (0, -2, 15), (0, 0, 0), x3d_viewpoint_description="Overview")
    tour = [("Tour1_Gate", (-6, -6, 2.0), (0, 0, 1.2)), ("Tour2_Beacon", (6.5, 2, 2.5), (4.5, 4.5, 1.0)),
            ("Tour3_Spinner", (-5, 6, 3), (-4.5, 4.5, 1.0)), ("Tour4_High", (0, -9, 9), (0, 0, 0))]
    for index, (name, loc, target) in enumerate(tour, start=1):
        camera(name, loc, target, x3d_tour_order=index, x3d_tour_dwell=1.5, x3d_viewpoint_description=f"Tour stop {index}")
    scene["x3d_tour_travel"] = 2.5

    add("plane", "Floor", stone, (0, 0, 0), (1, 1, 1), size=18)

    # 1. Click a button, a *different* object plays its animation: the door slides up.
    add("cube", "PillarL", stone, (-1.6, 0, 1.2), (0.3, 0.3, 1.2))
    add("cube", "PillarR", stone, (1.6, 0, 1.2), (0.3, 0.3, 1.2))
    door = add("cube", "Door", door_m, (0, 0, 1.1), (1.3, 0.2, 1.1))
    key(door, 1, location=(0, 0, 1.1))
    key(door, 40, location=(0, 0, 3.4))
    door.keyframe_insert("location", frame=48)
    btn = add("cylinder", "DoorButton", green, (-3.2, -2.5, 0.25), (0.5, 0.5, 0.25))
    btn["x3d_trigger"], btn["x3d_action"], btn["x3d_target"] = "click", "animate", "Door"

    # 2. Walk up to it: a proximity sensor plays the beacon's own animation.
    beacon = add("ico_sphere", "Beacon", gold, (4.5, 4.5, 0.6), (0.6, 0.6, 0.6), subdivisions=3)
    key(beacon, 1, location=(4.5, 4.5, 0.6), rotation_euler=(0, 0, 0))
    key(beacon, 48, location=(4.5, 4.5, 2.2), rotation_euler=(0, 0, math.tau))
    beacon["x3d_trigger"], beacon["x3d_action"], beacon["x3d_radius"] = "proximity", "animate", 3.5

    # 3. Always running: no trigger, so it keeps the free-running scene timer.
    spinner = add("cube", "Spinner", teal, (-4.5, 4.5, 1.0), (0.7, 0.7, 0.7))
    key(spinner, 1, rotation_euler=(0, 0, 0))
    key(spinner, 48, rotation_euler=(math.tau / 2, 0, math.tau))
    for fc in _fcurves(spinner):
        for point in fc.keyframe_points:
            point.interpolation = "LINEAR"

    # 4. Click a button, jump to a camera.
    jump = add("cylinder", "OverviewButton", blue, (3.2, -2.5, 0.25), (0.5, 0.5, 0.25))
    jump["x3d_trigger"], jump["x3d_action"], jump["x3d_target"] = "click", "viewpoint", "Overview"

    # 5. Click a button, fly the camera tour.
    start = add("cylinder", "TourButton", orange, (0, -4.5, 0.25), (0.5, 0.5, 0.25))
    start["x3d_trigger"], start["x3d_action"] = "click", "tour"

    scene.frame_set(1)          # leave every animated object at its frame-1 pose: that is the pose the file loads in
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    scene.collection.objects.link(sun)
    scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.35, 0.5, 0.75, 1.0)


def _fcurves(obj):
    action = obj.animation_data.action
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None and len(fcurves):
        return fcurves
    return action.layers[0].strips[0].channelbag(action.slots[0]).fcurves


def main():
    out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else (sys.argv[1] if len(sys.argv) > 1 else "route-demo.x3d")
    register_extension()
    build()
    result = bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False, use_animation=True,
                                      meta_title="Blender ROUTE interaction demo",
                                      meta_description="Click, proximity and camera-tour interactions authored from Blender custom properties.")
    if len(sys.argv) > 2 and "--blend" in sys.argv:
        bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--blend") + 1])
    print("export:", result, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
