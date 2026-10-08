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
    from .ir import IRInstance, IRMeshGeometry, IRMetadata, IRScene, IRShape, IRTransform
    from .material import analyze_material
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRInstance, IRMeshGeometry, IRMetadata, IRScene, IRShape, IRTransform
    from material import analyze_material


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


def _object_transform(obj, global_matrix) -> IRTransform:
    matrix = obj.matrix_world
    if global_matrix is not None:
        matrix = global_matrix @ matrix
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
    metadata: dict | None = None,
) -> IRScene:
    """Build the scene IR used by the X3D 4.0 emitter.

    Objects are written flat with their world transform (parenting survives
    only through the resulting matrices); hierarchy emission is a later
    milestone. Non-mesh objects are counted in ``diagnostics`` and skipped.
    """

    del use_hierarchy

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

    source_keys: dict[str, str] = {}
    material_names: set[str] = set()
    geometries_by_key: dict[str, list[IRMeshGeometry]] = {}
    skipped_types: dict[str, int] = {}

    for obj in _iter_export_objects(
        scene,
        view_layer,
        use_selection=use_selection,
        use_visible=use_visible,
        use_active_collection=use_active_collection,
    ):
        if obj.type != "MESH":
            skipped_types[obj.type] = skipped_types.get(obj.type, 0) + 1
            continue

        ir_scene.object_names.append(obj.name)

        modified = bool(use_mesh_modifiers and depsgraph is not None and obj.is_modified(scene, "PREVIEW"))
        geometry_key = obj.name if modified else obj.data.name
        source_key = f"MESH:{geometry_key}"
        source_keys.setdefault(source_key, obj.name)

        geometries = geometries_by_key.get(geometry_key)
        if geometries is None:
            mesh_owner = obj.evaluated_get(depsgraph) if modified else obj
            mesh = None
            try:
                if modified:
                    mesh = mesh_owner.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
                else:
                    mesh = obj.data
                if use_triangulate and hasattr(mesh, "calc_loop_triangles"):
                    mesh.calc_loop_triangles()
                geometries = extract_mesh_geometries(
                    mesh,
                    name=geometry_key,
                    material_slots=obj.material_slots,
                    use_triangulate=use_triangulate,
                    use_normals=use_normals,
                )
            finally:
                if modified and mesh is not None:
                    mesh_owner.to_mesh_clear()
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

        if not shapes:
            ir_scene.diagnostics.append(f"Object {obj.name!r} has no exportable faces and was skipped.")
            continue

        ir_scene.instances.append(
            IRInstance(
                source_key=source_key,
                object_name=obj.name,
                object_type=obj.type,
                geometry_name=shapes[0].geometry_name,
                material_name=shapes[0].material_name,
                transform=_object_transform(obj, global_matrix),
                shapes=shapes,
            )
        )

    for object_type, count in sorted(skipped_types.items()):
        ir_scene.diagnostics.append(
            f"Skipped {count} {object_type} object(s): not yet supported by the X3D 4.0 path."
        )

    if not ir_scene.object_names:
        ir_scene.diagnostics.append("No exportable objects matched the current filters.")
    else:
        shared_sources = {
            source_key: owner_name
            for source_key, owner_name in source_keys.items()
            if sum(1 for instance in ir_scene.instances if instance.source_key == source_key) > 1
        }
        if shared_sources:
            ir_scene.diagnostics.append(
                "Reused geometry (DEF/USE): "
                + ", ".join(f"{source_key}->{owner_name}" for source_key, owner_name in sorted(shared_sources.items()))
            )

    return ir_scene
