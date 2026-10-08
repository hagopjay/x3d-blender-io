# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender scene -> IR extraction for the X3D 4.0 export path.

Everything that touches ``bpy`` data on the export side lives here. The
emitter (``emit_x3d40``) never sees Blender objects.
"""

from __future__ import annotations

import math

try:
    from .ir import IRAnimation, IRInstance, IRLight, IRMeshGeometry, IRMetadata, IRScene, IRShape, IRTransform, IRViewpoint
    from .material import analyze_material
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRAnimation, IRInstance, IRLight, IRMeshGeometry, IRMetadata, IRScene, IRShape, IRTransform, IRViewpoint
    from material import analyze_material


MESH_LIKE_TYPES = {"MESH", "CURVE", "SURFACE", "FONT"}


_ROUND = 6


def _uv_values(mesh):
    """Return a per-loop UV accessor for the active UV layer, or None."""
    uv_layers = getattr(mesh, "uv_layers", None)
    layer = uv_layers.active if uv_layers else None
    if layer is None:
        return None
    uv_attr = getattr(layer, "uv", None)
    if uv_attr is not None and len(uv_attr) == len(mesh.loops):
        return lambda loop_index: tuple(uv_attr[loop_index].vector[:2])
    data = getattr(layer, "data", None)
    if data is not None:
        return lambda loop_index: tuple(data[loop_index].uv[:2])
    return None


def _corner_normals(mesh):
    """Return a per-loop normal accessor (Blender 4.1+ ``corner_normals``)."""
    corner_normals = getattr(mesh, "corner_normals", None)
    if corner_normals is not None and len(corner_normals) == len(mesh.loops):
        return lambda loop_index: tuple(corner_normals[loop_index].vector[:3])
    loops = mesh.loops
    return lambda loop_index: tuple(loops[loop_index].normal[:3])


def _color_values(mesh):
    """Return (accessor, domain) for the active color attribute, or (None, None)."""
    attributes = getattr(mesh, "color_attributes", None)
    if not attributes:
        return None, None
    attr = getattr(attributes, "active_color", None)
    if attr is None:
        return None, None
    data = attr.data
    domain = attr.domain  # 'POINT' or 'CORNER'

    def accessor(index):
        color = data[index].color
        alpha = float(color[3]) if len(color) > 3 else 1.0
        return (float(color[0]), float(color[1]), float(color[2]), alpha)

    return accessor, domain


def extract_mesh_geometries(
    mesh,
    *,
    name: str,
    material_slots=None,
    use_triangulate: bool = False,
    use_normals: bool = False,
) -> list[IRMeshGeometry]:
    """Split a Blender mesh into one IRMeshGeometry per used material slot.

    Vertices are split on (vertex, uv, color, normal) so that all X3D arrays
    share ``coordIndex``. Normals are only exported when ``use_normals`` is
    set; otherwise ``creaseAngle`` carries the smooth/flat intent.
    """

    polygons = getattr(mesh, "polygons", None)
    vertices = getattr(mesh, "vertices", None)
    loops = getattr(mesh, "loops", None)
    if not polygons or vertices is None or loops is None:
        return []

    uv_at = _uv_values(mesh)
    color_at, color_domain = _color_values(mesh)
    normal_at = _corner_normals(mesh) if use_normals else None

    tri_by_polygon: dict[int, list] = {}
    if use_triangulate:
        for tri in mesh.loop_triangles:
            tri_by_polygon.setdefault(tri.polygon_index, []).append(tri)

    def material_for_slot(slot_index):
        if not material_slots or slot_index >= len(material_slots):
            return None
        return getattr(material_slots[slot_index], "material", None)

    groups: dict[int, list] = {}
    for polygon in polygons:
        if len(polygon.vertices) < 3:
            continue
        groups.setdefault(int(polygon.material_index), []).append(polygon)

    geometries: list[IRMeshGeometry] = []
    multi = len(groups) > 1
    for slot_index in sorted(groups):
        group = groups[slot_index]
        vertex_map: dict[tuple, int] = {}
        coord: list[tuple[float, float, float]] = []
        normal: list[tuple[float, float, float]] = []
        tex_coord: list[tuple[float, float]] = []
        color: list[tuple[float, float, float, float]] = []
        coord_index: list[int] = []
        any_smooth = False

        def emit_vertex(vertex_index, loop_index):
            key = [vertex_index]
            uv = uv_at(loop_index) if uv_at else None
            col = None
            if color_at:
                col = color_at(loop_index if color_domain == "CORNER" else vertex_index)
            nrm = normal_at(loop_index) if normal_at else None
            if uv is not None:
                key.append(tuple(round(value, _ROUND) for value in uv))
            if col is not None:
                key.append(tuple(round(value, _ROUND) for value in col))
            if nrm is not None:
                key.append(tuple(round(value, _ROUND) for value in nrm))
            key = tuple(key)
            index = vertex_map.get(key)
            if index is None:
                index = len(coord)
                vertex_map[key] = index
                coord.append(tuple(float(value) for value in vertices[vertex_index].co[:3]))
                if uv is not None:
                    tex_coord.append((float(uv[0]), float(uv[1])))
                if col is not None:
                    color.append(col)
                if nrm is not None:
                    normal.append(tuple(float(value) for value in nrm))
            return index

        for polygon in group:
            if getattr(polygon, "use_smooth", False):
                any_smooth = True
            if use_triangulate:
                for tri in tri_by_polygon.get(polygon.index, ()):
                    for loop_index, vertex_index in zip(tri.loops, tri.vertices):
                        coord_index.append(emit_vertex(vertex_index, loop_index))
                    coord_index.append(-1)
            else:
                for loop_index in polygon.loop_indices:
                    coord_index.append(emit_vertex(loops[loop_index].vertex_index, loop_index))
                coord_index.append(-1)

        if not coord_index:
            continue

        material = material_for_slot(slot_index)
        solid = bool(getattr(material, "use_backface_culling", False)) if material else False
        crease_angle = None
        if normal_at is None:
            crease_angle = math.pi if any_smooth else 0.0

        geometries.append(
            IRMeshGeometry(
                name=f"{name}_m{slot_index}" if multi else name,
                coord=coord,
                coord_index=coord_index,
                solid=solid,
                crease_angle=crease_angle,
                normal=normal,
                tex_coord=tex_coord,
                color=color,
                material_slot=slot_index,
                source_mesh=name,
            )
        )
    return geometries


def _matrix_transform(matrix) -> IRTransform:
    loc, rot, scale = matrix.decompose()
    axis, angle = rot.to_axis_angle()
    if abs(angle) < 1e-9:
        axis = (0.0, 0.0, 1.0)
        angle = 0.0
    return IRTransform(
        translation=tuple(float(value) for value in loc[:3]),
        rotation_axis_angle=(float(axis[0]), float(axis[1]), float(axis[2]), float(angle)),
        scale=tuple(float(value) for value in scale[:3]),
    )


def _iter_export_objects(scene, view_layer, *, use_selection, use_visible, use_active_collection):
    if use_active_collection and view_layer is not None:
        objects = view_layer.active_layer_collection.collection.all_objects
    else:
        objects = scene.objects
    for obj in objects:
        if use_selection and not obj.select_get():
            continue
        if use_visible and not obj.visible_get():
            continue
        yield obj


def _direction_neg_z(matrix):
    vector = matrix.to_3x3() @ type(matrix.to_translation())((0.0, 0.0, -1.0))
    vector.normalize()
    return (float(vector[0]), float(vector[1]), float(vector[2]))


def _extract_light(obj, local_matrix) -> IRLight:
    """Mirror the legacy exporter's light mapping; values are local to the object's Transform."""
    data = obj.data
    light_type = {"POINT": "POINT", "SPOT": "SPOT", "SUN": "DIRECTIONAL"}.get(data.type, "DIRECTIONAL")
    light = IRLight(
        name=obj.name,
        light_type=light_type,
        color=tuple(max(0.0, min(1.0, float(channel))) for channel in data.color[:3]),
        intensity=min(float(data.energy) / 1.75, 1.0) if data.type != "SUN" else min(float(data.energy), 1.0),
        location=tuple(float(value) for value in local_matrix.to_translation()[:3]),
        direction=_direction_neg_z(local_matrix),
    )
    cutoff = float(getattr(data, "cutoff_distance", 0.0) or 0.0)
    if light_type == "POINT":
        light.radius = cutoff if cutoff > 0.0 else 100.0
    elif light_type == "SPOT":
        light.beam_width = float(data.spot_size) * 0.37
        light.cut_off_angle = min(light.beam_width * 1.3, math.pi / 2.0)
        light.radius = (cutoff * math.cos(light.beam_width)) if cutoff > 0.0 else 100.0
    return light


def _extract_viewpoint(obj, local_matrix) -> IRViewpoint:
    return IRViewpoint(
        name=obj.name,
        description=obj.name,
        transform=_matrix_transform(local_matrix),
        field_of_view=float(obj.data.angle) if obj.data.type == "PERSP" else None,
    )


def _sample_animation(scene, objects_by_name, *, use_hierarchy, global_matrix, frame_step=1):
    """Sample every exported object's local transform per frame.

    Returns (animations, cycle_interval). Objects whose transform never changes
    produce no animation.
    """
    frame_start, frame_end = scene.frame_start, scene.frame_end
    if frame_end <= frame_start:
        return [], None
    fps = scene.render.fps / scene.render.fps_base
    current = scene.frame_current
    frames = list(range(frame_start, frame_end + 1, max(1, int(frame_step))))
    if frames[-1] != frame_end:
        frames.append(frame_end)
    samples: dict[str, list] = {name: [] for name in objects_by_name}
    try:
        for frame in frames:
            scene.frame_set(frame)
            for name, (obj, parent) in objects_by_name.items():
                matrix = obj.matrix_world
                if use_hierarchy and parent is not None:
                    matrix = parent.matrix_world.inverted() @ matrix
                elif global_matrix is not None:
                    matrix = global_matrix @ matrix
                samples[name].append(_matrix_transform(matrix))
    finally:
        scene.frame_set(current)

    span = float(frame_end - frame_start)
    keys = [(frame - frame_start) / span for frame in frames]
    animations = []
    for name, transforms in samples.items():
        first = transforms[0]
        moving = any(t.translation != first.translation for t in transforms)
        rotating = any(t.rotation_axis_angle != first.rotation_axis_angle for t in transforms)
        scaling = any(t.scale != first.scale for t in transforms)
        if not (moving or rotating or scaling):
            continue
        animations.append(
            IRAnimation(
                target=name,
                keys=keys,
                translations=[t.translation for t in transforms] if moving else [],
                rotations=[t.rotation_axis_angle for t in transforms] if rotating else [],
                scales=[t.scale for t in transforms] if scaling else [],
            )
        )
    return animations, span / fps


def extract_scene(
    scene,
    *,
    view_layer=None,
    depsgraph=None,
    global_matrix=None,
    use_selection: bool = True,
    use_active_collection: bool = False,
    use_visible: bool = False,
    use_hierarchy: bool = True,
    use_mesh_modifiers: bool = False,
    use_triangulate: bool = False,
    use_normals: bool = False,
    use_animation: bool = False,
    animation_step: int = 1,
    metadata: dict | None = None,
) -> IRScene:
    """Build the scene IR used by the X3D 4.0 emitter.

    With ``use_hierarchy`` every exported object becomes a Transform whose
    matrix is relative to its exported parent; otherwise objects are written
    flat with world matrices. Meshes, curves, surfaces and text become
    IndexedFaceSets; lights and cameras become X3D lights and Viewpoints.
    """

    metadata = metadata or {}
    meta = IRMetadata(
        creator=metadata.get("creator"),
        title=metadata.get("title"),
        description=metadata.get("description"),
        keywords=metadata.get("keywords"),
        reference=metadata.get("reference"),
        license=metadata.get("license"),
        filename=metadata.get("filename"),
    )

    ir_scene = IRScene(name=scene.name, metadata=meta)
    world = getattr(scene, "world", None)
    if world is not None and getattr(world, "color", None) is not None:
        ir_scene.background_color = tuple(max(0.0, min(1.0, float(channel))) for channel in world.color[:3])

    exported = list(
        _iter_export_objects(
            scene,
            view_layer,
            use_selection=use_selection,
            use_visible=use_visible,
            use_active_collection=use_active_collection,
        )
    )
    exported_names = {obj.name for obj in exported}

    def exported_parent(obj):
        parent = obj.parent
        while parent is not None and parent.name not in exported_names:
            parent = parent.parent
        return parent

    source_keys: dict[str, str] = {}
    material_names: set[str] = set()
    geometries_by_key: dict[str, list[IRMeshGeometry]] = {}
    skipped_types: dict[str, int] = {}
    objects_by_name: dict[str, tuple] = {}

    def mesh_shapes(obj):
        """Return the IRShape list for a mesh-like object, extracting geometry on first sight."""
        needs_eval = obj.type != "MESH" or bool(
            use_mesh_modifiers and depsgraph is not None and obj.is_modified(scene, "PREVIEW")
        )
        geometry_key = obj.name if needs_eval else obj.data.name
        source_key = f"{obj.type}:{geometry_key}"
        source_keys.setdefault(source_key, obj.name)

        geometries = geometries_by_key.get(geometry_key)
        if geometries is None:
            mesh = None
            owner = obj
            try:
                if needs_eval:
                    owner = obj.evaluated_get(depsgraph) if depsgraph is not None else obj
                    try:
                        mesh = owner.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
                    except TypeError:
                        mesh = owner.to_mesh()
                else:
                    mesh = obj.data
                if mesh is not None:
                    if use_triangulate and hasattr(mesh, "calc_loop_triangles"):
                        mesh.calc_loop_triangles()
                    geometries = extract_mesh_geometries(
                        mesh,
                        name=geometry_key,
                        material_slots=obj.material_slots,
                        use_triangulate=use_triangulate,
                        use_normals=use_normals,
                    )
                else:
                    geometries = []
            finally:
                if needs_eval and mesh is not None:
                    owner.to_mesh_clear()
            geometries_by_key[geometry_key] = geometries
            ir_scene.geometries.extend(geometries)

        shapes: list[IRShape] = []
        slots = obj.material_slots
        for geometry in geometries:
            material = None
            if slots and geometry.material_slot < len(slots):
                material = slots[geometry.material_slot].material
            material_name = material.name if material else None
            if material and material.name not in material_names:
                analyzed = analyze_material(material)
                if analyzed:
                    ir_scene.materials.append(analyzed)
                    material_names.add(material.name)
            shapes.append(IRShape(geometry_name=geometry.name, material_name=material_name))
        return source_key, shapes

    def build_instance(obj, parent):
        if use_hierarchy and parent is not None:
            local_matrix = parent.matrix_world.inverted() @ obj.matrix_world
        else:
            local_matrix = (global_matrix @ obj.matrix_world) if global_matrix is not None else obj.matrix_world

        instance = IRInstance(
            source_key=f"{obj.type}:{obj.name}",
            object_name=obj.name,
            object_type=obj.type,
            transform=_matrix_transform(local_matrix),
        )
        objects_by_name[obj.name] = (obj, parent if use_hierarchy else None)

        if obj.type in MESH_LIKE_TYPES:
            source_key, shapes = mesh_shapes(obj)
            instance.source_key = source_key
            instance.shapes = shapes
            if shapes:
                instance.geometry_name = shapes[0].geometry_name
                instance.material_name = shapes[0].material_name
            else:
                ir_scene.diagnostics.append(f"Object {obj.name!r} has no exportable faces.")
            ir_scene.object_names.append(obj.name)
        elif obj.type == "LIGHT":
            # Light values are local to the object's Transform, which carries the matrix.
            instance.light = _extract_light(obj, local_matrix.__class__())
            ir_scene.object_names.append(obj.name)
        elif obj.type == "CAMERA":
            instance.viewpoint = _extract_viewpoint(obj, local_matrix.__class__())
            ir_scene.object_names.append(obj.name)
        elif obj.type == "EMPTY":
            ir_scene.object_names.append(obj.name)
        else:
            skipped_types[obj.type] = skipped_types.get(obj.type, 0) + 1
            if not use_hierarchy:
                return None

        if use_hierarchy:
            for child in exported:
                if exported_parent(child) is obj:
                    child_instance = build_instance(child, obj)
                    if child_instance is not None:
                        instance.children.append(child_instance)
        return instance

    if use_hierarchy:
        roots = [obj for obj in exported if exported_parent(obj) is None]
        for obj in roots:
            instance = build_instance(obj, None)
            if instance is not None:
                ir_scene.instances.append(instance)
    else:
        for obj in exported:
            instance = build_instance(obj, None)
            if instance is not None:
                ir_scene.instances.append(instance)

    if use_animation and objects_by_name:
        ir_scene.animations, ir_scene.cycle_interval = _sample_animation(
            scene,
            objects_by_name,
            use_hierarchy=use_hierarchy,
            global_matrix=global_matrix,
            frame_step=animation_step,
        )

    for object_type, count in sorted(skipped_types.items()):
        ir_scene.diagnostics.append(
            f"Skipped {count} {object_type} object(s): not yet supported by the X3D 4.0 path."
        )

    if not ir_scene.object_names:
        ir_scene.diagnostics.append("No exportable objects matched the current filters.")
    else:
        instances = list(ir_scene.iter_instances())
        shared_sources = {
            source_key: owner_name
            for source_key, owner_name in source_keys.items()
            if sum(1 for instance in instances if instance.source_key == source_key) > 1
        }
        if shared_sources:
            ir_scene.diagnostics.append(
                "Reused geometry (DEF/USE): "
                + ", ".join(f"{source_key}->{owner_name}" for source_key, owner_name in sorted(shared_sources.items()))
            )

    return ir_scene
