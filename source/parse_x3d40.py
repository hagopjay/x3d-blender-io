# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math
import re
from xml.etree import ElementTree as ET

try:
    from .ir import IRInlineAsset, IRMetadata, IRScene, IRTransform, IRViewpoint
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRInlineAsset, IRMetadata, IRScene, IRTransform, IRViewpoint


def parse_file(filepath: str) -> IRScene:
    tree = ET.parse(filepath)
    root = tree.getroot()

    metadata = IRMetadata()
    head = root.find("head")
    if head is not None:
        for meta in head.findall("meta"):
            name = meta.attrib.get("name")
            content = meta.attrib.get("content")
            if name == "creator":
                metadata.creator = content
            elif name == "title":
                metadata.title = content
            elif name == "description":
                metadata.description = content

    scene_name = metadata.title or filepath.rsplit("/", maxsplit=1)[-1]
    ir_scene = IRScene(
        name=scene_name,
        source_version=root.attrib.get("version", "4.0"),
        source_path=filepath,
        metadata=metadata,
    )

    scene_element = root.find("Scene")
    if scene_element is not None:
        _collect_inline_assets(scene_element, ir_scene, current_transform=IRTransform())

    return ir_scene


def _collect_inline_assets(element, ir_scene: IRScene, current_transform: IRTransform):
    tag = _local_name(element.tag)
    next_transform = current_transform
    if tag == "Transform":
        next_transform = _compose_transforms(current_transform, _transform_from_element(element))
    elif tag == "Inline":
        url_value = element.attrib.get("url", "").strip()
        for inline_url in _parse_mfstring_urls(url_value):
            ir_scene.inline_assets.append(
                IRInlineAsset(
                    url=inline_url,
                    asset_type=_guess_inline_type(inline_url),
                    transform=IRTransform(
                        translation=next_transform.translation,
                        rotation_axis_angle=next_transform.rotation_axis_angle,
                        scale=next_transform.scale,
                    ),
                )
            )
    elif tag == "Viewpoint":
        ir_scene.viewpoints.append(
            IRViewpoint(
                description=element.attrib.get("description"),
                transform=_compose_transforms(
                    current_transform,
                    IRTransform(
                        translation=_parse_float_tuple(element.attrib.get("position"), 3, (0.0, 0.0, 10.0)),
                        rotation_axis_angle=_parse_float_tuple(
                            element.attrib.get("orientation"),
                            4,
                            (0.0, 0.0, 1.0, 0.0),
                        ),
                    ),
                ),
                field_of_view=_parse_float(element.attrib.get("fieldOfView")),
            )
        )
    elif tag == "NavigationInfo":
        ir_scene.navigation_types.extend(_parse_mfstring_urls(element.attrib.get("type", "").strip()))
    for child in element:
        _collect_inline_assets(child, ir_scene, next_transform)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", maxsplit=1)[-1]
    return tag


def _parse_float_tuple(raw: str | None, expected: int, default: tuple[float, ...]) -> tuple[float, ...]:
    if not raw:
        return default
    values = tuple(float(value) for value in raw.split())
    if len(values) != expected:
        return default
    return values


def _parse_float(raw: str | None) -> float | None:
    if raw is None or raw == "":
        return None
    return float(raw)


def _transform_from_element(element) -> IRTransform:
    return IRTransform(
        translation=_parse_float_tuple(element.attrib.get("translation"), 3, (0.0, 0.0, 0.0)),
        rotation_axis_angle=_parse_float_tuple(element.attrib.get("rotation"), 4, (0.0, 0.0, 1.0, 0.0)),
        scale=_parse_float_tuple(element.attrib.get("scale"), 3, (1.0, 1.0, 1.0)),
    )


def _compose_transforms(parent: IRTransform, child: IRTransform) -> IRTransform:
    parent_matrix = _transform_to_matrix(parent)
    child_matrix = _transform_to_matrix(child)
    composed = _matrix_multiply(parent_matrix, child_matrix)
    translation, rotation_axis_angle, scale = _decompose_matrix(composed)
    return IRTransform(
        translation=translation,
        rotation_axis_angle=rotation_axis_angle,
        scale=scale,
    )


def _transform_to_matrix(transform: IRTransform) -> list[list[float]]:
    tx, ty, tz = transform.translation
    sx, sy, sz = transform.scale
    rotation = _axis_angle_to_matrix(transform.rotation_axis_angle)
    matrix = [
        [rotation[0][0] * sx, rotation[0][1] * sy, rotation[0][2] * sz, tx],
        [rotation[1][0] * sx, rotation[1][1] * sy, rotation[1][2] * sz, ty],
        [rotation[2][0] * sx, rotation[2][1] * sy, rotation[2][2] * sz, tz],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return matrix


def _axis_angle_to_matrix(axis_angle: tuple[float, float, float, float]) -> list[list[float]]:
    x, y, z, angle = axis_angle
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0.0 or angle == 0.0:
        return [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]

    x /= length
    y /= length
    z /= length
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    return [
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ]


def _matrix_multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    result = [[0.0] * 4 for _ in range(4)]
    for row in range(4):
        for col in range(4):
            result[row][col] = sum(a[row][k] * b[k][col] for k in range(4))
    return result


def _decompose_matrix(matrix: list[list[float]]):
    translation = (matrix[0][3], matrix[1][3], matrix[2][3])

    col0 = [matrix[0][0], matrix[1][0], matrix[2][0]]
    col1 = [matrix[0][1], matrix[1][1], matrix[2][1]]
    col2 = [matrix[0][2], matrix[1][2], matrix[2][2]]

    sx = _vector_length(col0)
    sy = _vector_length(col1)
    sz = _vector_length(col2)
    scale = (sx, sy, sz)

    rotation = [
        [
            col0[0] / sx if sx else 1.0,
            col1[0] / sy if sy else 0.0,
            col2[0] / sz if sz else 0.0,
        ],
        [
            col0[1] / sx if sx else 0.0,
            col1[1] / sy if sy else 1.0,
            col2[1] / sz if sz else 0.0,
        ],
        [
            col0[2] / sx if sx else 0.0,
            col1[2] / sy if sy else 0.0,
            col2[2] / sz if sz else 1.0,
        ],
    ]
    rotation_axis_angle = _matrix_to_axis_angle(rotation)
    return translation, rotation_axis_angle, scale


def _vector_length(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def _matrix_to_axis_angle(rotation: list[list[float]]) -> tuple[float, float, float, float]:
    trace = rotation[0][0] + rotation[1][1] + rotation[2][2]
    cos_angle = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
    angle = math.acos(cos_angle)

    if abs(angle) < 1e-8:
        return (0.0, 0.0, 1.0, 0.0)

    if abs(math.pi - angle) < 1e-5:
        xx = max(0.0, (rotation[0][0] + 1.0) * 0.5)
        yy = max(0.0, (rotation[1][1] + 1.0) * 0.5)
        zz = max(0.0, (rotation[2][2] + 1.0) * 0.5)
        x = math.sqrt(xx)
        y = math.sqrt(yy)
        z = math.sqrt(zz)
        if rotation[0][1] < 0.0:
            y = -y
        if rotation[0][2] < 0.0:
            z = -z
        return (x, y, z, angle)

    denom = 2.0 * math.sin(angle)
    x = (rotation[2][1] - rotation[1][2]) / denom
    y = (rotation[0][2] - rotation[2][0]) / denom
    z = (rotation[1][0] - rotation[0][1]) / denom
    return (x, y, z, angle)


def _parse_mfstring_urls(url_value: str) -> list[str]:
    if not url_value:
        return []
    urls = re.findall(r'"([^"]+)"', url_value)
    if urls:
        return urls
    cleaned = url_value.strip().strip("'").strip('"')
    return [cleaned] if cleaned else []


def _guess_inline_type(url_value: str) -> str:
    lower_value = url_value.lower()
    if ".gltf" in lower_value or ".glb" in lower_value or ".vrm" in lower_value:
        return "gltf"
    if ".x3d" in lower_value or ".x3dv" in lower_value or ".wrl" in lower_value:
        return "x3d"
    return "unknown"
