# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

try:
    from .ir import IRInstance, IRMeshGeometry, IRMetadata, IRScene, IRTransform
    from .material import analyze_material
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRInstance, IRMeshGeometry, IRMetadata, IRScene, IRTransform
    from material import analyze_material


def _geometry_hint_for_object(obj) -> str:
    if obj.type == "LIGHT":
        return "Sphere"
    if obj.type == "CAMERA":
        return "Cone"
    if obj.type == "MESH":
        data_name = getattr(obj.data, "name", "").lower()
        obj_name = obj.name.lower()
        for hint_name, primitive in (
            ("cube", "Box"),
            ("box", "Box"),
            ("sphere", "Sphere"),
            ("uvsphere", "Sphere"),
            ("icosphere", "Sphere"),
            ("cylinder", "Cylinder"),
            ("cone", "Cone"),
            ("plane", "Rectangle2D"),
            ("circle", "Circle2D"),
        ):
            if hint_name in data_name or hint_name in obj_name:
                return primitive
        return "Box"
    return "Sphere"


def _extract_mesh_geometry(obj) -> IRMeshGeometry | None:
    if obj.type != "MESH":
        return None

    mesh = getattr(obj, "data", None)
    if mesh is None:
        return None

    polygons = getattr(mesh, "polygons", None)
    vertices = getattr(mesh, "vertices", None)
    if polygons is None or vertices is None:
        return None

    coord = [tuple(vertex.co[:]) for vertex in vertices]
    coord_index: list[int] = []
    for polygon in polygons:
        vertex_indices = list(getattr(polygon, "vertices", ()))
        if len(vertex_indices) < 3:
            continue
        coord_index.extend(vertex_indices)
        coord_index.append(-1)

    if not coord or not coord_index:
        return None

    return IRMeshGeometry(
        name=getattr(mesh, "name", obj.name),
        coord=coord,
        coord_index=coord_index,
        solid=not bool(getattr(mesh, "show_double_sided", False)),
        crease_angle=getattr(mesh, "auto_smooth_angle", None) if getattr(mesh, "use_auto_smooth", False) else None,
    )


def extract_scene(
    scene,
    *,
    use_selection: bool = True,
    use_active_collection: bool = False,
    use_visible: bool = False,
    use_hierarchy: bool = True,
    metadata: dict | None = None,
) -> IRScene:
    """Build a minimal scene IR for orchestration, diagnostics, and profiling.

    This deliberately starts small. The legacy XML emitter still performs the
    real export work until modern emitters take over. The IR is used now to
    centralize scene filtering decisions and to give new modules a stable
    contract to build on.
    """

    del use_active_collection, use_hierarchy

    meta = IRMetadata(
        creator=metadata.get("creator") if metadata else None,
        title=metadata.get("title") if metadata else None,
        description=metadata.get("description") if metadata else None,
        keywords=metadata.get("keywords") if metadata else None,
        reference=metadata.get("reference") if metadata else None,
        license=metadata.get("license") if metadata else None,
    )

    ir_scene = IRScene(name=scene.name, metadata=meta)

    source_keys: dict[str, str] = {}
    material_names: set[str] = set()
    geometry_names: set[str] = set()

    for obj in scene.objects:
        if use_selection and not obj.select_get():
            continue
        if use_visible and not obj.visible_get():
            continue

        ir_scene.object_names.append(obj.name)

        data_name = getattr(obj.data, "name", None)
        source_key = f"{obj.type}:{data_name or obj.name}"
        source_keys.setdefault(source_key, obj.name)
        geometry = _extract_mesh_geometry(obj)
        geometry_name = None
        if geometry:
            geometry_name = geometry.name
            if geometry_name not in geometry_names:
                ir_scene.geometries.append(geometry)
                geometry_names.add(geometry_name)

        loc, rot, scale = obj.matrix_world.decompose()
        axis, angle = rot.to_axis_angle()
        primary_material_name = None
        if getattr(obj, "material_slots", None):
            for material_slot in obj.material_slots:
                material = getattr(material_slot, "material", None)
                if material:
                    primary_material_name = material.name
                    break

        ir_scene.instances.append(
            IRInstance(
                source_key=source_key,
                object_name=obj.name,
                object_type=obj.type,
                geometry_hint=_geometry_hint_for_object(obj),
                geometry_name=geometry_name,
                material_name=primary_material_name,
                transform=IRTransform(
                    translation=tuple(loc[:]),
                    rotation_axis_angle=(*axis[:], angle),
                    scale=tuple(scale[:]),
                ),
            )
        )

        for material_slot in getattr(obj, "material_slots", []):
            material = getattr(material_slot, "material", None)
            if not material or material.name in material_names:
                continue
            analyzed = analyze_material(material)
            if analyzed:
                ir_scene.materials.append(analyzed)
                material_names.add(material.name)

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
                "Detected reusable instance sources: "
                + ", ".join(f"{source_key}->{owner_name}" for source_key, owner_name in sorted(shared_sources.items()))
            )
        if ir_scene.materials:
            ir_scene.diagnostics.append(
                "Analyzed materials: " + ", ".join(sorted(material.name for material in ir_scene.materials))
            )
        if ir_scene.geometries:
            ir_scene.diagnostics.append(
                "Extracted geometries: " + ", ".join(sorted(geometry.name for geometry in ir_scene.geometries))
            )

    return ir_scene
