# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import bpy


REPO_ROOT = Path(__file__).resolve().parents[2]
ADDON_SOURCE_DIR = REPO_ROOT / "io_scene_x3d" / "source"
DEMO_DIR = REPO_ROOT / "demo" / "investor_poc"
INPUT_X3D = DEMO_DIR / "xite_gltf_inline_poc.x3d"
OUTPUT_REPORT = DEMO_DIR / "single_inline_import_report.json"


def _load_addon_package():
    package_name = "io_scene_x3d"
    if package_name in sys.modules:
        return sys.modules[package_name]

    spec = importlib.util.spec_from_file_location(
        package_name,
        ADDON_SOURCE_DIR / "__init__.py",
        submodule_search_locations=[str(ADDON_SOURCE_DIR)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to create addon module spec for io_scene_x3d")

    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return module


def _reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def main():
    if not INPUT_X3D.exists():
        raise FileNotFoundError(f"Expected demo file at {INPUT_X3D}")

    os.environ["BLENDER_X3D_IMPORT_TARGET"] = "MODERN_INLINE"
    _load_addon_package()
    _reset_scene()

    before = {obj.name for obj in bpy.context.scene.objects}

    from io_scene_x3d import import_x3d

    import_x3d.load(
        bpy.context,
        filepath=str(INPUT_X3D),
        global_scale=1.0,
        global_matrix=None,
        as_collection=False,
        solidify=False,
        solidify_value=0.1,
    )

    after = {obj.name for obj in bpy.context.scene.objects}
    imported = sorted(after - before)
    print(f"Imported objects: {imported}")
    print(f"Imported object count: {len(imported)}")

    inline_library = bpy.data.collections.get("X3DInlineAssets")
    if inline_library is None:
        raise RuntimeError("Modern Inline import did not create the X3DInlineAssets collection.")
    if inline_library.get("x3d_scene_title") != "Blender glTF Inline PoC":
        raise RuntimeError("Inline library collection is missing scene title metadata.")

    viewpoint_library = bpy.data.collections.get("X3DViewpoints")
    if viewpoint_library is None:
        raise RuntimeError("Modern Inline import did not create the X3DViewpoints collection.")

    inline_roots = sorted(obj.name for obj in bpy.context.scene.objects if obj.name.startswith("X3DInline_"))
    print(f"Inline root objects: {inline_roots}")

    for name in imported:
        obj = bpy.context.scene.objects[name]
        print(
            f"Object {name}: parent={getattr(obj.parent, 'name', None)} "
            f"collections={[collection.name for collection in obj.users_collection]} "
            f"inline_source={obj.get('x3d_inline_source')}"
        )

    if not imported:
        raise RuntimeError("Modern Inline import did not create any Blender objects.")
    if not inline_roots:
        raise RuntimeError("Modern Inline import did not create any root empty objects.")

    root = bpy.context.scene.objects[inline_roots[0]]
    expected_location = (2.0, 1.0, 0.5)
    expected_scale = (1.25, 1.25, 1.25)
    expected_axis_angle = (0.6, 0.0, 1.0, 0.0)

    actual_location = tuple(round(value, 4) for value in root.location)
    actual_scale = tuple(round(value, 4) for value in root.scale)
    actual_axis_angle = tuple(round(value, 4) for value in root.rotation_axis_angle)

    print(f"Inline root transform: location={actual_location} scale={actual_scale} axis_angle={actual_axis_angle}")
    print(
        "Inline root metadata: "
        f"title={root.get('x3d_scene_title')} "
        f"creator={root.get('x3d_scene_creator')} "
        f"source_path={root.get('x3d_scene_source_path')}"
    )

    scene_camera = bpy.context.scene.camera
    if scene_camera is None:
        raise RuntimeError("Modern Inline import did not create an active scene camera from Viewpoint.")
    print(
        "Scene camera: "
        f"name={scene_camera.name} "
        f"location={tuple(round(value, 4) for value in scene_camera.location)} "
        f"axis_angle={tuple(round(value, 4) for value in scene_camera.rotation_axis_angle)} "
        f"fov={round(scene_camera.data.angle, 4)}"
    )
    print(f"Scene navigation types: {bpy.context.scene.get('x3d_navigation_types')}")

    if actual_location != expected_location:
        raise RuntimeError(f"Inline root translation mismatch: expected {expected_location}, got {actual_location}")
    if actual_scale != expected_scale:
        raise RuntimeError(f"Inline root scale mismatch: expected {expected_scale}, got {actual_scale}")
    if actual_axis_angle != expected_axis_angle:
        raise RuntimeError(f"Inline root rotation mismatch: expected {expected_axis_angle}, got {actual_axis_angle}")
    if root.get("x3d_scene_title") != "Blender glTF Inline PoC":
        raise RuntimeError("Inline root is missing scene title metadata.")
    if scene_camera.get("x3d_viewpoint_description") != "Investor View":
        raise RuntimeError("Scene camera is missing Viewpoint description metadata.")
    if bpy.context.scene.get("x3d_navigation_types") != "EXAMINE|ANY":
        raise RuntimeError("Scene navigation types were not populated from NavigationInfo.")

    report = {
        "scene": INPUT_X3D.name,
        "imported_objects": imported,
        "inline_roots": inline_roots,
        "root_transform": {
            "location": actual_location,
            "scale": actual_scale,
            "axis_angle": actual_axis_angle,
        },
        "scene_camera": {
            "name": scene_camera.name,
            "location": tuple(round(value, 4) for value in scene_camera.location),
            "axis_angle": tuple(round(value, 4) for value in scene_camera.rotation_axis_angle),
            "fov": round(scene_camera.data.angle, 4),
        },
        "navigation_types": bpy.context.scene.get("x3d_navigation_types"),
        "root_metadata": {
            "title": root.get("x3d_scene_title"),
            "creator": root.get("x3d_scene_creator"),
            "source_path": root.get("x3d_scene_source_path"),
        },
    }
    OUTPUT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote report to {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
