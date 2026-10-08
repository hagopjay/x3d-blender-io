# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable

import bpy

try:
    from .extract import extract_scene
except ImportError:  # pragma: no cover - standalone test fallback
    from extract import extract_scene


@dataclass(slots=True)
class ExportSettings:
    filepath: str
    use_selection: bool = True
    use_active_collection: bool = False
    use_visible: bool = False
    use_mesh_modifiers: bool = False
    use_triangulate: bool = False
    use_normals: bool = False
    use_compress: bool = False
    use_hierarchy: bool = True
    use_h3d: bool = False
    global_matrix: object | None = None
    path_mode: str = "COPY"
    name_decorations: bool = True
    batch_mode: str = "OFF"
    use_batch_own_dir: bool = False
    meta_creator: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    meta_keywords: str | None = None
    meta_reference: str | None = None
    meta_license: str | None = None
    export_target: str = "AUTO"


def _scene_metadata(settings: ExportSettings) -> dict[str, str | None]:
    return {
        "creator": settings.meta_creator,
        "title": settings.meta_title,
        "description": settings.meta_description,
        "keywords": settings.meta_keywords,
        "reference": settings.meta_reference,
        "license": settings.meta_license,
    }


def save(context, settings: ExportSettings, writer: Callable[..., None]):
    """Shared orchestration for export workflows.

    The writer callback remains responsible for actual file emission while this
    module centralizes path planning and scene-to-IR extraction.
    """

    filepath = bpy.path.ensure_ext(settings.filepath, ".x3dz" if settings.use_compress else ".x3d")

    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode="OBJECT")

    def get_export_path(local_base_dir, name):
        export_dir = os.path.join(local_base_dir, bpy.path.clean_name(name)) if settings.use_batch_own_dir else local_base_dir
        if settings.use_batch_own_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir)
        suffix = ".x3dz" if settings.use_compress else ".x3d"
        return os.path.join(export_dir, f"{bpy.path.clean_name(name)}{suffix}")

    def run_writer(export_file, depsgraph, local_scene, view_layer):
        ir_scene = extract_scene(
            local_scene,
            use_selection=settings.use_selection,
            use_active_collection=settings.use_active_collection,
            use_visible=settings.use_visible,
            use_hierarchy=settings.use_hierarchy,
            metadata=_scene_metadata(settings),
        )
        writer(
            export_file=export_file,
            depsgraph=depsgraph,
            scene=local_scene,
            view_layer=view_layer,
            ir_scene=ir_scene,
            settings=settings,
        )

    base_dir = os.path.dirname(filepath)
    prefix = os.path.basename(filepath).replace(".x3d", "").replace(".x3dz", "")

    if settings.batch_mode == "OFF":
        run_writer(filepath, context.evaluated_depsgraph_get(), context.scene, context.view_layer)
    elif settings.batch_mode == "COLLECTION":
        original_collection = context.view_layer.active_layer_collection
        try:
            for collection in bpy.data.collections:
                if not collection.objects:
                    continue
                child = context.view_layer.layer_collection.children.get(collection.name)
                if child is None:
                    continue
                context.view_layer.active_layer_collection = child
                export_path = get_export_path(base_dir, f"{prefix}_{collection.name}")
                run_writer(export_path, context.evaluated_depsgraph_get(), context.scene, context.view_layer)
        finally:
            context.view_layer.active_layer_collection = original_collection
    elif settings.batch_mode == "SCENE":
        for scene in bpy.data.scenes:
            export_path = get_export_path(base_dir, f"{prefix}_{scene.name}")
            run_writer(export_path, scene.view_layers[0].depsgraph, scene, scene.view_layers[0])
    elif settings.batch_mode == "OBJECT":
        for obj in bpy.data.objects:
            if settings.use_visible and not obj.visible_get():
                continue
            if settings.use_selection and not obj.select_get():
                continue
            export_path = get_export_path(base_dir, f"{prefix}_{obj.name}")
            temp_scene = bpy.data.scenes.new(name="X3D_TempExportScene")
            try:
                temp_scene.collection.objects.link(obj)
                temp_scene.view_layers[0].update()
                run_writer(export_path, temp_scene.view_layers[0].depsgraph, temp_scene, temp_scene.view_layers[0])
            finally:
                bpy.data.scenes.remove(temp_scene)
    elif settings.batch_mode == "OBJECT_HIERARCHY":
        exported_objects = set()
        for obj in bpy.data.objects:
            if settings.use_visible and not obj.visible_get():
                continue
            if settings.use_selection and not obj.select_get():
                continue
            if obj in exported_objects:
                continue
            top_level_parent = obj
            while top_level_parent.parent:
                top_level_parent = top_level_parent.parent
            hierarchy_objects = {top_level_parent} | set(top_level_parent.children_recursive)
            exported_objects.update(hierarchy_objects)
            export_path = get_export_path(base_dir, f"{prefix}_{top_level_parent.name}")
            temp_scene = bpy.data.scenes.new(name="X3D_TempExportScene")
            try:
                for hierarchy_obj in hierarchy_objects:
                    temp_scene.collection.objects.link(hierarchy_obj)
                temp_scene.view_layers[0].update()
                run_writer(export_path, temp_scene.view_layers[0].depsgraph, temp_scene, temp_scene.view_layers[0])
            finally:
                bpy.data.scenes.remove(temp_scene)
    else:
        run_writer(filepath, context.evaluated_depsgraph_get(), context.scene, context.view_layer)

    return {"FINISHED"}
