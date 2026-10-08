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
    from .splat_io import sh0_to_rgb
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRScene
    from splat_io import sh0_to_rgb


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
    if geometry.skin_coord_def:
        xml.append(f'{indent}  <Coordinate USE="{geometry.skin_coord_def}" />\n')
    else:
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


def _light_xml(light, defs: _DefNames, indent):
    light_def = defs.get("light", light.name, "LA_")
    attrs = [
        f'DEF="{light_def}"',
        f'color="{_fmt3(light.color)}"',
        f'intensity="{_fmt(light.intensity)}"',
        f'ambientIntensity="{_fmt(light.ambient_intensity)}"',
    ]
    if light.light_type == "DIRECTIONAL":
        attrs.append(f'direction="{_fmt3(light.direction)}"')
        return f"{indent}<DirectionalLight {' '.join(attrs)} />\n"
    attrs.append(f'location="{_fmt3(light.location)}"')
    if light.radius is not None:
        attrs.append(f'radius="{_fmt(light.radius)}"')
    if light.light_type == "SPOT":
        attrs.append(f'direction="{_fmt3(light.direction)}"')
        if light.beam_width is not None:
            attrs.append(f'beamWidth="{_fmt(light.beam_width)}"')
        if light.cut_off_angle is not None:
            attrs.append(f'cutOffAngle="{_fmt(light.cut_off_angle)}"')
        return f"{indent}<SpotLight {' '.join(attrs)} />\n"
    return f"{indent}<PointLight {' '.join(attrs)} />\n"


def _viewpoint_xml(viewpoint, defs: _DefNames, indent):
    view_def = defs.get("viewpoint", viewpoint.name or viewpoint.description or "Viewpoint", "CA_")
    attrs = [f'DEF="{view_def}"']
    if viewpoint.description:
        attrs.append(f"description={quoteattr(viewpoint.description)}")
    attrs.append(f'position="{_fmt3(viewpoint.transform.translation)}"')
    attrs.append(f'orientation="{_fmt4(viewpoint.transform.rotation_axis_angle)}"')
    if viewpoint.field_of_view is not None:
        attrs.append(f'fieldOfView="{_fmt(viewpoint.field_of_view)}"')
    return f"{indent}<Viewpoint {' '.join(attrs)} />\n"


def _instance_xml(instance, geometries, materials, defs: _DefNames, indent, *, output_dir=None, humanoids=None,
                  splats=None, version="4.0"):
    humanoids = humanoids or {}
    splats = splats or {}
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
    if instance.humanoid_name and instance.humanoid_name in humanoids:
        humanoid = humanoids[instance.humanoid_name]
        placed = type(humanoid)(name=humanoid.name, root_joints=humanoid.root_joints,
                                skin_coord=humanoid.skin_coord, skin_shapes=humanoid.skin_shapes)
        xml.append(_humanoid_xml(placed, geometries, materials, defs, indent + "  ", output_dir=output_dir))
    if instance.inline is not None:
        inline_def = defs.get("inline", instance.object_name, "IN_")
        xml.append(f"{indent}  <Inline DEF=\"{inline_def}\" url='{_mfstring([instance.inline.url])}' />\n")
    if instance.splats_name and instance.splats_name in splats:
        xml.append(_splats_xml(splats[instance.splats_name], defs, indent + "  ", version=version))
    if instance.light is not None:
        xml.append(_light_xml(instance.light, defs, indent + "  "))
    if instance.viewpoint is not None:
        xml.append(_viewpoint_xml(instance.viewpoint, defs, indent + "  "))
    for child in instance.children:
        xml.append(_instance_xml(child, geometries, materials, defs, indent + "  ", output_dir=output_dir, humanoids=humanoids,
                                 splats=splats, version=version))
    xml.append(f"{indent}</Transform>\n")
    return "".join(xml)


def _joint_def(defs: _DefNames, humanoid_name, joint_name):
    return defs.get("joint", f"{humanoid_name}:{joint_name}", "hanim_")


def _joint_xml(joint, humanoid_name, defs: _DefNames, indent, *, container_field="children"):
    joint_def = _joint_def(defs, humanoid_name, joint.name)
    attrs = [f'DEF="{joint_def}"', f"name={quoteattr(joint.name)}", f'center="{_fmt3(joint.center)}"']
    if container_field != "children":
        attrs.append(f'containerField="{container_field}"')
    if joint.skin_coord_index:
        attrs.append(f'skinCoordIndex="{_fmt_ints(joint.skin_coord_index)}"')
        attrs.append(f'skinCoordWeight="{" ".join(_fmt(weight) for weight in joint.skin_coord_weight)}"')
    if not joint.children:
        return f"{indent}<HAnimJoint {' '.join(attrs)} />\n"
    xml = [f"{indent}<HAnimJoint {' '.join(attrs)}>\n"]
    for child in joint.children:
        xml.append(_joint_xml(child, humanoid_name, defs, indent + "  "))
    xml.append(f"{indent}</HAnimJoint>\n")
    return "".join(xml)


def _humanoid_xml(humanoid, geometries, materials, defs: _DefNames, indent, *, output_dir=None):
    humanoid_def = defs.get("humanoid", humanoid.name, "hanim_")
    tx = humanoid.transform
    xml = [
        f'{indent}<HAnimHumanoid DEF="{humanoid_def}" name={quoteattr(humanoid.name)} version="2.0" '
        f'skeletalConfiguration="BLENDER" '
        f'translation="{_fmt3(tx.translation)}" rotation="{_fmt4(tx.rotation_axis_angle)}" '
        f'scale="{_fmt3(tx.scale)}">\n'
    ]
    for root in humanoid.root_joints:
        xml.append(_joint_xml(root, humanoid.name, defs, indent + "  ", container_field="skeleton"))
    for joint in humanoid.iter_joints():
        xml.append(f'{indent}  <HAnimJoint USE="{_joint_def(defs, humanoid.name, joint.name)}" containerField="joints" />\n')
    if humanoid.skin_coord:
        skin_def = next((geometries[s.geometry_name].skin_coord_def for s in humanoid.skin_shapes
                         if s.geometry_name in geometries and geometries[s.geometry_name].skin_coord_def), None)
        if skin_def:
            xml.append(
                f'{indent}  <Coordinate DEF="{skin_def}" containerField="skinCoord" '
                f'point="{" ".join(_fmt3(point) for point in humanoid.skin_coord)}" />\n'
            )
    for shape in humanoid.skin_shapes:
        xml.append(f'{indent}  <Shape containerField="skin">\n')
        material = materials.get(shape.material_name) if shape.material_name else None
        if material is not None:
            xml.append(_appearance_xml(material, defs, indent + "    ", output_dir=output_dir))
        else:
            xml.append(_default_appearance_xml(indent + "    "))
        geometry = geometries.get(shape.geometry_name)
        if geometry is not None:
            xml.append(_geometry_xml(geometry, defs, indent + "    "))
        xml.append(f"{indent}  </Shape>\n")
    xml.append(f"{indent}</HAnimHumanoid>\n")
    return "".join(xml)


def _animation_xml(ir_scene, defs: _DefNames, indent):
    if not ir_scene.animations:
        return ""
    cycle = ir_scene.cycle_interval or 1.0
    timer_def = defs.get("timer", "SceneTimer", "")
    xml = [f'{indent}<TimeSensor DEF="{timer_def}" cycleInterval="{_fmt(cycle)}" loop="true" />\n']
    routes = []
    for animation in ir_scene.animations:
        if animation.target_kind == "joint":
            humanoid_name, _, joint_name = animation.target.partition(":")
            target_def = _joint_def(defs, humanoid_name, joint_name)
        else:
            target_def = defs.get("transform", animation.target, "OB_")
        keys = " ".join(_fmt(key) for key in animation.keys)
        safe_target = _safe_name(animation.target)
        if animation.translations:
            node_def = f"PI_{safe_target}"
            xml.append(
                f'{indent}<PositionInterpolator DEF="{node_def}" key="{keys}" '
                f'keyValue="{" ".join(_fmt3(value) for value in animation.translations)}" />\n'
            )
            routes.append((timer_def, "fraction_changed", node_def, "set_fraction"))
            routes.append((node_def, "value_changed", target_def, "set_translation"))
        if animation.rotations:
            node_def = f"OI_{safe_target}"
            xml.append(
                f'{indent}<OrientationInterpolator DEF="{node_def}" key="{keys}" '
                f'keyValue="{" ".join(_fmt4(value) for value in animation.rotations)}" />\n'
            )
            routes.append((timer_def, "fraction_changed", node_def, "set_fraction"))
            routes.append((node_def, "value_changed", target_def, "set_rotation"))
        if animation.scales:
            node_def = f"SI_{safe_target}"
            xml.append(
                f'{indent}<PositionInterpolator DEF="{node_def}" key="{keys}" '
                f'keyValue="{" ".join(_fmt3(value) for value in animation.scales)}" />\n'
            )
            routes.append((timer_def, "fraction_changed", node_def, "set_fraction"))
            routes.append((node_def, "value_changed", target_def, "set_scale"))
    for from_node, from_field, to_node, to_field in routes:
        xml.append(
            f'{indent}<ROUTE fromNode="{from_node}" fromField="{from_field}" '
            f'toNode="{to_node}" toField="{to_field}" />\n'
        )
    return "".join(xml)


_SH_FIELD = "sphericalHarmonicsDegree{degree}Coef{coef}"


def _splats_xml(splats, defs: _DefNames, indent, *, version="4.0"):
    """GaussianSplats node for X3D 4.1; a coloured PointSet for earlier versions."""
    splats_def = defs.get("splats", splats.name, "GS_")
    if version == "4.1":
        if not defs.first_use("splats", splats.name):
            return f'{indent}<GaussianSplats USE="{splats_def}" />\n'
        attrs = [f'DEF="{splats_def}"']
        if splats.color_space != "SRGB_REC709_DISPLAY":
            attrs.append(f'colorSpace="{escape(splats.color_space)}"')
        attrs.append(f'positions="{" ".join(_fmt3(p) for p in splats.positions)}"')
        if splats.scales:
            attrs.append(f'scales="{" ".join(_fmt3(s) for s in splats.scales)}"')
        if splats.orientations:
            attrs.append(f'orientations="{" ".join(_fmt4(q) for q in splats.orientations)}"')
        if splats.opacities:
            attrs.append(f'opacities="{" ".join(_fmt(o) for o in splats.opacities)}"')
        for (degree, coef), values in sorted(splats.sh.items()):
            if values:
                attrs.append(f'{_SH_FIELD.format(degree=degree, coef=coef)}="{" ".join(_fmt3(v) for v in values)}"')
        return f"{indent}<GaussianSplats {' '.join(attrs)} />\n"
    # 4.0 fallback: centres as a PointSet with the reconstructed base colour
    xml = [f"{indent}<Shape>\n"]
    if not defs.first_use("splats", splats.name):
        xml.append(f'{indent}  <PointSet USE="{splats_def}" />\n')
    else:
        xml.append(f'{indent}  <PointSet DEF="{splats_def}">\n')
        xml.append(f'{indent}    <Coordinate point="{" ".join(_fmt3(p) for p in splats.positions)}" />\n')
        dc = splats.sh.get((0, 0))
        if dc:
            colors = (sh0_to_rgb(c) + (max(0.0, min(1.0, splats.opacities[i])) if i < len(splats.opacities) else 1.0,)
                      for i, c in enumerate(dc))
            xml.append(f'{indent}    <ColorRGBA color="{" ".join(_fmt4(c) for c in colors)}" />\n')
        xml.append(f"{indent}  </PointSet>\n")
    xml.append(f"{indent}</Shape>\n")
    return "".join(xml)


def _meta(name, content):
    return f"    <meta name={quoteattr(name)} content={quoteattr(str(content))} />\n"


def export_ir_scene(file, ir_scene: IRScene, *, generator: str = "io_scene_x3d", version: str = "4.0") -> None:
    """Write ``ir_scene`` as an X3D 4.0 (or 4.1 draft) XML document to ``file``.

    With ``version`` "4.1" Gaussian splats are written as the GaussianSplats
    node (component GaussianSplats level 1); with "4.0" they degrade to a
    coloured PointSet and a diagnostic says so.
    """
    if version not in {"4.0", "4.1"}:
        raise ValueError(f"Unsupported X3D version for the modern writer: {version!r}")
    diagnostics = list(ir_scene.diagnostics)
    if version == "4.0" and ir_scene.splats:
        diagnostics.append(
            f"{len(ir_scene.splats)} Gaussian splat object(s) written as PointSet; choose X3D 4.1 for the GaussianSplats node."
        )

    write = file.write
    output_dir = None
    output_name = getattr(file, "name", None)
    if output_name and not str(output_name).startswith("<"):
        output_dir = os.path.dirname(os.path.abspath(output_name))

    write('<?xml version="1.0" encoding="UTF-8"?>\n')
    write(f'<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D {version}//EN" "https://www.web3d.org/specifications/x3d-{version}.dtd">\n')
    write(
        f'<X3D version="{version}" profile="Immersive" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsd:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-{version}.xsd">\n'
    )
    write("  <head>\n")
    if version == "4.1" and ir_scene.splats:
        write('    <component name="GaussianSplats" level="1" />\n')
    if ir_scene.humanoids:
        write('    <component name="HAnim" level="1" />\n')
    write(_meta("generator", generator))
    metadata = ir_scene.metadata
    for name in ("filename", "title", "creator", "description", "keywords", "reference", "license"):
        value = getattr(metadata, name, None)
        if value:
            write(_meta(name, value))
    for message in diagnostics:
        write(_meta("info", message))
    write("  </head>\n")
    write("  <Scene>\n")

    defs = _DefNames()
    geometries = ir_scene.geometry_by_name()
    materials = ir_scene.material_by_name()
    has_lights = ir_scene.has_lights()
    write(
        f'    <NavigationInfo headlight="{"false" if has_lights else "true"}" '
        "type='\"EXAMINE\" \"ANY\"' />\n"
    )
    if ir_scene.background_color is not None:
        write(f'    <Background skyColor="{_fmt3(ir_scene.background_color)}" />\n')
    humanoids = {humanoid.name: humanoid for humanoid in ir_scene.humanoids}
    splats = ir_scene.splats_by_name()
    for instance in ir_scene.instances:
        write(_instance_xml(instance, geometries, materials, defs, "    ", output_dir=output_dir, humanoids=humanoids,
                            splats=splats, version=version))
    write(_animation_xml(ir_scene, defs, "    "))

    write("  </Scene>\n")
    write("</X3D>\n")
