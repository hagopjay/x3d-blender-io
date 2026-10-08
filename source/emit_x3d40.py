# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""IR -> X3D 4.0 XML emitter.

Pure Python, no ``bpy``. Nodes are written with DEF on first use and USE on
every later use, so repeated meshes and materials are shared instead of
duplicated.
"""

from __future__ import annotations

import os
from xml.sax.saxutils import escape, quoteattr

try:
    from .ir import IRScene
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRScene


def _safe_name(name: str, fallback: str = "Node") -> str:
    clean = []
    for index, char in enumerate(name or fallback):
        if char.isalnum() or char == "_":
            clean.append(char)
        else:
            clean.append("_")
        if index == 0 and clean[-1].isdigit():
            clean[-1] = "_"
    return "".join(clean) or fallback


class _DefNames:
    """Allocate unique DEF names per IR object key and track first use."""

    def __init__(self):
        self._by_key: dict[tuple[str, str], str] = {}
        self._used: set[str] = set()
        self.emitted: set[tuple[str, str]] = set()

    def get(self, kind: str, key: str, prefix: str) -> str:
        lookup = (kind, key)
        name = self._by_key.get(lookup)
        if name is None:
            base = f"{prefix}{_safe_name(key, kind)}"
            name = base
            counter = 1
            while name in self._used:
                counter += 1
                name = f"{base}_{counter}"
            self._used.add(name)
            self._by_key[lookup] = name
        return name

    def first_use(self, kind: str, key: str) -> bool:
        lookup = (kind, key)
        if lookup in self.emitted:
            return False
        self.emitted.add(lookup)
        return True


def _fmt(value: float) -> str:
    return "%.6f" % value


def _fmt2(values):
    return "%.6f %.6f" % tuple(values[:2])


def _fmt3(values):
    return "%.6f %.6f %.6f" % tuple(values[:3])


def _fmt4(values):
    return "%.6f %.6f %.6f %.6f" % tuple(values[:4])


def _fmt_ints(values):
    return " ".join(str(value) for value in values)


def _mfstring(values):
    """Encode a list of strings as an X3D MFString attribute value (single-quoted)."""
    parts = ['"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"' for value in values]
    return escape(" ".join(parts)).replace("'", "&apos;")


# ---------------------------------------------------------------------------
# Appearance


def _texture_url(texture_ref, output_dir=None):
    url = texture_ref.url
    if url is None:
        url = texture_ref.filepath or texture_ref.image_name or ""
        if url and output_dir and os.path.isabs(url):
            try:
                url = os.path.relpath(url, output_dir)
            except ValueError:
                pass
    return url.replace("\\", "/") if url else ""


def _texture_xml(texture_ref, indent, *, container_field, output_dir=None):
    url = _texture_url(texture_ref, output_dir=output_dir)
    if not url:
        return ""
    xml = f"{indent}<ImageTexture containerField=\"{container_field}\" url='{_mfstring([url])}'"
    if texture_ref.extension == "CLIP":
        xml += ' repeatS="false" repeatT="false"'
    xml += " />\n"
    return xml


def _texture_transform_xml(material, indent):
    """Appearance-level TextureTransform taken from the first mapped texture."""
    for _container_field, texture_ref in material.texture_refs():
        transform = texture_ref.transform
        if transform is None:
            continue
        if (
            tuple(transform.translation) == (0.0, 0.0)
            and float(transform.rotation) == 0.0
            and tuple(transform.scale) == (1.0, 1.0)
        ):
            continue
        return (
            f'{indent}<TextureTransform translation="{_fmt2(transform.translation)}" '
            f'rotation="{_fmt(transform.rotation)}" scale="{_fmt2(transform.scale)}" />\n'
        )
    return ""


def _material_xml(material, material_def, indent, *, output_dir=None):
    tag = "UnlitMaterial" if material.unlit else "PhysicalMaterial"
    alpha = material.base_color[3] if len(material.base_color) > 3 else 1.0
    transparency = max(0.0, min(1.0, 1.0 - alpha))
    attrs = [f'DEF="{material_def}"']
    textures = []

    if material.unlit:
        attrs.append(f'emissiveColor="{_fmt3(material.emissive_color)}"')
        if transparency > 0.0:
            attrs.append(f'transparency="{_fmt(transparency)}"')
        if material.normal_scale is not None and material.normal_scale != 1.0:
            attrs.append(f'normalScale="{_fmt(material.normal_scale)}"')
        emissive_ref = material.emissive_texture or material.base_color_texture
        if emissive_ref is not None:
            textures.append(("emissiveTexture", emissive_ref))
        if material.normal_texture is not None:
            textures.append(("normalTexture", material.normal_texture))
    else:
        attrs.append(f'baseColor="{_fmt3(material.base_color)}"')
        if material.metallic is not None:
            attrs.append(f'metallic="{_fmt(material.metallic)}"')
        if material.roughness is not None:
            attrs.append(f'roughness="{_fmt(material.roughness)}"')
        if material.normal_scale is not None and material.normal_scale != 1.0:
            attrs.append(f'normalScale="{_fmt(material.normal_scale)}"')
        if material.occlusion_strength is not None and material.occlusion_strength != 1.0:
            attrs.append(f'occlusionStrength="{_fmt(material.occlusion_strength)}"')
        if any(channel != 0.0 for channel in material.emissive_color[:3]):
            attrs.append(f'emissiveColor="{_fmt3(material.emissive_color)}"')
        if transparency > 0.0:
            attrs.append(f'transparency="{_fmt(transparency)}"')
        textures.extend(material.texture_refs())

    texture_xml = "".join(
        _texture_xml(texture_ref, indent + "  ", container_field=container_field, output_dir=output_dir)
        for container_field, texture_ref in textures
    )
    if texture_xml:
        return f"{indent}<{tag} {' '.join(attrs)}>\n{texture_xml}{indent}</{tag}>\n"
    return f"{indent}<{tag} {' '.join(attrs)} />\n"


def _appearance_xml(material, defs: _DefNames, indent, *, output_dir=None):
    app_def = defs.get("appearance", material.name, "APP_")
    if not defs.first_use("appearance", material.name):
        return f'{indent}<Appearance USE="{app_def}" />\n'
    material_def = defs.get("material", material.name, "MA_")
    attrs = [f'DEF="{app_def}"']
    if material.alpha_mode == "BLEND":
        attrs.append('alphaMode="BLEND"')
    elif material.alpha_mode == "MASK":
        attrs.append('alphaMode="MASK"')
        if material.alpha_cutoff is not None:
            attrs.append(f'alphaCutoff="{_fmt(material.alpha_cutoff)}"')
    xml = [f"{indent}<Appearance {' '.join(attrs)}>\n"]
    xml.append(_material_xml(material, material_def, indent + "  ", output_dir=output_dir))
    xml.append(_texture_transform_xml(material, indent + "  "))
    xml.append(f"{indent}</Appearance>\n")
    return "".join(xml)


def _default_appearance_xml(indent):
    return (
        f"{indent}<Appearance>\n"
        f'{indent}  <PhysicalMaterial baseColor="0.800000 0.800000 0.800000" metallic="0.000000" roughness="0.500000" />\n'
        f"{indent}</Appearance>\n"
    )


# ---------------------------------------------------------------------------
# Geometry


def _geometry_xml(geometry, defs: _DefNames, indent):
    geometry_def = defs.get("geometry", geometry.name, "ME_")
    if not defs.first_use("geometry", geometry.name):
        return f'{indent}<IndexedFaceSet USE="{geometry_def}" />\n'
    attrs = [f'DEF="{geometry_def}"', f'coordIndex="{_fmt_ints(geometry.coord_index)}"']
    if not geometry.solid:
        attrs.append('solid="false"')
    if geometry.crease_angle is not None and geometry.crease_angle > 0.0:
        attrs.append(f'creaseAngle="{_fmt(geometry.crease_angle)}"')
    xml = [f"{indent}<IndexedFaceSet {' '.join(attrs)}>\n"]
    xml.append(f'{indent}  <Coordinate point="{" ".join(_fmt3(point) for point in geometry.coord)}" />\n')
    if geometry.normal:
        xml.append(f'{indent}  <Normal vector="{" ".join(_fmt3(vector) for vector in geometry.normal)}" />\n')
    if geometry.tex_coord:
        xml.append(
            f'{indent}  <TextureCoordinate point="{" ".join(_fmt2(point) for point in geometry.tex_coord)}" />\n'
        )
    if geometry.color:
        xml.append(f'{indent}  <ColorRGBA color="{" ".join(_fmt4(color) for color in geometry.color)}" />\n')
    xml.append(f"{indent}</IndexedFaceSet>\n")
    return "".join(xml)


def _primitive_geometry_xml(hint, indent):
    if hint == "Box":
        return f'{indent}<Box size="1.000000 1.000000 1.000000" />\n'
    if hint == "Cone":
        return f'{indent}<Cone bottomRadius="0.500000" height="1.000000" />\n'
    if hint == "Cylinder":
        return f'{indent}<Cylinder radius="0.500000" height="1.000000" />\n'
    if hint == "Rectangle2D":
        return f'{indent}<Rectangle2D size="1.000000 1.000000" />\n'
    if hint == "Circle2D":
        return f'{indent}<Circle2D radius="0.500000" />\n'
    return f'{indent}<Sphere radius="0.750000" />\n'


# ---------------------------------------------------------------------------
# Scene


def _instance_xml(instance, geometries, materials, defs: _DefNames, indent, *, output_dir=None):
    tx, ty, tz = instance.transform.translation
    rx, ry, rz, ra = instance.transform.rotation_axis_angle
    sx, sy, sz = instance.transform.scale
    transform_def = defs.get("transform", instance.object_name, "OB_")
    xml = [
        f'{indent}<Transform DEF="{transform_def}" '
        f'translation="{_fmt3((tx, ty, tz))}" '
        f'rotation="{_fmt4((rx, ry, rz, ra))}" '
        f'scale="{_fmt3((sx, sy, sz))}">\n'
    ]
    for shape in instance.iter_shapes():
        xml.append(f"{indent}  <Shape>\n")
        material = materials.get(shape.material_name) if shape.material_name else None
        if material is not None:
            xml.append(_appearance_xml(material, defs, indent + "    ", output_dir=output_dir))
        else:
            xml.append(_default_appearance_xml(indent + "    "))
        geometry = geometries.get(shape.geometry_name) if shape.geometry_name else None
        if geometry is not None:
            xml.append(_geometry_xml(geometry, defs, indent + "    "))
        else:
            xml.append(_primitive_geometry_xml(shape.geometry_hint, indent + "    "))
        xml.append(f"{indent}  </Shape>\n")
    xml.append(f"{indent}</Transform>\n")
    return "".join(xml)


def _meta(name, content):
    return f"    <meta name={quoteattr(name)} content={quoteattr(str(content))} />\n"


def export_ir_scene(file, ir_scene: IRScene, *, generator: str = "io_scene_x3d") -> None:
    """Write ``ir_scene`` as an X3D 4.0 XML document to ``file``."""

    write = file.write
    output_dir = None
    output_name = getattr(file, "name", None)
    if output_name and not str(output_name).startswith("<"):
        output_dir = os.path.dirname(os.path.abspath(output_name))

    write('<?xml version="1.0" encoding="UTF-8"?>\n')
    write('<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">\n')
    write(
        '<X3D version="4.0" profile="Immersive" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance" '
        'xsd:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">\n'
    )
    write("  <head>\n")
    write(_meta("generator", generator))
    metadata = ir_scene.metadata
    for name in ("filename", "title", "creator", "description", "keywords", "reference", "license"):
        value = getattr(metadata, name, None)
        if value:
            write(_meta(name, value))
    for message in ir_scene.diagnostics:
        write(_meta("info", message))
    write("  </head>\n")
    write("  <Scene>\n")

    defs = _DefNames()
    geometries = ir_scene.geometry_by_name()
    materials = ir_scene.material_by_name()
    for instance in ir_scene.instances:
        write(_instance_xml(instance, geometries, materials, defs, "    ", output_dir=output_dir))

    write("  </Scene>\n")
    write("</X3D>\n")
