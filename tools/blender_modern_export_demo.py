# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import sys
from pathlib import Path

import addon_utils
import bpy


REPO_ROOT = Path(__file__).resolve().parents[2]
ADDON_SOURCE_DIR = REPO_ROOT / "io_scene_x3d" / "source"
DEMO_DIR = REPO_ROOT / "demo" / "investor_poc"
TEXTURE_DIR = DEMO_DIR / "textures"
OUTPUT_X3D = DEMO_DIR / "blender_modern_poc.x3d"
OUTPUT_GLB = DEMO_DIR / "blender_scene.glb"
OUTPUT_GLB_ALT = DEMO_DIR / "blender_scene_alt.glb"
OUTPUT_GLB_WHOPPER = DEMO_DIR / "blender_whopper_ellipsoid.glb"
OUTPUT_INLINE_X3D = DEMO_DIR / "xite_gltf_inline_poc.x3d"
OUTPUT_MULTI_INLINE_X3D = DEMO_DIR / "xite_gltf_multi_inline_poc.x3d"
OUTPUT_WHOPPER_INLINE_X3D = DEMO_DIR / "xite_whopper_inline_poc.x3d"
OUTPUT_MANIFEST = DEMO_DIR / "demo_manifest.json"
LANDING_HTML = DEMO_DIR / "index.html"
DIRECT_VIEWER_HTML = DEMO_DIR / "direct_x3d.html"
INLINE_VIEWER_HTML = DEMO_DIR / "gltf_inline.html"
MULTI_INLINE_VIEWER_HTML = DEMO_DIR / "gltf_multi_inline.html"
WHOPPER_VIEWER_HTML = DEMO_DIR / "whopper_glb.html"


def _load_addon_package():
    package_name = "io_scene_x3d"
    if package_name in sys.modules:
        return sys.modules[package_name]

    spec = importlib.util.spec_from_file_location(
        package_name,
        ADDON_SOURCE_DIR / "__init__.py",
        submodule_search_locations=[str(ADDON_SOURCE_DIR)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to create addon module spec for io_scene_x3d")

    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return module


def _reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.lights,
        bpy.data.cameras,
    ):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def _write_image(name: str, width: int, height: int, pixels, *, colorspace="sRGB"):
    image = bpy.data.images.new(name=name, width=width, height=height, alpha=True)
    image.filepath_raw = str((TEXTURE_DIR / f"{name}.png").resolve())
    image.file_format = "PNG"
    image.colorspace_settings.name = colorspace
    image.pixels = pixels
    image.save()
    return image


def _make_texture_assets():
    TEXTURE_DIR.mkdir(parents=True, exist_ok=True)

    def rgba(r, g, b, a=1.0):
        return [r, g, b, a]

    base_pixels = []
    orm_pixels = []
    normal_pixels = []
    emissive_pixels = []
    ao_pixels = []
    for y in range(4):
        for x in range(4):
            u = x / 3.0
            v = y / 3.0
            base_pixels.extend(rgba(0.45 + 0.4 * u, 0.15 + 0.3 * v, 0.1 + 0.2 * (1.0 - u)))
            orm_pixels.extend(rgba(0.0, 0.2 + 0.6 * v, 0.25 + 0.65 * u))
            nx = 0.5 + 0.2 * math.sin(u * math.pi)
            ny = 0.5 + 0.2 * math.cos(v * math.pi)
            normal_pixels.extend(rgba(nx, ny, 1.0, 1.0))
            emissive_pixels.extend(rgba(0.1 + 0.5 * u, 0.02, 0.0 + 0.35 * v))
            ao_value = 0.35 + 0.55 * ((x + y) % 2)
            ao_pixels.extend(rgba(ao_value, ao_value, ao_value))

    return {
        "base": _write_image("hero_base", 4, 4, base_pixels, colorspace="sRGB"),
        "orm": _write_image("hero_orm", 4, 4, orm_pixels, colorspace="Non-Color"),
        "normal": _write_image("hero_normal", 4, 4, normal_pixels, colorspace="Non-Color"),
        "emissive": _write_image("hero_emissive", 4, 4, emissive_pixels, colorspace="sRGB"),
        "occlusion": _write_image("hero_occlusion", 4, 4, ao_pixels, colorspace="Non-Color"),
    }


def _make_whopper_texture_assets():
    TEXTURE_DIR.mkdir(parents=True, exist_ok=True)

    def rgba(r, g, b, a=1.0):
        return [r, g, b, a]

    width = 1024
    height = 512
    base_pixels = []
    orm_pixels = []
    normal_pixels = []
    emissive_pixels = []

    for y in range(height):
        for x in range(width):
            u = x / max(1, width - 1)
            v = y / max(1, height - 1)
            wave = 0.5 + 0.5 * math.sin((u * math.pi * 8.0) + (v * math.pi * 2.5))
            ridge = 0.5 + 0.5 * math.cos((u * math.pi * 3.0) - (v * math.pi * 6.0))
            warm = 0.45 + 0.35 * wave
            cool = 0.18 + 0.24 * ridge
            depth = 0.2 + 0.65 * (1.0 - abs((v * 2.0) - 1.0))
            spark = 0.5 + 0.5 * math.sin((u * math.pi * 24.0) + (v * math.pi * 13.0))

            r = min(1.0, 0.22 + warm + (0.18 * spark))
            g = min(1.0, 0.08 + (0.52 * depth) + (0.14 * wave))
            b = min(1.0, 0.18 + cool + (0.12 * spark))
            base_pixels.extend(rgba(r, g, b))

            occlusion = 0.2 + 0.7 * depth
            roughness = 0.18 + 0.55 * (1.0 - wave)
            metallic = 0.62 + 0.28 * ridge
            orm_pixels.extend(rgba(occlusion, roughness, metallic))

            nx = 0.5 + 0.18 * math.sin(u * math.pi * 18.0)
            ny = 0.5 + 0.18 * math.cos(v * math.pi * 12.0)
            normal_pixels.extend(rgba(nx, ny, 1.0))

            emissive = max(0.0, (spark - 0.86) * 5.5)
            emissive_pixels.extend(rgba(emissive, emissive * 0.4, emissive * 0.8))

    return {
        "base": _write_image("whopper_base", width, height, base_pixels, colorspace="sRGB"),
        "orm": _write_image("whopper_orm", width, height, orm_pixels, colorspace="Non-Color"),
        "normal": _write_image("whopper_normal", width, height, normal_pixels, colorspace="Non-Color"),
        "emissive": _write_image("whopper_emissive", width, height, emissive_pixels, colorspace="sRGB"),
    }


def _build_hero_material(material, texture_assets):
    material.use_nodes = True
    node_tree = material.node_tree
    nodes = node_tree.nodes
    links = node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (900, 100)
    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.location = (520, 120)
    principled.inputs["Metallic"].default_value = 0.9
    principled.inputs["Roughness"].default_value = 0.2
    principled.inputs["Emission Strength"].default_value = 1.25
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    texcoord = nodes.new(type="ShaderNodeTexCoord")
    texcoord.location = (-900, 40)
    mapping = nodes.new(type="ShaderNodeMapping")
    mapping.location = (-680, 40)
    mapping.inputs["Location"].default_value = (0.1, 0.05, 0.0)
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, 0.18)
    mapping.inputs["Scale"].default_value = (1.35, 1.35, 1.0)
    links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])

    base_tex = nodes.new(type="ShaderNodeTexImage")
    base_tex.name = "BaseColorTexture"
    base_tex.label = "BaseColorTexture"
    base_tex.image = texture_assets["base"]
    base_tex.location = (-640, 260)
    links.new(mapping.outputs["Vector"], base_tex.inputs["Vector"])
    tint = nodes.new(type="ShaderNodeRGB")
    tint.location = (-640, 430)
    tint.outputs[0].default_value = (0.95, 0.68, 0.44, 1.0)
    mix_rgb = nodes.new(type="ShaderNodeMixRGB")
    mix_rgb.location = (-380, 260)
    mix_rgb.blend_type = "MIX"
    mix_rgb.inputs["Fac"].default_value = 0.28
    links.new(base_tex.outputs["Color"], mix_rgb.inputs["Color1"])
    links.new(tint.outputs["Color"], mix_rgb.inputs["Color2"])
    links.new(mix_rgb.outputs["Color"], principled.inputs["Base Color"])

    orm_tex = nodes.new(type="ShaderNodeTexImage")
    orm_tex.name = "ORMTexture"
    orm_tex.label = "ORMTexture"
    orm_tex.image = texture_assets["orm"]
    orm_tex.location = (-640, 0)
    links.new(mapping.outputs["Vector"], orm_tex.inputs["Vector"])
    separate_type = "ShaderNodeSeparateColor"
    try:
        separate_rgb = nodes.new(type=separate_type)
    except RuntimeError:
        separate_type = "ShaderNodeSeparateRGB"
        separate_rgb = nodes.new(type=separate_type)
    separate_rgb.location = (-380, 0)
    links.new(orm_tex.outputs["Color"], separate_rgb.inputs.get("Color") or separate_rgb.inputs.get("Image"))
    green_output = separate_rgb.outputs.get("G") or separate_rgb.outputs.get("Green")
    blue_output = separate_rgb.outputs.get("B") or separate_rgb.outputs.get("Blue")

    roughness_value = nodes.new(type="ShaderNodeValue")
    roughness_value.location = (-180, 90)
    roughness_value.outputs[0].default_value = 0.85
    roughness_math = nodes.new(type="ShaderNodeMath")
    roughness_math.location = (40, 60)
    roughness_math.operation = "MULTIPLY"
    links.new(green_output, roughness_math.inputs[0])
    links.new(roughness_value.outputs[0], roughness_math.inputs[1])
    roughness_map = nodes.new(type="ShaderNodeMapRange")
    roughness_map.location = (250, 60)
    roughness_map.inputs["From Min"].default_value = 0.0
    roughness_map.inputs["From Max"].default_value = 1.0
    roughness_map.inputs["To Min"].default_value = 0.12
    roughness_map.inputs["To Max"].default_value = 0.84
    roughness_map.clamp = True
    roughness_clamp = nodes.new(type="ShaderNodeClamp")
    roughness_clamp.location = (470, 60)
    roughness_clamp.inputs["Min"].default_value = 0.1
    roughness_clamp.inputs["Max"].default_value = 0.78
    links.new(roughness_math.outputs[0], roughness_map.inputs["Value"])
    links.new(roughness_map.outputs[0], roughness_clamp.inputs["Value"])
    links.new(roughness_clamp.outputs[0], principled.inputs["Roughness"])

    metallic_value = nodes.new(type="ShaderNodeValue")
    metallic_value.location = (-180, -40)
    metallic_value.outputs[0].default_value = 1.0
    metallic_math = nodes.new(type="ShaderNodeMath")
    metallic_math.location = (40, -40)
    metallic_math.operation = "MULTIPLY"
    links.new(blue_output, metallic_math.inputs[0])
    links.new(metallic_value.outputs[0], metallic_math.inputs[1])
    metallic_clamp = nodes.new(type="ShaderNodeClamp")
    metallic_clamp.location = (250, -40)
    metallic_clamp.inputs["Min"].default_value = 0.18
    metallic_clamp.inputs["Max"].default_value = 0.94
    links.new(metallic_math.outputs[0], metallic_clamp.inputs["Value"])
    links.new(metallic_clamp.outputs[0], principled.inputs["Metallic"])

    normal_tex = nodes.new(type="ShaderNodeTexImage")
    normal_tex.name = "NormalTexture"
    normal_tex.label = "NormalTexture"
    normal_tex.image = texture_assets["normal"]
    normal_tex.location = (-640, -250)
    links.new(mapping.outputs["Vector"], normal_tex.inputs["Vector"])
    reroute = nodes.new(type="NodeReroute")
    reroute.location = (-400, -250)
    links.new(normal_tex.outputs["Color"], reroute.inputs[0])
    normal_map = nodes.new(type="ShaderNodeNormalMap")
    normal_map.location = (-180, -250)
    normal_map.inputs["Strength"].default_value = 0.8
    links.new(reroute.outputs[0], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])

    emissive_tex = nodes.new(type="ShaderNodeTexImage")
    emissive_tex.name = "EmissiveTexture"
    emissive_tex.label = "EmissiveTexture"
    emissive_tex.image = texture_assets["emissive"]
    emissive_tex.location = (-640, -500)
    links.new(mapping.outputs["Vector"], emissive_tex.inputs["Vector"])
    emission_socket_name = "Emission Color" if "Emission Color" in principled.inputs else "Emission"
    links.new(emissive_tex.outputs["Color"], principled.inputs[emission_socket_name])

    occlusion_tex = nodes.new(type="ShaderNodeTexImage")
    occlusion_tex.name = "OcclusionTexture"
    occlusion_tex.label = "OcclusionTexture"
    occlusion_tex.image = texture_assets["occlusion"]
    occlusion_tex.location = (-640, -720)
    links.new(mapping.outputs["Vector"], occlusion_tex.inputs["Vector"])
    ao_strength = nodes.new(type="ShaderNodeValue")
    ao_strength.name = "AO_Strength"
    ao_strength.label = "AO_Strength"
    ao_strength.location = (-380, -720)
    ao_strength.outputs[0].default_value = 0.72


def _add_bevel_modifier(obj, *, width, segments):
    modifier = obj.modifiers.new(name="PreviewBevel", type="BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    return modifier


def _build_whopper_material(material, texture_assets):
    material.use_nodes = True
    node_tree = material.node_tree
    nodes = node_tree.nodes
    links = node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (1200, 100)
    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.location = (780, 120)
    principled.inputs["Metallic"].default_value = 0.82
    principled.inputs["Roughness"].default_value = 0.28
    principled.inputs["Emission Strength"].default_value = 0.35
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    texcoord = nodes.new(type="ShaderNodeTexCoord")
    texcoord.location = (-1160, 0)
    mapping = nodes.new(type="ShaderNodeMapping")
    mapping.location = (-930, 0)
    mapping.inputs["Scale"].default_value = (1.0, 1.0, 1.0)
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, 0.08)
    links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])

    base_tex = nodes.new(type="ShaderNodeTexImage")
    base_tex.name = "WhopperBaseTexture"
    base_tex.label = "WhopperBaseTexture"
    base_tex.image = texture_assets["base"]
    base_tex.location = (-900, 260)
    links.new(mapping.outputs["Vector"], base_tex.inputs["Vector"])

    color_ramp = nodes.new(type="ShaderNodeValToRGB")
    color_ramp.location = (-620, 260)
    color_ramp.color_ramp.elements[0].position = 0.12
    color_ramp.color_ramp.elements[0].color = (0.06, 0.03, 0.12, 1.0)
    color_ramp.color_ramp.elements[1].position = 0.88
    color_ramp.color_ramp.elements[1].color = (0.97, 0.58, 0.16, 1.0)
    links.new(base_tex.outputs["Color"], color_ramp.inputs["Fac"])

    tint = nodes.new(type="ShaderNodeRGB")
    tint.location = (-620, 440)
    tint.outputs[0].default_value = (0.2, 0.78, 1.0, 1.0)

    mix_rgb = nodes.new(type="ShaderNodeMixRGB")
    mix_rgb.location = (-360, 260)
    mix_rgb.inputs["Fac"].default_value = 0.18
    links.new(color_ramp.outputs["Color"], mix_rgb.inputs["Color1"])
    links.new(tint.outputs["Color"], mix_rgb.inputs["Color2"])
    links.new(mix_rgb.outputs["Color"], principled.inputs["Base Color"])

    orm_tex = nodes.new(type="ShaderNodeTexImage")
    orm_tex.name = "WhopperORMTexture"
    orm_tex.label = "WhopperORMTexture"
    orm_tex.image = texture_assets["orm"]
    orm_tex.location = (-900, -40)
    links.new(mapping.outputs["Vector"], orm_tex.inputs["Vector"])

    try:
        separate = nodes.new(type="ShaderNodeSeparateColor")
    except RuntimeError:
        separate = nodes.new(type="ShaderNodeSeparateRGB")
    separate.location = (-620, -40)
    links.new(orm_tex.outputs["Color"], separate.inputs.get("Color") or separate.inputs.get("Image"))
    green = separate.outputs.get("G") or separate.outputs.get("Green")
    blue = separate.outputs.get("B") or separate.outputs.get("Blue")

    rough_map = nodes.new(type="ShaderNodeMapRange")
    rough_map.location = (-360, -20)
    rough_map.inputs["From Min"].default_value = 0.0
    rough_map.inputs["From Max"].default_value = 1.0
    rough_map.inputs["To Min"].default_value = 0.08
    rough_map.inputs["To Max"].default_value = 0.68
    rough_map.clamp = True
    links.new(green, rough_map.inputs["Value"])

    rough_clamp = nodes.new(type="ShaderNodeClamp")
    rough_clamp.location = (-100, -20)
    rough_clamp.inputs["Min"].default_value = 0.08
    rough_clamp.inputs["Max"].default_value = 0.72
    links.new(rough_map.outputs[0], rough_clamp.inputs["Value"])
    links.new(rough_clamp.outputs[0], principled.inputs["Roughness"])

    metallic_math = nodes.new(type="ShaderNodeMath")
    metallic_math.location = (-360, -150)
    metallic_math.operation = "MULTIPLY"
    metallic_math.inputs[1].default_value = 0.92
    links.new(blue, metallic_math.inputs[0])

    metallic_clamp = nodes.new(type="ShaderNodeClamp")
    metallic_clamp.location = (-100, -150)
    metallic_clamp.inputs["Min"].default_value = 0.34
    metallic_clamp.inputs["Max"].default_value = 0.98
    links.new(metallic_math.outputs[0], metallic_clamp.inputs["Value"])
    links.new(metallic_clamp.outputs[0], principled.inputs["Metallic"])

    normal_tex = nodes.new(type="ShaderNodeTexImage")
    normal_tex.name = "WhopperNormalTexture"
    normal_tex.label = "WhopperNormalTexture"
    normal_tex.image = texture_assets["normal"]
    normal_tex.location = (-900, -320)
    links.new(mapping.outputs["Vector"], normal_tex.inputs["Vector"])

    normal_map = nodes.new(type="ShaderNodeNormalMap")
    normal_map.location = (-360, -320)
    normal_map.inputs["Strength"].default_value = 1.15
    links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])

    emissive_tex = nodes.new(type="ShaderNodeTexImage")
    emissive_tex.name = "WhopperEmissiveTexture"
    emissive_tex.label = "WhopperEmissiveTexture"
    emissive_tex.image = texture_assets["emissive"]
    emissive_tex.location = (-900, -560)
    links.new(mapping.outputs["Vector"], emissive_tex.inputs["Vector"])
    emission_socket_name = "Emission Color" if "Emission Color" in principled.inputs else "Emission"
    links.new(emissive_tex.outputs["Color"], principled.inputs[emission_socket_name])


def _build_whopper_scene():
    available_engines = {item.identifier for item in bpy.context.scene.render.bl_rna.properties["engine"].enum_items}
    if "BLENDER_EEVEE_NEXT" in available_engines:
        bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in available_engines:
        bpy.context.scene.render.engine = "BLENDER_EEVEE"

    texture_assets = _make_whopper_texture_assets()

    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=256,
        ring_count=160,
        radius=2.2,
        location=(0.0, 0.0, 2.6),
    )
    ellipsoid = bpy.context.active_object
    ellipsoid.name = "WhopperEllipsoid"
    ellipsoid.scale = (1.95, 1.35, 1.08)
    _add_bevel_modifier(ellipsoid, width=0.015, segments=2)
    subsurf = ellipsoid.modifiers.new(name="PreviewSubsurf", type="SUBSURF")
    subsurf.levels = 2
    subsurf.render_levels = 3
    bpy.ops.object.shade_smooth()

    material = bpy.data.materials.new(name="WhopperEllipsoidMat")
    _build_whopper_material(material, texture_assets)
    ellipsoid.data.materials.append(material)

    bpy.ops.mesh.primitive_torus_add(
        major_radius=4.3,
        minor_radius=0.12,
        location=(0.0, 0.0, 2.55),
        rotation=(math.radians(90.0), 0.0, 0.0),
    )
    ring = bpy.context.active_object
    ring.name = "WhopperOrbit"
    ring.data.materials.append(material)
    bpy.ops.object.shade_smooth()

    bpy.ops.mesh.primitive_plane_add(size=18.0, location=(0.0, 0.0, 0.0))
    ground = bpy.context.active_object
    ground.name = "WhopperGround"
    ground_mat = bpy.data.materials.new(name="WhopperGroundMat")
    ground_mat.use_nodes = True
    ground_principled = ground_mat.node_tree.nodes.get("Principled BSDF")
    if ground_principled is None:
        ground_principled = ground_mat.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    ground_principled.inputs["Base Color"].default_value = (0.03, 0.035, 0.055, 1.0)
    ground_principled.inputs["Roughness"].default_value = 0.96
    ground.data.materials.append(ground_mat)

    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 8.0, 8.0))
    backdrop = bpy.context.active_object
    backdrop.name = "WhopperBackdrop"
    backdrop.rotation_euler = (math.radians(78.0), 0.0, 0.0)
    backdrop_mat = bpy.data.materials.new(name="WhopperBackdropMat")
    backdrop_mat.use_nodes = True
    backdrop_principled = backdrop_mat.node_tree.nodes.get("Principled BSDF")
    if backdrop_principled is None:
        backdrop_principled = backdrop_mat.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    backdrop_principled.inputs["Base Color"].default_value = (0.05, 0.04, 0.09, 1.0)
    backdrop_principled.inputs["Roughness"].default_value = 0.92
    backdrop.data.materials.append(backdrop_mat)

    bpy.ops.object.light_add(type="SUN", location=(8.0, -10.0, 14.0))
    sun = bpy.context.active_object
    sun.name = "WhopperSun"
    sun.data.energy = 4.4

    bpy.ops.object.light_add(type="AREA", location=(-7.5, -4.5, 5.8))
    rim = bpy.context.active_object
    rim.name = "WhopperRim"
    rim.data.energy = 4800.0
    rim.data.color = (0.96, 0.48, 0.16)
    rim.rotation_euler = (math.radians(70.0), 0.0, math.radians(48.0))

    bpy.ops.object.light_add(type="AREA", location=(7.0, -6.5, 4.4))
    fill = bpy.context.active_object
    fill.name = "WhopperFill"
    fill.data.energy = 2200.0
    fill.data.color = (0.46, 0.7, 1.0)
    fill.rotation_euler = (math.radians(66.0), 0.0, math.radians(-52.0))

    world = bpy.context.scene.world
    if world is not None:
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background is not None:
            background.inputs["Color"].default_value = (0.008, 0.01, 0.018, 1.0)
            background.inputs["Strength"].default_value = 0.34

    bpy.ops.object.camera_add(location=(0.0, -18.5, 5.8), rotation=(1.28, 0.0, 0.0))
    camera = bpy.context.active_object
    camera.name = "WhopperCamera"
    camera.data.lens = 58
    bpy.context.scene.camera = camera

    for obj in bpy.context.scene.objects:
        obj.select_set(obj.type == "MESH")


def _build_demo_scene():
    available_engines = {item.identifier for item in bpy.context.scene.render.bl_rna.properties["engine"].enum_items}
    if "BLENDER_EEVEE_NEXT" in available_engines:
        bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in available_engines:
        bpy.context.scene.render.engine = "BLENDER_EEVEE"

    bpy.ops.mesh.primitive_monkey_add(size=1.0, location=(-1.5, 0.0, 0.7))
    cube = bpy.context.active_object
    cube.name = "InvestorCube"
    cube.rotation_euler = (0.18, -0.08, 0.42)
    _add_bevel_modifier(cube, width=0.04, segments=3)
    bpy.ops.object.shade_smooth()

    texture_assets = _make_texture_assets()
    material = bpy.data.materials.new(name="InvestorPBR")
    _build_hero_material(material, texture_assets)
    cube.data.materials.append(material)

    duplicate = cube.copy()
    duplicate.data = cube.data
    duplicate.name = "InvestorCubeInstance"
    duplicate.location = (1.5, 0.05, 0.72)
    duplicate.rotation_euler = (-0.12, 0.22, -0.34)
    bpy.context.collection.objects.link(duplicate)

    bpy.ops.mesh.primitive_cylinder_add(radius=0.75, depth=0.35, location=(-1.5, 0.0, 0.175))
    pedestal_left = bpy.context.active_object
    pedestal_left.name = "InvestorPedestalLeft"
    _add_bevel_modifier(pedestal_left, width=0.02, segments=2)
    bpy.ops.object.shade_smooth()

    bpy.ops.mesh.primitive_cylinder_add(radius=0.75, depth=0.35, location=(1.5, 0.0, 0.175))
    pedestal_right = bpy.context.active_object
    pedestal_right.name = "InvestorPedestalRight"
    _add_bevel_modifier(pedestal_right, width=0.02, segments=2)
    bpy.ops.object.shade_smooth()

    bpy.ops.mesh.primitive_torus_add(
        major_radius=2.6,
        minor_radius=0.08,
        location=(0.0, 0.0, 1.25),
        rotation=(math.radians(90.0), 0.0, 0.0),
    )
    ring = bpy.context.active_object
    ring.name = "InvestorRing"
    bpy.ops.object.shade_smooth()

    bpy.ops.mesh.primitive_torus_add(
        major_radius=1.95,
        minor_radius=0.06,
        location=(0.0, -0.2, 2.05),
        rotation=(math.radians(14.0), math.radians(22.0), math.radians(90.0)),
    )
    halo = bpy.context.active_object
    halo.name = "InvestorHalo"
    bpy.ops.object.shade_smooth()

    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(-3.2, 1.45, 1.7))
    fin_left = bpy.context.active_object
    fin_left.name = "InvestorFinLeft"
    fin_left.scale = (0.14, 1.6, 2.2)
    fin_left.rotation_euler = (0.0, math.radians(9.0), math.radians(18.0))
    _add_bevel_modifier(fin_left, width=0.01, segments=2)

    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(3.25, 1.2, 1.55))
    fin_right = bpy.context.active_object
    fin_right.name = "InvestorFinRight"
    fin_right.scale = (0.14, 1.35, 1.9)
    fin_right.rotation_euler = (0.0, math.radians(-11.0), math.radians(-14.0))
    _add_bevel_modifier(fin_right, width=0.01, segments=2)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 1.15, 0.12))
    bridge = bpy.context.active_object
    bridge.name = "InvestorBridge"
    bridge.scale = (2.25, 0.52, 0.12)
    _add_bevel_modifier(bridge, width=0.025, segments=2)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-2.55, -1.35, 0.42))
    plinth_left = bpy.context.active_object
    plinth_left.name = "InvestorPlinthLeft"
    plinth_left.scale = (0.62, 0.62, 0.42)
    plinth_left.rotation_euler = (0.0, 0.0, math.radians(18.0))
    _add_bevel_modifier(plinth_left, width=0.03, segments=2)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(2.7, -1.1, 0.36))
    plinth_right = bpy.context.active_object
    plinth_right.name = "InvestorPlinthRight"
    plinth_right.scale = (0.52, 0.52, 0.36)
    plinth_right.rotation_euler = (0.0, 0.0, math.radians(-15.0))
    _add_bevel_modifier(plinth_right, width=0.03, segments=2)

    bpy.ops.mesh.primitive_plane_add(size=6.0, location=(0.0, 0.0, 0.0))
    plane = bpy.context.active_object
    plane.name = "InvestorGround"

    ground_material = bpy.data.materials.new(name="GroundUnlit")
    ground_material.use_nodes = True
    ground_nodes = ground_material.node_tree.nodes
    ground_principled = ground_nodes.get("Principled BSDF")
    if ground_principled is None:
        ground_principled = ground_nodes.new(type="ShaderNodeBsdfPrincipled")
    ground_principled.inputs["Base Color"].default_value = (0.12, 0.14, 0.16, 1.0)
    ground_principled.inputs["Roughness"].default_value = 1.0
    plane.data.materials.append(ground_material)
    pedestal_left.data.materials.append(ground_material)
    pedestal_right.data.materials.append(ground_material)
    ring.data.materials.append(material)
    halo.data.materials.append(material)
    bridge.data.materials.append(ground_material)
    fin_left.data.materials.append(ground_material)
    fin_right.data.materials.append(ground_material)
    plinth_left.data.materials.append(ground_material)
    plinth_right.data.materials.append(ground_material)

    bpy.ops.mesh.primitive_plane_add(size=7.0, location=(0.0, 2.8, 2.6))
    backdrop = bpy.context.active_object
    backdrop.name = "InvestorBackdrop"
    backdrop.rotation_euler = (math.radians(72.0), 0.0, 0.0)
    backdrop_material = bpy.data.materials.new(name="BackdropWarm")
    backdrop_material.use_nodes = True
    backdrop_principled = backdrop_material.node_tree.nodes.get("Principled BSDF")
    if backdrop_principled is None:
        backdrop_principled = backdrop_material.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    backdrop_principled.inputs["Base Color"].default_value = (0.56, 0.31, 0.18, 1.0)
    backdrop_principled.inputs["Roughness"].default_value = 0.92
    backdrop.data.materials.append(backdrop_material)

    bpy.ops.mesh.primitive_plane_add(size=4.8, location=(-3.15, 2.05, 1.95))
    wing_left = bpy.context.active_object
    wing_left.name = "InvestorWingLeft"
    wing_left.rotation_euler = (math.radians(73.0), math.radians(0.0), math.radians(18.0))
    wing_left.data.materials.append(backdrop_material)

    bpy.ops.mesh.primitive_plane_add(size=4.4, location=(3.25, 1.95, 1.75))
    wing_right = bpy.context.active_object
    wing_right.name = "InvestorWingRight"
    wing_right.rotation_euler = (math.radians(72.0), math.radians(0.0), math.radians(-16.0))
    wing_right.data.materials.append(backdrop_material)

    fin_left.data.materials.clear()
    fin_left.data.materials.append(backdrop_material)
    fin_right.data.materials.clear()
    fin_right.data.materials.append(backdrop_material)

    bpy.ops.object.light_add(type="SUN", location=(3.0, -3.0, 5.0))
    light = bpy.context.active_object
    light.name = "InvestorSun"
    light.data.energy = 3.4

    bpy.ops.object.light_add(type="AREA", location=(-4.2, -2.0, 3.0))
    rim = bpy.context.active_object
    rim.name = "InvestorRim"
    rim.data.energy = 3000.0
    rim.data.color = (0.98, 0.64, 0.42)
    rim.rotation_euler = (math.radians(72.0), 0.0, math.radians(48.0))

    bpy.ops.object.light_add(type="AREA", location=(3.8, -3.8, 2.8))
    fill = bpy.context.active_object
    fill.name = "InvestorFill"
    fill.data.energy = 1600.0
    fill.data.color = (0.74, 0.84, 1.0)
    fill.rotation_euler = (math.radians(70.0), 0.0, math.radians(-52.0))

    bpy.ops.object.light_add(type="SPOT", location=(0.0, -3.1, 4.8))
    key_spot = bpy.context.active_object
    key_spot.name = "InvestorSpot"
    key_spot.data.energy = 2200.0
    key_spot.data.spot_size = math.radians(42.0)
    key_spot.data.spot_blend = 0.45
    key_spot.data.color = (1.0, 0.93, 0.86)
    key_spot.rotation_euler = (math.radians(62.0), 0.0, 0.0)

    world = bpy.context.scene.world
    if world is not None:
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background is not None:
            background.inputs["Color"].default_value = (0.021, 0.026, 0.038, 1.0)
            background.inputs["Strength"].default_value = 0.65

    bpy.ops.object.camera_add(location=(0.0, -10.8, 4.35), rotation=(1.14, 0.0, 0.0))
    camera = bpy.context.active_object
    camera.name = "InvestorCamera"
    bpy.context.scene.camera = camera
    camera.data.lens = 52

    for obj in bpy.context.scene.objects:
        obj.select_set(obj.type == "MESH")


def _build_alt_demo_scene():
    available_engines = {item.identifier for item in bpy.context.scene.render.bl_rna.properties["engine"].enum_items}
    if "BLENDER_EEVEE_NEXT" in available_engines:
        bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in available_engines:
        bpy.context.scene.render.engine = "BLENDER_EEVEE"

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.85, location=(-0.9, 0.0, 0.85))
    sphere = bpy.context.active_object
    sphere.name = "InvestorSphere"

    sphere_material = bpy.data.materials.new(name="InvestorBlue")
    sphere_material.use_nodes = True
    sphere_principled = sphere_material.node_tree.nodes.get("Principled BSDF")
    if sphere_principled is None:
        sphere_principled = sphere_material.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    sphere_principled.inputs["Base Color"].default_value = (0.12, 0.42, 0.88, 1.0)
    sphere_principled.inputs["Metallic"].default_value = 0.1
    sphere_principled.inputs["Roughness"].default_value = 0.3
    sphere.data.materials.append(sphere_material)

    bpy.ops.mesh.primitive_cylinder_add(radius=0.45, depth=2.2, location=(1.2, 0.0, 1.1))
    column = bpy.context.active_object
    column.name = "InvestorColumn"
    column.rotation_euler = (0.0, 0.0, math.radians(8.0))

    column_material = bpy.data.materials.new(name="InvestorCopper")
    column_material.use_nodes = True
    column_principled = column_material.node_tree.nodes.get("Principled BSDF")
    if column_principled is None:
        column_principled = column_material.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    column_principled.inputs["Base Color"].default_value = (0.74, 0.38, 0.18, 1.0)
    column_principled.inputs["Metallic"].default_value = 0.8
    column_principled.inputs["Roughness"].default_value = 0.25
    column.data.materials.append(column_material)

    bpy.ops.mesh.primitive_plane_add(size=5.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    floor.name = "InvestorAltGround"
    floor_material = bpy.data.materials.new(name="InvestorAltGroundMat")
    floor_material.use_nodes = True
    floor_principled = floor_material.node_tree.nodes.get("Principled BSDF")
    if floor_principled is None:
        floor_principled = floor_material.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    floor_principled.inputs["Base Color"].default_value = (0.08, 0.09, 0.11, 1.0)
    floor_principled.inputs["Roughness"].default_value = 1.0
    floor.data.materials.append(floor_material)

    bpy.ops.mesh.primitive_plane_add(size=4.0, location=(0.0, 1.8, 1.9))
    wall = bpy.context.active_object
    wall.name = "InvestorAltWall"
    wall.rotation_euler = (math.radians(78.0), 0.0, 0.0)
    wall.data.materials.append(floor_material)

    for obj in bpy.context.scene.objects:
        obj.select_set(obj.type == "MESH")


def _copy_xite_runtime():
    runtime_src = REPO_ROOT / "x_ite-main" / "dist"
    runtime_dst = DEMO_DIR / "x_ite"
    if runtime_dst.exists():
        shutil.rmtree(runtime_dst)
    shutil.copytree(runtime_src, runtime_dst)


def _export_glb(filepath: Path):
    enabled, loaded = addon_utils.check("io_scene_gltf2")
    if not (enabled and loaded):
        try:
            addon_utils.enable("io_scene_gltf2", default_set=False, persistent=False)
        except Exception:
            return False

    gltf_op = getattr(bpy.ops.export_scene, "gltf", None)
    if gltf_op is None:
        return False

    result = gltf_op(
        filepath=str(filepath),
        export_format="GLB",
        use_selection=True,
        export_apply=False,
    )
    return "FINISHED" in result


def _write_inline_x3d():
    inline_x3d = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D version="4.0" profile="Immersive">
  <head>
    <meta name="title" content="Blender glTF Inline PoC" />
    <meta name="creator" content="OpenAI Codex" />
  </head>
  <Scene>
    <WorldInfo title="Blender glTF Inline PoC" info='"Blender-exported GLB loaded through X3D Inline in X_ITE."' />
    <NavigationInfo type='"EXAMINE" "ANY"' />
    <Viewpoint description="Investor View" position="0 -7 4" orientation="1 0 0 0.75" />
    <Transform translation="2 1 0.5" rotation="0 1 0 0.6" scale="1.25 1.25 1.25">
      <Inline url='"blender_scene.glb"' />
    </Transform>
  </Scene>
</X3D>
"""
    OUTPUT_INLINE_X3D.write_text(inline_x3d, encoding="utf-8")

    multi_inline_x3d = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D version="4.0" profile="Immersive">
  <head>
    <meta name="title" content="Blender glTF Multi Inline PoC" />
    <meta name="creator" content="OpenAI Codex" />
    <meta name="description" content="Two Blender-exported GLB instances loaded through X3D Inline with independent transforms." />
  </head>
  <Scene>
    <WorldInfo title="Blender glTF Multi Inline PoC" info='"Two distinct GLB Inline instances composed in one X3D wrapper scene."' />
    <NavigationInfo type='"EXAMINE" "ANY"' />
    <Viewpoint description="Wide Investor View" position="0 -14 7" orientation="1 0 0 0.75" fieldOfView="0.9" />
    <Transform translation="-4 0 0" rotation="0 1 0 0.3" scale="1 1 1">
      <Inline url='"blender_scene.glb"' />
    </Transform>
    <Transform translation="4 0 0" rotation="0 1 0 -0.35" scale="0.8 0.8 0.8">
      <Inline url='"blender_scene_alt.glb"' />
    </Transform>
  </Scene>
</X3D>
"""
    OUTPUT_MULTI_INLINE_X3D.write_text(multi_inline_x3d, encoding="utf-8")

    whopper_inline_x3d = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D version="4.0" profile="Immersive">
  <head>
    <meta name="title" content="Blender Whopper Ellipsoid PoC" />
    <meta name="creator" content="OpenAI Codex" />
    <meta name="description" content="A deliberately oversized Blender-exported GLB wrapped through X3D Inline for X_ITE presentation." />
  </head>
  <Scene>
    <WorldInfo title="Blender Whopper Ellipsoid PoC" info='"Large GLB ellipsoid showcase loaded through X3D Inline in X_ITE."' />
    <NavigationInfo type='"EXAMINE" "ANY"' />
    <Viewpoint description="Whopper View" position="0 -15 6" orientation="1 0 0 0.95" fieldOfView="0.72" />
    <Transform translation="0 0 0" rotation="0 1 0 0.42" scale="1 1 1">
      <Inline url='"blender_whopper_ellipsoid.glb"' />
    </Transform>
  </Scene>
</X3D>
"""
    OUTPUT_WHOPPER_INLINE_X3D.write_text(whopper_inline_x3d, encoding="utf-8")


def _viewer_shell(*, title: str, eyebrow: str, heading: str, body: str, scene_src: str) -> str:
    template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <link rel="stylesheet" href="./x_ite/x_ite.css" />
  <style>
    :root {
      --bg: #f4eadb;
      --bg-deep: #e4d4bd;
      --panel: rgba(255, 249, 241, 0.82);
      --panel-strong: rgba(255, 252, 247, 0.94);
      --ink: #1f1a15;
      --muted: #65584d;
      --accent: #b94f1c;
      --accent-dark: #7e3412;
      --line: rgba(31, 26, 21, 0.11);
      --shadow: 0 30px 90px rgba(87, 59, 34, 0.12);
    }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top, rgba(185, 79, 28, 0.18), transparent 24%),
        radial-gradient(circle at 80% 18%, rgba(0, 0, 0, 0.05), transparent 22%),
        linear-gradient(180deg, #faf3e8 0%, var(--bg) 48%, var(--bg-deep) 100%);
    }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 420px) 1fr;
      gap: 20px;
      min-height: 100vh;
      padding: 24px;
      box-sizing: border-box;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 24px;
      backdrop-filter: blur(14px);
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }
    .panel::after {
      content: "";
      position: absolute;
      inset: auto -12% -32% auto;
      width: 280px;
      height: 280px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(185, 79, 28, 0.16), transparent 68%);
      pointer-events: none;
    }
    h1 {
      margin: 0 0 12px;
      font-size: clamp(2rem, 4vw, 3.4rem);
      line-height: 0.98;
      letter-spacing: -0.04em;
    }
    p, li {
      line-height: 1.62;
    }
    .eyebrow {
      margin: 0 0 8px;
      color: var(--accent);
      font-weight: 700;
      letter-spacing: 0.11em;
      text-transform: uppercase;
      font-size: 0.78rem;
    }
    .viewer-note {
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 18px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.94rem;
    }
    x3d-canvas {
      width: 100%;
      height: calc(100vh - 48px);
      border-radius: 30px;
      overflow: hidden;
      background: linear-gradient(180deg, #f8f1e6 0%, #dcd2c2 100%);
      border: 1px solid rgba(31, 29, 26, 0.1);
      box-shadow: 0 34px 90px rgba(58, 45, 31, 0.2);
    }
    code {
      font-family: "IBM Plex Mono", "Consolas", monospace;
      font-size: 0.92em;
    }
    ul {
      padding-left: 1.1rem;
      margin: 0;
    }
    a {
      color: inherit;
    }
    .back-link {
      display: inline-flex;
      margin-top: 18px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid var(--line);
      text-decoration: none;
      font-weight: 700;
    }
    @media (max-width: 960px) {
      main {
        grid-template-columns: 1fr;
      }
      x3d-canvas {
        height: 68vh;
      }
    }
  </style>
  <script type="module" src="./x_ite/x_ite.mjs"></script>
</head>
<body>
  <main>
    <section class="panel">
      <p class="eyebrow">__EYEBROW__</p>
      <h1>__HEADING__</h1>
      __BODY__
      <div class="viewer-note">This page is part of the deployable technical-preview bundle and is intended to be embedded or opened directly during review.</div>
      <a class="back-link" href="./index.html">Back to preview dashboard</a>
    </section>
    <x3d-canvas src="__SCENE_SRC__" contentScale="auto" update="auto"></x3d-canvas>
  </main>
</body>
</html>
"""
    return (
        template
        .replace("__TITLE__", title)
        .replace("__EYEBROW__", eyebrow)
        .replace("__HEADING__", heading)
        .replace("__BODY__", body)
        .replace("__SCENE_SRC__", scene_src)
    )


def _write_viewers(glb_available: bool):
    LANDING_HTML.write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Blender X3D Investor PoC</title>
  <style>
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top, rgba(184, 79, 29, 0.16), transparent 26%),
        linear-gradient(180deg, #faf5ec 0%, #ece5d9 100%);
      color: #1f1d1a;
    }
    main {
      max-width: 1040px;
      margin: 0 auto;
      padding: 40px 24px 56px;
    }
    h1 {
      font-size: 3rem;
      line-height: 0.95;
      margin: 0 0 12px;
    }
    p {
      line-height: 1.6;
      max-width: 760px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 18px;
      margin-top: 28px;
    }
    .card {
      border-radius: 20px;
      padding: 22px;
      background: rgba(255, 252, 247, 0.84);
      border: 1px solid rgba(31, 29, 26, 0.1);
      box-shadow: 0 24px 80px rgba(70, 52, 34, 0.08);
    }
    .card a {
      color: #b84f1d;
      font-weight: 700;
      text-decoration: none;
    }
  </style>
</head>
<body>
  <main>
    <h1>Blender to X3D 4.0 to X_ITE</h1>
    <p>This proof package contains direct modern X3D export, multiple Blender-generated GLB interoperability scenes, and one deliberately oversized ellipsoid showcase asset for stress-testing the static preview path.</p>
    <div class="grid">
      <article class="card">
        <h2>Direct Modern X3D</h2>
        <p>Principled material analysis, <code>PhysicalMaterial</code>, reusable geometry, and shared appearances from the upgraded exporter.</p>
        <p><a href="./direct_x3d.html">Open direct X3D viewer</a></p>
      </article>
      <article class="card">
        <h2>glTF Inline in X_ITE</h2>
        <p>Blender exports a GLB, then X3D <code>Inline</code> loads it in X_ITE. This proves the browser-side interoperability target.</p>
        <p><a href="./gltf_inline.html">Open glTF Inline viewer</a></p>
      </article>
      <article class="card">
        <h2>Multi Inline Composition</h2>
        <p>The same GLB is instanced twice through separate X3D <code>Inline</code> nodes, each with independent transforms and one authored wide camera.</p>
        <p><a href="./gltf_multi_inline.html">Open multi-inline viewer</a></p>
      </article>
      <article class="card">
        <h2>Whopper Ellipsoid GLB</h2>
        <p>A deliberately oversized, richly textured ellipsoid exported as a standalone GLB and wrapped through X3D <code>Inline</code> for a heavyweight runtime showcase.</p>
        <p><a href="./whopper_glb.html">Open whopper viewer</a></p>
      </article>
    </div>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )

    DIRECT_VIEWER_HTML.write_text(
        _viewer_shell(
            title="Blender Modern X3D PoC",
            eyebrow="Investor PoC",
            heading="Direct Modern X3D Export",
            body="""
      <p>This scene was exported from Blender through the upgraded <code>io_scene_x3d</code> modern path and loaded directly by X_ITE.</p>
      <ul>
        <li>X3D 4.0 document structure</li>
        <li>PhysicalMaterial emission from Principled BSDF</li>
        <li>Shared mesh geometry with DEF/USE reuse</li>
        <li>Two Blender instances referencing one exported geometry source</li>
      </ul>
      <p>Source asset: <code>blender_modern_poc.x3d</code></p>
""",
            scene_src="./blender_modern_poc.x3d",
        ),
        encoding="utf-8",
    )

    inline_body = """
      <p>This scene demonstrates the companion interoperability story: Blender exports a GLB, an X3D wrapper references it through <code>Inline</code>, and X_ITE is the runtime that resolves it.</p>
      <ul>
        <li>Blender source scene exported as <code>blender_scene.glb</code></li>
        <li>X3D wrapper document: <code>xite_gltf_inline_poc.x3d</code></li>
        <li>Runtime target: X_ITE <code>Inline</code> + glTF loading</li>
      </ul>
"""
    if not glb_available:
        inline_body += """
      <p><strong>Note:</strong> the local Blender build did not expose the glTF exporter addon, so this page is generated but the GLB artifact was not produced in this run.</p>
"""

    INLINE_VIEWER_HTML.write_text(
        _viewer_shell(
            title="Blender glTF Inline PoC",
            eyebrow="Interop PoC",
            heading="glTF Inline Through X3D",
            body=inline_body,
            scene_src="./xite_gltf_inline_poc.x3d",
        ),
        encoding="utf-8",
    )

    MULTI_INLINE_VIEWER_HTML.write_text(
        _viewer_shell(
            title="Blender glTF Multi Inline PoC",
            eyebrow="Composition PoC",
            heading="Multiple glTF Inline Assets",
            body="""
      <p>This scene composes two separate <code>Inline</code> references to two distinct Blender-generated GLB assets, each with independent X3D transforms and a wider authored camera.</p>
      <ul>
        <li>two different GLB assets in one wrapper scene</li>
        <li>independent translation, rotation, and scale per asset</li>
        <li>single X3D-authored overview camera</li>
      </ul>
      <p>Source asset: <code>xite_gltf_multi_inline_poc.x3d</code></p>
""",
            scene_src="./xite_gltf_multi_inline_poc.x3d",
        ),
        encoding="utf-8",
    )

    WHOPPER_VIEWER_HTML.write_text(
        _viewer_shell(
            title="Blender Whopper Ellipsoid PoC",
            eyebrow="Heavyweight GLB",
            heading="Whopper Ellipsoid Showcase",
            body="""
      <p>This scene is the deliberately oversized asset in the preview bundle: a high-detail Blender-exported GLB centered on a richly textured ellipsoid with a cinematic presentation wrapper.</p>
      <ul>
        <li>large standalone GLB payload</li>
        <li>high-resolution UV texture set</li>
        <li>ellipsoid mesh with heavier geometry density</li>
        <li>X3D <code>Inline</code> runtime presentation through X_ITE</li>
      </ul>
      <p>Source assets: <code>blender_whopper_ellipsoid.glb</code> and <code>xite_whopper_inline_poc.x3d</code></p>
""",
            scene_src="./xite_whopper_inline_poc.x3d",
        ),
        encoding="utf-8",
    )


def _write_manifest(glb_available: bool):
    direct_x3d_text = OUTPUT_X3D.read_text(encoding="utf-8") if OUTPUT_X3D.exists() else ""
    manifest = {
        "title": "Blender X3D Investor PoC",
        "generated_by": "io_scene_x3d/tools/blender_modern_export_demo.py",
        "artifacts": {
            "direct_x3d": OUTPUT_X3D.name,
            "glb": OUTPUT_GLB.name if glb_available else None,
            "glb_alt": OUTPUT_GLB_ALT.name if glb_available else None,
            "glb_whopper": OUTPUT_GLB_WHOPPER.name if glb_available else None,
            "inline_x3d": OUTPUT_INLINE_X3D.name,
            "multi_inline_x3d": OUTPUT_MULTI_INLINE_X3D.name,
            "whopper_inline_x3d": OUTPUT_WHOPPER_INLINE_X3D.name,
            "landing_page": LANDING_HTML.name,
            "direct_viewer": DIRECT_VIEWER_HTML.name,
            "inline_viewer": INLINE_VIEWER_HTML.name,
            "multi_inline_viewer": MULTI_INLINE_VIEWER_HTML.name,
            "whopper_viewer": WHOPPER_VIEWER_HTML.name,
        },
        "proof_points": [
            "Blender modern exporter emits X3D 4.0 with PhysicalMaterial",
            "Blender GLB export is available for interoperability",
            "X3D Inline can reference Blender-generated GLB assets for X_ITE runtime loading",
            "Multi-inline composition demonstrates heterogeneous asset reuse with independent transforms",
            "A heavyweight ellipsoid GLB demonstrates the preview pipeline on a larger textured asset",
            "Modern importer can materialize inline assets, viewpoints, and navigation metadata back into Blender",
        ],
        "scenes": [
            {
                "name": "direct_modern_x3d",
                "file": OUTPUT_X3D.name,
                "viewer": DIRECT_VIEWER_HTML.name,
                "expected": {
                    "x3d_version": "4.0",
                    "shared_geometry": True,
                    "physical_material": True,
                    "texture_fields": {
                        "baseTexture": 'containerField="baseTexture"' in direct_x3d_text,
                        "metallicRoughnessTexture": 'containerField="metallicRoughnessTexture"' in direct_x3d_text,
                        "normalTexture": 'containerField="normalTexture"' in direct_x3d_text,
                        "emissiveTexture": 'containerField="emissiveTexture"' in direct_x3d_text,
                        "occlusionTexture": 'containerField="occlusionTexture"' in direct_x3d_text,
                    },
                },
            },
            {
                "name": "single_inline",
                "file": OUTPUT_INLINE_X3D.name,
                "viewer": INLINE_VIEWER_HTML.name,
                "expected": {
                    "inline_assets": 1,
                    "viewpoints": 1,
                    "navigation_types": ["EXAMINE", "ANY"],
                },
            },
            {
                "name": "multi_inline",
                "file": OUTPUT_MULTI_INLINE_X3D.name,
                "viewer": MULTI_INLINE_VIEWER_HTML.name,
                "expected": {
                    "inline_assets": 2,
                    "asset_files": [OUTPUT_GLB.name, OUTPUT_GLB_ALT.name],
                    "viewpoints": 1,
                    "navigation_types": ["EXAMINE", "ANY"],
                },
            },
            {
                "name": "whopper_ellipsoid",
                "file": OUTPUT_WHOPPER_INLINE_X3D.name,
                "viewer": WHOPPER_VIEWER_HTML.name,
                "expected": {
                    "inline_assets": 1,
                    "asset_files": [OUTPUT_GLB_WHOPPER.name],
                    "viewpoints": 1,
                    "navigation_types": ["EXAMINE", "ANY"],
                },
            },
        ],
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main():
    os.environ["BLENDER_X3D_EXPORT_TARGET"] = "MODERN_SCAFFOLD"
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    _load_addon_package()
    _reset_scene()
    _build_demo_scene()

    from io_scene_x3d import export_x3d

    export_x3d.save(
        bpy.context,
        filepath=str(OUTPUT_X3D),
        use_selection=True,
        use_visible=False,
        use_mesh_modifiers=False,
        use_triangulate=False,
        use_normals=False,
        use_compress=False,
        use_hierarchy=True,
        use_h3d=False,
        batch_mode="OFF",
        use_batch_own_dir=False,
        meta_creator="OpenAI Codex",
        meta_title="Blender Modern X3D PoC",
        meta_description="Headless Blender export through the modern io_scene_x3d scaffold path.",
        meta_reference="x_ite-main dist viewer",
        meta_license="Demo only",
    )

    glb_available = _export_glb(OUTPUT_GLB)
    if glb_available:
        _reset_scene()
        _build_alt_demo_scene()
        glb_available = _export_glb(OUTPUT_GLB_ALT)
    if glb_available:
        _reset_scene()
        _build_whopper_scene()
        glb_available = _export_glb(OUTPUT_GLB_WHOPPER)
    _write_inline_x3d()
    _copy_xite_runtime()
    _write_viewers(glb_available)
    _write_manifest(glb_available)
    print(f"Wrote X3D demo to {OUTPUT_X3D}")
    if glb_available:
        print(f"Wrote GLB demo to {OUTPUT_GLB}")
        print(f"Wrote alternate GLB demo to {OUTPUT_GLB_ALT}")
        print(f"Wrote whopper GLB demo to {OUTPUT_GLB_WHOPPER}")
    else:
        print("GLB demo export skipped; io_scene_gltf2 unavailable in this Blender runtime.")
    print(f"Wrote Inline X3D demo to {OUTPUT_INLINE_X3D}")
    print(f"Wrote multi Inline X3D demo to {OUTPUT_MULTI_INLINE_X3D}")
    print(f"Wrote whopper Inline X3D demo to {OUTPUT_WHOPPER_INLINE_X3D}")
    print(f"Wrote manifest to {OUTPUT_MANIFEST}")
    print(f"Wrote landing page to {LANDING_HTML}")


if __name__ == "__main__":
    main()
