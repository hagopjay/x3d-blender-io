# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
from xml.sax.saxutils import escape

try:
    from .ir import IRScene
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRScene


def _safe_name(name: str) -> str:
    clean = []
    for index, char in enumerate(name or "Material"):
        if char.isalnum() or char == "_":
            clean.append(char)
        else:
            clean.append("_")
        if index == 0 and clean[-1].isdigit():
            clean[-1] = "_"
    return "".join(clean) or "Material"


def _fmt3(values):
    return "%.6f %.6f %.6f" % tuple(values[:3])


def _fmt2(values):
    return "%.6f %.6f" % tuple(values[:2])


def _fmt_ints(values):
    return " ".join(str(value) for value in values)


def _texture_transform_xml(texture_ref, indent):
    transform = texture_ref.transform if texture_ref else None
    if not transform:
        return ""
    return (
        f'{indent}<TextureTransform translation="{_fmt2(transform.translation)}" '
        f'rotation="{transform.rotation:.6f}" scale="{_fmt2(transform.scale)}" />\n'
    )


def _texture_url(texture_ref, output_dir=None):
    filepath = texture_ref.filepath or texture_ref.image_name or ""
    if not filepath:
        return ""
    if output_dir and os.path.isabs(filepath):
        try:
            filepath = os.path.relpath(filepath, output_dir)
        except ValueError:
            pass
    return escape(filepath.replace("\\", "/"))


def _texture_xml(texture_ref, indent, *, container_field=None, output_dir=None):
    if not texture_ref:
        return ""
    filepath = _texture_url(texture_ref, output_dir=output_dir)
    if not filepath:
        return ""
    xml = f"{indent}<ImageTexture"
    if container_field:
        xml += f' containerField="{container_field}"'
    xml += f" url='\"{filepath}\"'"
    if texture_ref.extension == "CLIP":
        xml += ' repeatS="false" repeatT="false"'
    xml += ' />\n'
    return xml


def _texture_bundle_xml(material, indent, *, output_dir=None):
    xml_parts = []
    texture_specs = (
        ("baseTexture", material.base_color_texture),
        ("metallicRoughnessTexture", material.metallic_roughness_texture),
        ("normalTexture", material.normal_texture),
        ("emissiveTexture", material.emissive_texture),
        ("occlusionTexture", material.occlusion_texture),
    )
    for container_field, texture_ref in texture_specs:
        texture_xml = _texture_xml(texture_ref, indent, container_field=container_field, output_dir=output_dir)
        if texture_xml:
            xml_parts.append(texture_xml)
    return "".join(xml_parts)


def _appearance_xml(material, index, indent="      ", *, output_dir=None):
    material_def = f"MAT_{index:03d}_{_safe_name(material.name)}"
    appearance_xml = [f'{indent}<Appearance DEF="{material_def}_APP">\n']
    material_tag = "UnlitMaterial" if material.unlit else "PhysicalMaterial"
    appearance_xml.append(f'{indent}  <{material_tag} DEF="{material_def}"')

    if material.unlit:
        appearance_xml.append(f' emissiveColor="{_fmt3(material.emissive_color)}"')
        transparency = max(0.0, min(1.0, 1.0 - material.base_color[3]))
        appearance_xml.append(f' transparency="{transparency:.6f}"')
    else:
        transparency = max(0.0, min(1.0, 1.0 - material.base_color[3]))
        appearance_xml.append(f' baseColor="{_fmt3(material.base_color)}"')
        if material.metallic is not None:
            appearance_xml.append(f' metallic="{material.metallic:.6f}"')
        if material.roughness is not None:
            appearance_xml.append(f' roughness="{material.roughness:.6f}"')
        if material.normal_scale is not None:
            appearance_xml.append(f' normalScale="{material.normal_scale:.6f}"')
        if material.occlusion_strength is not None:
            appearance_xml.append(f' occlusionStrength="{material.occlusion_strength:.6f}"')
        if any(channel != 0.0 for channel in material.emissive_color[:3]):
            appearance_xml.append(f' emissiveColor="{_fmt3(material.emissive_color)}"')
        appearance_xml.append(f' transparency="{transparency:.6f}"')

    texture_xml = _texture_bundle_xml(material, indent + "  ", output_dir=output_dir)
    appearance_xml.append(">\n")
    if texture_xml:
        appearance_xml.append(texture_xml)
    appearance_xml.append(f'{indent}  </{material_tag}>\n')

    # Keep a single Appearance-level texture transform for the primary texture path.
    primary_transform_xml = _texture_transform_xml(material.base_color_texture, indent + "  ")
    if primary_transform_xml:
        appearance_xml.append(primary_transform_xml)

    appearance_xml.append(f"{indent}</Appearance>\n")
    return "".join(appearance_xml)


def _material_defs(ir_scene):
    return {
        material.name: f"MAT_{index:03d}_{_safe_name(material.name)}"
        for index, material in enumerate(ir_scene.materials)
    }


def _geometry_defs(ir_scene):
    return {
        geometry.name: f"GEO_{index:03d}_{_safe_name(geometry.name)}"
        for index, geometry in enumerate(ir_scene.geometries)
    }


def _geometry_def_xml(geometry, geometry_def, indent="    "):
    point_values = " ".join(_fmt3(point) for point in geometry.coord)
    xml = [f"{indent}<Shape>\n"]
    xml.append(f'{indent}  <IndexedFaceSet DEF="{geometry_def}" coordIndex="{_fmt_ints(geometry.coord_index)}"')
    if not geometry.solid:
        xml.append(' solid="false"')
    if geometry.crease_angle is not None:
        xml.append(f' creaseAngle="{geometry.crease_angle:.6f}"')
    xml.append(">\n")
    xml.append(f'{indent}    <Coordinate point="{point_values}" />\n')
    xml.append(f"{indent}  </IndexedFaceSet>\n")
    xml.append(f"{indent}</Shape>\n")
    return "".join(xml)


def _primitive_geometry_xml(instance, indent):
    primitive = instance.geometry_hint
    if primitive == "Box":
        return f"{indent}<Box size=\"1.000000 1.000000 1.000000\" />\n"
    if primitive == "Cone":
        return f"{indent}<Cone bottomRadius=\"0.500000\" height=\"1.000000\" />\n"
    if primitive == "Cylinder":
        return f"{indent}<Cylinder radius=\"0.500000\" height=\"1.000000\" />\n"
    if primitive == "Rectangle2D":
        return f"{indent}<Rectangle2D size=\"1.000000 1.000000\" />\n"
    if primitive == "Circle2D":
        return f"{indent}<Circle2D radius=\"0.500000\" />\n"
    return f"{indent}<Sphere radius=\"0.750000\" />\n"


def _geometry_xml(instance, geometry_defs, indent):
    if instance.geometry_name and instance.geometry_name in geometry_defs:
        return f'{indent}<IndexedFaceSet USE="{geometry_defs[instance.geometry_name]}" />\n'
    return _primitive_geometry_xml(instance, indent)


def _instance_xml(instance, material_defs, geometry_defs, indent="    "):
    tx, ty, tz = instance.transform.translation
    rx, ry, rz, ra = instance.transform.rotation_axis_angle
    sx, sy, sz = instance.transform.scale
    xml = [
        f'{indent}<Transform DEF="OBJ_{_safe_name(instance.object_name)}" '
        f'translation="{tx:.6f} {ty:.6f} {tz:.6f}" '
        f'rotation="{rx:.6f} {ry:.6f} {rz:.6f} {ra:.6f}" '
        f'scale="{sx:.6f} {sy:.6f} {sz:.6f}">\n',
        f"{indent}  <Shape>\n",
    ]
    if instance.material_name and instance.material_name in material_defs:
        xml.append(f'{indent}    <Appearance USE="{material_defs[instance.material_name]}_APP" />\n')
    else:
        xml.append(f"{indent}    <Appearance>\n")
        xml.append(f"{indent}      <PhysicalMaterial baseColor=\"0.800000 0.800000 0.800000\" metallic=\"0.000000\" roughness=\"0.500000\" />\n")
        xml.append(f"{indent}    </Appearance>\n")
    xml.append(_geometry_xml(instance, geometry_defs, indent + "    "))
    xml.append(f"{indent}  </Shape>\n")
    xml.append(f"{indent}</Transform>\n")
    return "".join(xml)


def export_ir_scene(file, ir_scene: IRScene, *, generator: str = "io_scene_x3d") -> None:
    """X3D 4.0 emitter scaffold with real material output.

    This exists so new work can target a dedicated emitter module immediately.
    It remains conservative on geometry, but emits analyzed material blocks so
    PBR mapping work can be inspected and validated before full scene emission
    is migrated out of the legacy exporter.
    """

    write = file.write
    output_dir = None
    output_name = getattr(file, "name", None)
    if output_name and not str(output_name).startswith("<"):
        output_dir = os.path.dirname(os.path.abspath(output_name))
    write('<?xml version="1.0" encoding="UTF-8"?>\n')
    write('<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">\n')
    write('<X3D version="4.0" profile="Immersive">\n')
    write('  <head>\n')
    write(f'    <meta name="generator" content="{generator}" />\n')
    if ir_scene.metadata.title:
        write(f'    <meta name="title" content="{ir_scene.metadata.title}" />\n')
    if ir_scene.metadata.creator:
        write(f'    <meta name="creator" content="{ir_scene.metadata.creator}" />\n')
    write('  </head>\n')
    write('  <Scene>\n')
    write('    <WorldInfo title="Scaffold Export" info=\'"Modern emitter scaffold; geometry migration still pending."\' />\n')
    if ir_scene.diagnostics:
        info_values = ", ".join(f'"{escape(message)}"' for message in ir_scene.diagnostics)
        write(f"    <WorldInfo title=\"Diagnostics\" info='{info_values}' />\n")
    material_defs = _material_defs(ir_scene)
    geometry_defs = _geometry_defs(ir_scene)
    if ir_scene.materials:
        write('    <Transform DEF="MaterialGallery">\n')
        for index, material in enumerate(ir_scene.materials):
            x_offset = float(index) * 2.5
            write(f'      <Transform translation="{x_offset:.6f} 0.000000 0.000000">\n')
            write('        <Shape>\n')
            write(_appearance_xml(material, index, indent="          ", output_dir=output_dir))
            write('          <Sphere radius="0.750000" />\n')
            write('        </Shape>\n')
            write('      </Transform>\n')
        write('    </Transform>\n')
    if ir_scene.geometries:
        write('    <Switch DEF="GeometryLibrary" whichChoice="-1">\n')
        for geometry in ir_scene.geometries:
            write(_geometry_def_xml(geometry, geometry_defs[geometry.name], indent="      "))
        write('    </Switch>\n')
    if ir_scene.instances:
        write('    <Group DEF="SceneInstances">\n')
        for instance in ir_scene.instances:
            write(_instance_xml(instance, material_defs, geometry_defs, indent="      "))
        write('    </Group>\n')
    write('  </Scene>\n')
    write('</X3D>\n')
