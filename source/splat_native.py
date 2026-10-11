# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender's native Gaussian-splat point clouds <-> IRGaussianSplats.

Blender 5.3 stores splats as a PointCloud whose ``type`` is ``'GAUSSIAN_SPLAT'``
(commit 6e18d7a, "GSplat: Add type field to the PointCloud data-block"). Its
PLY, SPZ, glTF (KHR_gaussian_splatting) and USD importers all write the same
point attributes, and Blender 5.3 has no splat exporter of its own:

========================  ============================================================
attribute                 meaning
========================  ============================================================
``position``              splat centre (float3)
``scale``                 linear scale (float3; the PLY importer has already applied exp)
``rotation``              quaternion, Blender order (w, x, y, z)
``radiance:base``         float4: SH degree-0 coefficient (xyz) and opacity 0..1 (w);
                          stored as a FLOAT_COLOR before Blender 5.2, which lacks FLOAT4
``radiance:sh_{i}``       float3 SH coefficients of degrees 1..3, ``i = degree**2 - 1 + coef``
========================  ============================================================

The same layout is used on Blender 4.5-5.2, which have PointClouds but no
``type`` field; there the object simply renders as plain points.
"""

from __future__ import annotations

try:
    from .ir import IRGaussianSplats
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRGaussianSplats

GAUSSIAN_SPLAT_TYPE = "GAUSSIAN_SPLAT"
POSITION_ATTR = "position"
SCALE_ATTR = "scale"
ROTATION_ATTR = "rotation"
RADIANCE_BASE_ATTR = "radiance:base"
RADIANCE_SH_ATTR = "radiance:sh_{index}"
SPLAT_PROPERTY = "x3d_gaussian_splats"
SPLAT_COLOR_SPACE_PROPERTY = "x3d_splat_color_space"
MAX_SH_DEGREE = 3


def sh_index(degree: int, coef: int) -> int:
    """Flattened ``radiance:sh_{i}`` index of an SH coefficient of degree >= 1."""
    if degree < 1 or not 0 <= coef < 2 * degree + 1:
        raise ValueError(f"no radiance:sh_ index for degree {degree} coefficient {coef}")
    return degree * degree - 1 + coef


def sh_degree_coef(index: int) -> tuple[int, int]:
    """Inverse of :func:`sh_index`."""
    if index < 0:
        raise ValueError(index)
    degree = 1
    while index >= (degree + 1) * (degree + 1) - 1:
        degree += 1
    return degree, index - (degree * degree - 1)


def pointcloud_type_supported() -> bool:
    """True when this Blender has the PointCloud ``type`` field with a Gaussian-splat item (5.3+)."""
    import bpy

    prop = bpy.types.PointCloud.bl_rna.properties.get("type")
    return prop is not None and GAUSSIAN_SPLAT_TYPE in {item.identifier for item in prop.enum_items}


def pointcloud_buildable() -> bool:
    """True when Python can size a new PointCloud (``PointCloud.resize``; absent in Blender 4.5)."""
    import bpy

    return "resize" in bpy.types.PointCloud.bl_rna.functions


def is_native_splat_object(obj) -> bool:
    """A PointCloud object holding splats: typed GAUSSIAN_SPLAT, or carrying the splat attributes."""
    if getattr(obj, "type", None) != "POINTCLOUD":
        return False
    data = getattr(obj, "data", None)
    if data is None:
        return False
    if getattr(data, "type", None) == GAUSSIAN_SPLAT_TYPE:
        return True
    names = set(data.attributes.keys())
    return {SCALE_ATTR, ROTATION_ATTR, RADIANCE_BASE_ATTR} <= names


def _flat(attr, key, width, count):
    values = [0.0] * (width * count)
    attr.data.foreach_get(key, values)
    return [tuple(values[i:i + width]) for i in range(0, width * count, width)]


def _point_attr(pointcloud, name, data_types):
    attr = pointcloud.attributes.get(name)
    if attr is None or attr.domain != "POINT" or attr.data_type not in data_types:
        return None
    return attr


def extract_native_splats(pointcloud, *, name: str) -> IRGaussianSplats:
    """Read a native splat PointCloud into IRGaussianSplats (X3D order: quaternions x y z w)."""
    splats = IRGaussianSplats(name=name, color_space=str(pointcloud.get(SPLAT_COLOR_SPACE_PROPERTY, "SRGB_REC709_DISPLAY")))
    count = len(pointcloud.points)
    position = _point_attr(pointcloud, POSITION_ATTR, {"FLOAT_VECTOR"})
    splats.positions = _flat(position, "vector", 3, count) if position is not None else [(0.0, 0.0, 0.0)] * count
    scale = _point_attr(pointcloud, SCALE_ATTR, {"FLOAT_VECTOR"})
    splats.scales = _flat(scale, "vector", 3, count) if scale is not None else [(0.01, 0.01, 0.01)] * count
    rotation = _point_attr(pointcloud, ROTATION_ATTR, {"QUATERNION"})
    if rotation is not None:
        splats.orientations = [(x, y, z, w) for (w, x, y, z) in _flat(rotation, "value", 4, count)]
    else:
        splats.orientations = [(0.0, 0.0, 0.0, 1.0)] * count
    base = _point_attr(pointcloud, RADIANCE_BASE_ATTR, {"FLOAT4", "FLOAT_COLOR"})
    if base is not None:
        rows = _flat(base, "vector" if base.data_type == "FLOAT4" else "color", 4, count)
        splats.sh[(0, 0)] = [row[:3] for row in rows]
        splats.opacities = [max(0.0, min(1.0, row[3])) for row in rows]
    else:
        splats.opacities = [1.0] * count
    for degree in range(1, MAX_SH_DEGREE + 1):
        found = []
        for coef in range(2 * degree + 1):
            attr = _point_attr(pointcloud, RADIANCE_SH_ATTR.format(index=sh_index(degree, coef)), {"FLOAT_VECTOR"})
            if attr is None:
                break
            found.append(_flat(attr, "vector", 3, count))
        if len(found) != 2 * degree + 1:
            break  # a degree is only usable when all of its coefficients are present
        for coef, values in enumerate(found):
            splats.sh[(degree, coef)] = values
    return splats


def build_native_splat_pointcloud(name: str, splats: IRGaussianSplats):
    """IRGaussianSplats -> new PointCloud datablock in Blender's native splat layout."""
    import bpy

    count = len(splats.positions)
    pointcloud = bpy.data.pointclouds.new(name)
    pointcloud.resize(count)

    def put(attr_name, data_type, key, rows):
        attr = pointcloud.attributes.get(attr_name) or pointcloud.attributes.new(attr_name, data_type, "POINT")
        attr.data.foreach_set(key, [float(c) for row in rows for c in row])

    put(POSITION_ATTR, "FLOAT_VECTOR", "vector", splats.positions)
    scales = splats.scales if len(splats.scales) == count else [(0.01, 0.01, 0.01)] * count
    put(SCALE_ATTR, "FLOAT_VECTOR", "vector", scales)
    orientations = splats.orientations if len(splats.orientations) == count else [(0.0, 0.0, 0.0, 1.0)] * count
    put(ROTATION_ATTR, "QUATERNION", "value", [(w, x, y, z) for (x, y, z, w) in orientations])
    opacities = splats.opacities if len(splats.opacities) == count else [1.0] * count
    dc = splats.sh.get((0, 0))
    if not dc or len(dc) != count:
        dc = [(0.0, 0.0, 0.0)] * count
    base_rows = [(*rgb, opacity) for rgb, opacity in zip(dc, opacities)]
    try:
        put(RADIANCE_BASE_ATTR, "FLOAT4", "vector", base_rows)
    except TypeError:
        # FLOAT4 attributes arrived in Blender 5.2; earlier versions keep the four values as a colour
        put(RADIANCE_BASE_ATTR, "FLOAT_COLOR", "color", base_rows)
    for (degree, coef), values in sorted(splats.sh.items()):
        if degree >= 1 and len(values) == count:
            put(RADIANCE_SH_ATTR.format(index=sh_index(degree, coef)), "FLOAT_VECTOR", "vector", values)
    pointcloud[SPLAT_PROPERTY] = True
    pointcloud[SPLAT_COLOR_SPACE_PROPERTY] = splats.color_space
    if pointcloud_type_supported():
        pointcloud.type = GAUSSIAN_SPLAT_TYPE
    return pointcloud
