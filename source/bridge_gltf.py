# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os

import addon_utils
import bpy


def enable_gltf_importer() -> bool:
    enabled, loaded = addon_utils.check("io_scene_gltf2")
    if enabled and loaded:
        return True
    try:
        addon_utils.enable("io_scene_gltf2", default_set=False, persistent=False)
    except Exception:
        return False
    enabled, loaded = addon_utils.check("io_scene_gltf2")
    return enabled and loaded


def import_gltf(filepath: str) -> list[str]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(filepath)
    if not enable_gltf_importer():
        raise RuntimeError("Blender glTF importer addon io_scene_gltf2 is unavailable.")

    before = {obj.name for obj in bpy.context.scene.objects}
    result = bpy.ops.import_scene.gltf(filepath=filepath)
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF import did not finish successfully for {filepath!r}: {result!r}")
    after = {obj.name for obj in bpy.context.scene.objects}
    return sorted(after - before)


def imported_material_names(object_names: list[str]) -> list[str]:
    names: set[str] = set()
    for object_name in object_names:
        obj = bpy.context.scene.objects.get(object_name)
        if obj is None:
            continue
        for slot in getattr(obj, "material_slots", []):
            material = getattr(slot, "material", None)
            if material is not None:
                names.add(material.name)
    return sorted(names)
