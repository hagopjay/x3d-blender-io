# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os

import bpy

from .bridge_gltf import import_gltf, imported_material_names


def _apply_transform(obj, transform):
    if transform is None:
        return
    tx, ty, tz = transform.translation
    rx, ry, rz, ra = transform.rotation_axis_angle
    sx, sy, sz = transform.scale
    obj.location = (tx, ty, tz)
    obj.rotation_mode = "AXIS_ANGLE"
    obj.rotation_axis_angle = (ra, rx, ry, rz)
    obj.scale = (sx, sy, sz)


def _resolve_inline_path(source_path: str | None, inline_url: str) -> str:
    if os.path.isabs(inline_url):
        return inline_url
    if source_path:
        return os.path.normpath(os.path.join(os.path.dirname(source_path), inline_url))
    return os.path.normpath(inline_url)


def _safe_name(name: str) -> str:
    clean = []
    for index, char in enumerate(name or "InlineAsset"):
        if char.isalnum() or char == "_":
            clean.append(char)
        else:
            clean.append("_")
        if index == 0 and clean[-1].isdigit():
            clean[-1] = "_"
    return "".join(clean) or "InlineAsset"


def _ensure_inline_collection(scene_collection, collection_name: str):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
    if collection not in list(scene_collection.children):
        scene_collection.children.link(collection)
    return collection


def _create_inline_root(collection, asset_index: int, inline_asset, resolved_path: str):
    root_name = f"X3DInline_{asset_index:03d}_{_safe_name(os.path.basename(resolved_path))}"
    root = bpy.data.objects.new(root_name, None)
    root.empty_display_type = "PLAIN_AXES"
    root["x3d_inline_url"] = inline_asset.url
    root["x3d_inline_resolved_path"] = resolved_path
    root["x3d_inline_asset_type"] = inline_asset.asset_type
    root["x3d_import_policy"] = inline_asset.import_policy
    collection.objects.link(root)
    return root


def _apply_scene_metadata(id_block, ir_scene):
    metadata = ir_scene.metadata
    if metadata.title:
        id_block["x3d_scene_title"] = metadata.title
    if metadata.creator:
        id_block["x3d_scene_creator"] = metadata.creator
    if metadata.description:
        id_block["x3d_scene_description"] = metadata.description
    if ir_scene.source_path:
        id_block["x3d_scene_source_path"] = ir_scene.source_path


def _move_object_to_collection(obj, target_collection):
    if target_collection not in obj.users_collection:
        target_collection.objects.link(obj)
    for collection in list(obj.users_collection):
        if collection != target_collection:
            collection.objects.unlink(obj)


def _tag_imported_materials(material_names, inline_asset, resolved_path: str, asset_index: int):
    for material_name in material_names:
        material = bpy.data.materials.get(material_name)
        if material is None:
            continue
        material["x3d_inline_source"] = inline_asset.url
        material["x3d_inline_resolved_path"] = resolved_path
        material["x3d_inline_asset_index"] = asset_index


def _populate_viewpoints(context, ir_scene):
    if not ir_scene.viewpoints:
        return []

    camera_library = _ensure_inline_collection(context.scene.collection, "X3DViewpoints")
    _apply_scene_metadata(camera_library, ir_scene)
    created_names = []

    for index, viewpoint in enumerate(ir_scene.viewpoints):
        camera_data = bpy.data.cameras.new(f"X3DViewpointCamera_{index:03d}")
        if viewpoint.field_of_view is not None:
            camera_data.angle = viewpoint.field_of_view
        camera_object = bpy.data.objects.new(
            viewpoint.description or f"X3DViewpoint_{index:03d}",
            camera_data,
        )
        camera_object["x3d_viewpoint_description"] = viewpoint.description or ""
        if viewpoint.field_of_view is not None:
            camera_object["x3d_viewpoint_fov"] = viewpoint.field_of_view
        _apply_scene_metadata(camera_object, ir_scene)
        _apply_transform(camera_object, viewpoint.transform)
        camera_library.objects.link(camera_object)
        created_names.append(camera_object.name)

        if index == 0:
            context.scene.camera = camera_object

    if ir_scene.navigation_types:
        context.scene["x3d_navigation_types"] = "|".join(ir_scene.navigation_types)

    return created_names


def populate_scene(context, ir_scene):
    """Populate Blender data from IR.

    This is a scaffold only. Import modernization will move object/material
    creation here instead of directly coupling XML parsing to Blender writes.
    """
    imported_assets: list[dict[str, object]] = []
    viewpoint_names = _populate_viewpoints(context, ir_scene)

    inline_library = _ensure_inline_collection(context.scene.collection, "X3DInlineAssets")
    _apply_scene_metadata(inline_library, ir_scene)

    for asset_index, inline_asset in enumerate(ir_scene.inline_assets):
        resolved_path = _resolve_inline_path(ir_scene.source_path, inline_asset.url)
        if inline_asset.asset_type != "gltf":
            ir_scene.diagnostics.append(f"Unsupported Inline asset type for modern importer: {inline_asset.url}")
            continue

        imported_names = import_gltf(resolved_path)
        material_names = imported_material_names(imported_names)
        imported_objects = [context.scene.objects[name] for name in imported_names if name in context.scene.objects]
        asset_collection = _ensure_inline_collection(
            inline_library,
            f"X3DInline_{asset_index:03d}_{_safe_name(os.path.basename(resolved_path))}",
        )
        _apply_scene_metadata(asset_collection, ir_scene)
        root = _create_inline_root(asset_collection, asset_index, inline_asset, resolved_path)
        _apply_scene_metadata(root, ir_scene)
        _apply_transform(root, inline_asset.transform)

        for obj in imported_objects:
            _move_object_to_collection(obj, asset_collection)
            if obj.parent is None:
                obj.parent = root
            obj["x3d_inline_source"] = inline_asset.url
            obj["x3d_inline_resolved_path"] = resolved_path
            obj["x3d_inline_asset_index"] = asset_index

        _tag_imported_materials(material_names, inline_asset, resolved_path, asset_index)

        imported_assets.append(
            {
                "url": inline_asset.url,
                "resolved_path": resolved_path,
                "root_name": root.name,
                "collection_name": asset_collection.name,
                "object_names": imported_names,
                "material_names": material_names,
            }
        )

    return {
        "imported_assets": imported_assets,
        "viewpoints": viewpoint_names,
        "navigation_types": list(ir_scene.navigation_types),
    }
