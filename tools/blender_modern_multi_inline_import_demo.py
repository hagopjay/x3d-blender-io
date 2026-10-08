# SPDX-FileCopyrightText: 2026 OpenAI
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
INPUT_X3D = DEMO_DIR / "xite_gltf_multi_inline_poc.x3d"
OUTPUT_REPORT = DEMO_DIR / "multi_inline_import_report.json"


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

    inline_roots = sorted(
        (obj for obj in bpy.context.scene.objects if obj.name.startswith("X3DInline_")),
        key=lambda obj: obj.name,
    )
    print(f"Inline roots: {[obj.name for obj in inline_roots]}")
    if len(inline_roots) != 2:
        raise RuntimeError(f"Expected 2 inline roots, got {len(inline_roots)}")

    expected = [
        ((-4.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        ((4.0, 0.0, 0.0), (0.8, 0.8, 0.8)),
    ]
    expected_sources = ["blender_scene.glb", "blender_scene_alt.glb"]
    actual = [
        (
            tuple(round(value, 4) for value in root.location),
            tuple(round(value, 4) for value in root.scale),
        )
        for root in inline_roots
    ]
    print(f"Inline root transforms: {actual}")

    if actual != expected:
        raise RuntimeError(f"Inline root transforms mismatch: expected {expected}, got {actual}")

    child_counts = []
    root_reports = []
    for root, expected_source in zip(inline_roots, expected_sources):
        children = sorted(child.name for child in root.children)
        child_counts.append(len(children))
        print(f"Root {root.name} children: {children}")
        if len(children) < 2:
            raise RuntimeError(f"Inline root {root.name} did not receive the imported GLB children.")
        for child_name in children:
            child = bpy.context.scene.objects[child_name]
            if child.get("x3d_inline_source") != expected_source:
                raise RuntimeError(f"Imported child {child_name} is missing inline source provenance.")
        if root.get("x3d_inline_url") != expected_source:
            raise RuntimeError(f"Inline root {root.name} has wrong source URL metadata.")
        root_reports.append(
            {
                "name": root.name,
                "source": expected_source,
                "location": tuple(round(value, 4) for value in root.location),
                "scale": tuple(round(value, 4) for value in root.scale),
                "children": children,
            }
        )

    tagged_materials = sorted(
        (material.name, material.get("x3d_inline_source"))
        for material in bpy.data.materials
        if material.get("x3d_inline_source") in set(expected_sources)
    )
    print(f"Tagged inline materials: {tagged_materials}")
    if len(tagged_materials) < 4:
        raise RuntimeError("Expected imported materials to be tagged with inline provenance.")

    scene_camera = bpy.context.scene.camera
    if scene_camera is None or scene_camera.name != "Wide Investor View":
        raise RuntimeError("Expected the wide authored Viewpoint camera to become the scene camera.")
    print(
        "Scene camera: "
        f"name={scene_camera.name} "
        f"location={tuple(round(value, 4) for value in scene_camera.location)} "
        f"fov={round(scene_camera.data.angle, 4)}"
    )

    if bpy.context.scene.get("x3d_navigation_types") != "EXAMINE|ANY":
        raise RuntimeError("Scene navigation types were not preserved for the multi-inline scene.")

    report = {
        "scene": INPUT_X3D.name,
        "inline_roots": root_reports,
        "tagged_materials": tagged_materials,
        "scene_camera": {
            "name": scene_camera.name,
            "location": tuple(round(value, 4) for value in scene_camera.location),
            "fov": round(scene_camera.data.angle, 4),
        },
        "navigation_types": bpy.context.scene.get("x3d_navigation_types"),
    }
    OUTPUT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote report to {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
