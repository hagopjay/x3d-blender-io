# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable

import bpy
from bpy_extras.io_utils import path_reference, path_reference_copy

try:
    from .extract import extract_scene
except ImportError:  # pragma: no cover - standalone test fallback
    from extract import extract_scene


def resolve_texture_urls(ir_scene, export_file: str, path_mode: str, copy_set: set) -> None:
    """Fill ``IRTextureRef.url`` for every texture according to the path mode.

    Mirrors the legacy exporter: COPY places files next to the X3D file,
    RELATIVE/ABSOLUTE/STRIP/MATCH/RELATIVE_ALL follow ``path_reference``.
    Packed images with no file on disk are written next to the X3D file.
    """

    base_dst = os.path.dirname(os.path.abspath(export_file))
    base_src = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else base_dst
    seen: dict[str, str] = {}
    for texture_ref in ir_scene.iter_texture_refs():
        image = bpy.data.images.get(texture_ref.image_name) if texture_ref.image_name else None
        if image is None:
            continue
        if image.name in seen:
            texture_ref.url = seen[image.name]
            continue
        filepath = bpy.path.abspath(image.filepath_raw or image.filepath, library=image.library)
        has_file = bool(filepath) and os.path.exists(filepath)
        if not has_file:
            if path_mode == "STRIP" or image.packed_file is None and not image.has_data:
                url = os.path.basename(filepath) or image.name
                texture_ref.url = url
                seen[image.name] = url
                ir_scene.diagnostics.append(f"Texture {image.name!r} has no file on disk; wrote bare name {url!r}.")
                continue
            ext = {"PNG": ".png", "JPEG": ".jpg", "BMP": ".bmp", "TARGA": ".tga", "TIFF": ".tif"}.get(
                image.file_format, ".png"
            )
            target = os.path.join(base_dst, bpy.path.clean_name(os.path.splitext(image.name)[0]) + ext)
            try:
                image.save(filepath=target)
            except TypeError:  # older API without the filepath keyword
                previous = image.filepath_raw
                image.filepath_raw = target
                try:
                    image.save()
                finally:
                    image.filepath_raw = previous
            except RuntimeError as exc:
                ir_scene.diagnostics.append(f"Could not write packed texture {image.name!r}: {exc}")
                continue
            filepath = target
        url = path_reference(
            filepath,
            base_src,
            base_dst,
            path_mode,
            "",
            copy_set,
            image.library,
        )
        url = url.replace("\\", "/")
        texture_ref.url = url
        seen[image.name] = url


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
    x3d_version: str = "X3D33"
    use_animation: bool = False
    animation_step: int = 1

    @property
    def use_modern_path(self) -> bool:
        target = (self.export_target or "AUTO").upper()
        if target in {"MODERN", "X3D40", "MODERN_SCAFFOLD"}:
            return True
        if target == "AUTO":
            return self.x3d_version.upper() in {"X3D40", "4.0"}
        return False


def _scene_metadata(settings: ExportSettings, export_file: str) -> dict[str, str | None]:
    return {
        "filename": os.path.basename(export_file),
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
        ir_scene = None
        copy_set = set()
        if settings.use_modern_path:
            ir_scene = extract_scene(
                local_scene,
                view_layer=view_layer,
                depsgraph=depsgraph,
                global_matrix=settings.global_matrix,
                use_selection=settings.use_selection,
                use_active_collection=settings.use_active_collection,
                use_visible=settings.use_visible,
                use_hierarchy=settings.use_hierarchy,
                use_mesh_modifiers=settings.use_mesh_modifiers,
                use_triangulate=settings.use_triangulate,
                use_normals=settings.use_normals,
                use_animation=settings.use_animation,
                animation_step=settings.animation_step,
                metadata=_scene_metadata(settings, export_file),
            )
            resolve_texture_urls(ir_scene, export_file, settings.path_mode, copy_set)
        writer(
            export_file=export_file,
            depsgraph=depsgraph,
            scene=local_scene,
            view_layer=view_layer,
            ir_scene=ir_scene,
            settings=settings,
        )
        if copy_set:
            path_reference_copy(copy_set)

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
