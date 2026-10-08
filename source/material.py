# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging

try:
    from .ir import IRPBRMaterial, IRTextureRef, IRTextureTransform
except ImportError:  # pragma: no cover - standalone test fallback
    from ir import IRPBRMaterial, IRTextureRef, IRTextureTransform

logger = logging.getLogger("export_x3d.material")


class ShaderNodeTypes:
    MATERIAL_OUTPUT = "ShaderNodeOutputMaterial"
    BSDF_PRINCIPLED = "ShaderNodeBsdfPrincipled"
    IMAGE_TEXTURE = "ShaderNodeTexImage"
    EMISSION = "ShaderNodeEmission"
    DIFFUSE_BSDF = "ShaderNodeBsdfDiffuse"
    MAPPING = "ShaderNodeMapping"
    MIX_SHADER = "ShaderNodeMixShader"
    MIX_RGB = "ShaderNodeMixRGB"
    RGB = "ShaderNodeRGB"
    MATH = "ShaderNodeMath"
    CLAMP = "ShaderNodeClamp"
    MAP_RANGE = "ShaderNodeMapRange"
    NORMAL_MAP = "ShaderNodeNormalMap"
    SEPARATE_COLOR = "ShaderNodeSeparateColor"
    SEPARATE_RGB = "ShaderNodeSeparateRGB"
    GROUP = "ShaderNodeGroup"
    VALUE = "ShaderNodeValue"
    REROUTE = "NodeReroute"


def _iter_input_links(node):
    for input_socket in getattr(node, "inputs", []):
        for link in getattr(input_socket, "links", []):
            yield input_socket, link


def _find_active_output(material):
    node_tree = getattr(material, "node_tree", None)
    if not node_tree:
        return None
    for node in node_tree.nodes:
        if node.bl_idname == ShaderNodeTypes.MATERIAL_OUTPUT and getattr(node, "is_active_output", False):
            return node
    for node in node_tree.nodes:
        if node.bl_idname == ShaderNodeTypes.MATERIAL_OUTPUT:
            return node
    return None


def _linked_surface_node(material):
    output = _find_active_output(material)
    if not output:
        return None
    surface_socket = output.inputs.get("Surface")
    if not surface_socket or not surface_socket.links:
        return None
    return surface_socket.links[0].from_node


def _node_default_rgba(node, socket_name, fallback):
    socket = node.inputs.get(socket_name) if node else None
    if socket is None or not hasattr(socket, "default_value"):
        return fallback
    default_value = socket.default_value
    if len(default_value) >= 4:
        return tuple(default_value[:4])
    if len(default_value) == 3:
        return tuple(default_value[:3]) + (1.0,)
    return fallback


def _node_default_float(node, socket_name, fallback):
    socket = node.inputs.get(socket_name) if node else None
    if socket is None or not hasattr(socket, "default_value"):
        return fallback
    return float(socket.default_value)


def _upstream_node(socket):
    if socket is None or not socket.links:
        return None
    return socket.links[0].from_node


def _recursive_find_node_by_idname(node_tree, idname):
    if not node_tree or not hasattr(node_tree, "nodes"):
        return None
    for node in node_tree.nodes:
        if node.bl_idname == idname:
            return node
        if node.bl_idname == ShaderNodeTypes.GROUP and getattr(node, "node_tree", None):
            found = _recursive_find_node_by_idname(node.node_tree, idname)
            if found:
                return found
    return None


def _recursive_find_nodes_by_idname(node_tree, idname, results=None):
    if results is None:
        results = []
    if not node_tree or not hasattr(node_tree, "nodes"):
        return results
    for node in node_tree.nodes:
        if node.bl_idname == idname:
            results.append(node)
        if node.bl_idname == ShaderNodeTypes.GROUP and getattr(node, "node_tree", None):
            _recursive_find_nodes_by_idname(node.node_tree, idname, results)
    return results


def _find_labeled_image_node(material, keywords):
    node_tree = getattr(material, "node_tree", None)
    image_nodes = _recursive_find_nodes_by_idname(node_tree, ShaderNodeTypes.IMAGE_TEXTURE, results=[])
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for node in image_nodes:
        haystack = " ".join(
            filter(
                None,
                (
                    getattr(node, "name", ""),
                    getattr(node, "label", ""),
                    getattr(getattr(node, "image", None), "name", ""),
                    getattr(getattr(node, "image", None), "filepath", ""),
                ),
            )
        ).lower()
        if any(keyword in haystack for keyword in lowered_keywords):
            return node
    return None


def _find_labeled_value_node(material, keywords):
    node_tree = getattr(material, "node_tree", None)
    value_nodes = _recursive_find_nodes_by_idname(node_tree, ShaderNodeTypes.VALUE, results=[])
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for node in value_nodes:
        haystack = " ".join(filter(None, (getattr(node, "name", ""), getattr(node, "label", "")))).lower()
        if any(keyword in haystack for keyword in lowered_keywords):
            return node
    return None


def _find_mapping_node(image_texture):
    if not image_texture:
        return None
    for input_socket, link in _iter_input_links(image_texture):
        del input_socket
        if link.from_node.bl_idname == ShaderNodeTypes.MAPPING:
            return link.from_node
    vector_socket = image_texture.inputs.get("Vector")
    candidate = _upstream_node(vector_socket)
    if candidate and candidate.bl_idname == ShaderNodeTypes.MAPPING:
        return candidate
    return None


def _texture_transform_from_mapping(mapping_node):
    if not mapping_node:
        return None
    rotation = mapping_node.inputs["Rotation"].default_value[:3] if "Rotation" in mapping_node.inputs else (0.0, 0.0, 0.0)
    scale = mapping_node.inputs["Scale"].default_value[:3] if "Scale" in mapping_node.inputs else (1.0, 1.0, 1.0)
    translation = mapping_node.inputs["Location"].default_value[:3] if "Location" in mapping_node.inputs else (0.0, 0.0, 0.0)
    return IRTextureTransform(
        translation=(float(translation[0]), float(translation[1])),
        rotation=float(rotation[2]),
        scale=(float(scale[0]), float(scale[1])),
        texcoord_set=0,
    )


def _texture_ref_from_image_node(image_node, usage):
    if not image_node or not getattr(image_node, "image", None):
        return None
    image = image_node.image
    colorspace = None
    if hasattr(image_node, "image") and hasattr(image_node, "color_space"):
        colorspace = getattr(image_node, "color_space", None)
    elif hasattr(image_node, "image") and hasattr(image_node, "colorspace_settings"):
        colorspace = getattr(image_node.colorspace_settings, "name", None)
    elif hasattr(image, "colorspace_settings"):
        colorspace = getattr(image.colorspace_settings, "name", None)
    return IRTextureRef(
        image_name=image.name,
        filepath=image.filepath,
        source=image.source,
        colorspace=colorspace,
        extension=getattr(image_node, "extension", None),
        transform=_texture_transform_from_mapping(_find_mapping_node(image_node)),
        usage=usage,
    )


def _socket_default_value(socket, fallback):
    if socket is None or not hasattr(socket, "default_value"):
        return fallback
    default_value = socket.default_value
    try:
        if len(default_value) >= 4:
            return tuple(default_value[:4])
        if len(default_value) == 3:
            return tuple(default_value[:3]) + (1.0,)
    except TypeError:
        pass
    return default_value


def _socket_numeric_value(socket, fallback):
    if socket is None or not hasattr(socket, "default_value"):
        return fallback
    try:
        return float(socket.default_value)
    except (TypeError, ValueError):
        return fallback


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def _resolve_rgba_socket(socket, fallback, visited=None):
    if socket is None:
        return fallback
    if visited is None:
        visited = set()

    default_value = _socket_default_value(socket, fallback)
    if not getattr(socket, "links", None):
        if isinstance(default_value, tuple):
            return default_value
        return fallback

    link = socket.links[0]
    node = link.from_node
    node_id = id(node)
    if node_id in visited:
        return fallback
    visited.add(node_id)

    if node.bl_idname == ShaderNodeTypes.RGB:
        output = getattr(node, "outputs", [None])[0]
        return _socket_default_value(output, fallback)

    if node.bl_idname == ShaderNodeTypes.MIX_RGB:
        fac = _resolve_float_socket(node.inputs.get("Fac"), 0.5, visited=visited.copy())
        color1 = _resolve_rgba_socket(node.inputs.get("Color1"), fallback, visited=visited.copy())
        color2 = _resolve_rgba_socket(node.inputs.get("Color2"), fallback, visited=visited.copy())
        fac = _clamp01(fac)
        return tuple(((1.0 - fac) * color1[index]) + (fac * color2[index]) for index in range(4))

    if node.bl_idname == ShaderNodeTypes.REROUTE and node.inputs:
        return _resolve_rgba_socket(node.inputs[0], fallback, visited=visited)

    if node.bl_idname == ShaderNodeTypes.IMAGE_TEXTURE:
        return fallback

    for input_socket, _ in _iter_input_links(node):
        resolved = _resolve_rgba_socket(input_socket, fallback, visited=visited.copy())
        if resolved != fallback:
            return resolved

    return fallback


def _resolve_float_socket(socket, fallback, visited=None):
    if socket is None:
        return fallback
    if visited is None:
        visited = set()

    if not getattr(socket, "links", None):
        return _socket_numeric_value(socket, fallback)

    link = socket.links[0]
    node = link.from_node
    node_id = id(node)
    if node_id in visited:
        return fallback
    visited.add(node_id)

    if node.bl_idname == ShaderNodeTypes.VALUE:
        output = getattr(node, "outputs", [None])[0]
        return _socket_numeric_value(output, fallback)

    if node.bl_idname == ShaderNodeTypes.REROUTE and node.inputs:
        return _resolve_float_socket(node.inputs[0], fallback, visited=visited)

    if node.bl_idname == ShaderNodeTypes.MATH:
        operation = getattr(node, "operation", "")
        a = _resolve_float_socket(node.inputs[0], _socket_numeric_value(node.inputs[0], fallback), visited=visited.copy())
        b = _resolve_float_socket(node.inputs[1], _socket_numeric_value(node.inputs[1], fallback), visited=visited.copy())
        if operation == "MULTIPLY":
            return a * b
        if operation == "ADD":
            return a + b
        if operation == "SUBTRACT":
            return a - b
        if operation == "DIVIDE":
            return a / b if abs(b) > 1e-8 else fallback
        if operation == "POWER":
            try:
                return a ** b
            except (ValueError, OverflowError):
                return fallback
        if operation == "MINIMUM":
            return min(a, b)
        if operation == "MAXIMUM":
            return max(a, b)
        if operation == "MULTIPLY_ADD":
            c = _resolve_float_socket(node.inputs[2], _socket_numeric_value(node.inputs[2], 0.0), visited=visited.copy())
            return (a * b) + c
        return a

    if node.bl_idname == ShaderNodeTypes.CLAMP:
        value = _resolve_float_socket(node.inputs.get("Value"), _socket_numeric_value(node.inputs.get("Value"), fallback), visited=visited.copy())
        min_value = _resolve_float_socket(node.inputs.get("Min"), _socket_numeric_value(node.inputs.get("Min"), 0.0), visited=visited.copy())
        max_value = _resolve_float_socket(node.inputs.get("Max"), _socket_numeric_value(node.inputs.get("Max"), 1.0), visited=visited.copy())
        return min(max(value, min_value), max_value)

    if node.bl_idname == ShaderNodeTypes.MAP_RANGE:
        value = _resolve_float_socket(node.inputs.get("Value"), _socket_numeric_value(node.inputs.get("Value"), fallback), visited=visited.copy())
        from_min = _resolve_float_socket(node.inputs.get("From Min"), _socket_numeric_value(node.inputs.get("From Min"), 0.0), visited=visited.copy())
        from_max = _resolve_float_socket(node.inputs.get("From Max"), _socket_numeric_value(node.inputs.get("From Max"), 1.0), visited=visited.copy())
        to_min = _resolve_float_socket(node.inputs.get("To Min"), _socket_numeric_value(node.inputs.get("To Min"), 0.0), visited=visited.copy())
        to_max = _resolve_float_socket(node.inputs.get("To Max"), _socket_numeric_value(node.inputs.get("To Max"), 1.0), visited=visited.copy())
        if abs(from_max - from_min) <= 1e-8:
            return to_min
        factor = (value - from_min) / (from_max - from_min)
        if getattr(node, "clamp", False):
            factor = _clamp01(factor)
        return to_min + (factor * (to_max - to_min))

    return _socket_numeric_value(socket, fallback)


def _find_image_node_from_socket(socket, *, usage, visited=None):
    if socket is None:
        return None
    if visited is None:
        visited = set()
    for link in socket.links:
        node = link.from_node
        node_id = id(node)
        if node_id in visited:
            continue
        visited.add(node_id)

        if node.bl_idname == ShaderNodeTypes.IMAGE_TEXTURE:
            return node

        if node.bl_idname == ShaderNodeTypes.NORMAL_MAP:
            image_socket = node.inputs.get("Color")
            found = _find_image_node_from_socket(image_socket, usage=usage, visited=visited)
            if found:
                return found

        if node.bl_idname == ShaderNodeTypes.REROUTE and node.inputs:
            found = _find_image_node_from_socket(node.inputs[0], usage=usage, visited=visited)
            if found:
                return found

        if node.bl_idname in {ShaderNodeTypes.SEPARATE_COLOR, ShaderNodeTypes.SEPARATE_RGB}:
            image_socket = node.inputs.get("Color") or node.inputs.get("Image")
            found = _find_image_node_from_socket(image_socket, usage=usage, visited=visited)
            if found:
                return found

        for input_socket, _ in _iter_input_links(node):
            found = _find_image_node_from_socket(input_socket, usage=usage, visited=visited)
            if found:
                return found

    return None


def _mix_shader_branches(node):
    if not node or node.bl_idname != ShaderNodeTypes.MIX_SHADER:
        return ()
    branches = []
    for socket_name in ("Shader", "Shader_001", 1, 2):
        socket = node.inputs.get(socket_name) if isinstance(socket_name, str) else node.inputs[socket_name]
        if socket and socket.links:
            branches.append(socket.links[0].from_node)
    return tuple(branches)


def _select_primary_shader(surface_node):
    if not surface_node:
        return None, None

    if surface_node.bl_idname == ShaderNodeTypes.BSDF_PRINCIPLED:
        return surface_node, None

    if surface_node.bl_idname == ShaderNodeTypes.EMISSION:
        return None, surface_node

    if surface_node.bl_idname == ShaderNodeTypes.MIX_SHADER:
        principled = None
        emission = None
        for branch in _mix_shader_branches(surface_node):
            if branch.bl_idname == ShaderNodeTypes.BSDF_PRINCIPLED and principled is None:
                principled = branch
            elif branch.bl_idname == ShaderNodeTypes.EMISSION and emission is None:
                emission = branch
        if principled or emission:
            return principled, emission

    return None, None


def analyze_material(material):
    if not material:
        return None

    surface_node = _linked_surface_node(material)
    principled_node, emission_node = _select_primary_shader(surface_node)

    if principled_node is None and emission_node is None:
        principled_node = _recursive_find_node_by_idname(material.node_tree, ShaderNodeTypes.BSDF_PRINCIPLED)
        emission_node = _recursive_find_node_by_idname(material.node_tree, ShaderNodeTypes.EMISSION)

    base_color = (0.8, 0.8, 0.8, 1.0)
    emissive_color = (0.0, 0.0, 0.0, 1.0)
    metallic = None
    roughness = None
    unlit = False

    if principled_node:
        base_color = _resolve_rgba_socket(principled_node.inputs.get("Base Color"), _node_default_rgba(principled_node, "Base Color", base_color))
        alpha = _resolve_float_socket(principled_node.inputs.get("Alpha"), _node_default_float(principled_node, "Alpha", base_color[3]))
        base_color = base_color[:3] + (alpha,)
        emission_socket_name = "Emission Color" if "Emission Color" in principled_node.inputs else "Emission"
        emissive_color = _resolve_rgba_socket(principled_node.inputs.get(emission_socket_name), _node_default_rgba(principled_node, emission_socket_name, emissive_color))
        emissive_strength = _resolve_float_socket(principled_node.inputs.get("Emission Strength"), _node_default_float(principled_node, "Emission Strength", 1.0))
        emissive_color = tuple(channel * emissive_strength for channel in emissive_color[:3]) + (base_color[3],)
        metallic = _resolve_float_socket(principled_node.inputs.get("Metallic"), _node_default_float(principled_node, "Metallic", 0.0))
        roughness = _resolve_float_socket(principled_node.inputs.get("Roughness"), _node_default_float(principled_node, "Roughness", 0.5))

    if emission_node and not principled_node:
        emissive_color = _resolve_rgba_socket(emission_node.inputs.get("Color"), _node_default_rgba(emission_node, "Color", emissive_color))
        strength = _resolve_float_socket(emission_node.inputs.get("Strength"), _node_default_float(emission_node, "Strength", 1.0))
        emissive_color = tuple(channel * strength for channel in emissive_color[:3]) + (1.0,)
        base_color = emissive_color
        unlit = True

    alpha_mode = "OPAQUE"
    if getattr(material, "surface_render_method", "") == "BLENDED" or getattr(material, "blend_method", "") == "BLEND":
        alpha_mode = "BLEND"
    elif getattr(material, "blend_method", "") == "CLIP":
        alpha_mode = "MASK"

    pbr = IRPBRMaterial(
        name=material.name,
        base_color=base_color,
        emissive_color=emissive_color,
        metallic=metallic,
        roughness=roughness,
        alpha_mode=alpha_mode,
        alpha_cutoff=getattr(material, "alpha_threshold", None),
        double_sided=not getattr(material, "use_backface_culling", False),
        unlit=unlit,
    )

    base_image = None
    if principled_node:
        base_image = _find_image_node_from_socket(principled_node.inputs.get("Base Color"), usage="baseColor")
    if base_image is None and emission_node and not principled_node:
        base_image = _find_image_node_from_socket(emission_node.inputs.get("Color"), usage="emissive")
    pbr.base_color_texture = _texture_ref_from_image_node(base_image, "baseColor") if base_image else None

    if principled_node:
        metallic_image = _find_image_node_from_socket(principled_node.inputs.get("Metallic"), usage="metallicRoughness")
        roughness_image = _find_image_node_from_socket(principled_node.inputs.get("Roughness"), usage="metallicRoughness")
        pbr.metallic_roughness_texture = _texture_ref_from_image_node(metallic_image or roughness_image, "metallicRoughness")

        normal_image = _find_image_node_from_socket(principled_node.inputs.get("Normal"), usage="normal")
        pbr.normal_texture = _texture_ref_from_image_node(normal_image, "normal") if normal_image else None
        normal_node = _upstream_node(principled_node.inputs.get("Normal"))
        if normal_node and normal_node.bl_idname == ShaderNodeTypes.NORMAL_MAP:
            pbr.normal_scale = _resolve_float_socket(normal_node.inputs.get("Strength"), _node_default_float(normal_node, "Strength", 1.0))

        emission_socket = principled_node.inputs.get("Emission Color") or principled_node.inputs.get("Emission")
        emissive_image = _find_image_node_from_socket(emission_socket, usage="emissive")
        pbr.emissive_texture = _texture_ref_from_image_node(emissive_image, "emissive") if emissive_image else None

    if emission_node and not pbr.emissive_texture:
        emissive_image = _find_image_node_from_socket(emission_node.inputs.get("Color"), usage="emissive")
        pbr.emissive_texture = _texture_ref_from_image_node(emissive_image, "emissive") if emissive_image else None

    occlusion_image = _find_labeled_image_node(material, ("occlusion", "ambient_occlusion", "ao"))
    pbr.occlusion_texture = _texture_ref_from_image_node(occlusion_image, "occlusion") if occlusion_image else None
    occlusion_strength_node = _find_labeled_value_node(material, ("occlusion_strength", "ao_strength"))
    if occlusion_strength_node and getattr(occlusion_strength_node, "outputs", None):
        pbr.occlusion_strength = float(occlusion_strength_node.outputs[0].default_value)

    return pbr


def image_texture_in_material(material):
    material_info = analyze_material(material)
    node_tree = getattr(material, "node_tree", None)
    if not node_tree:
        return None

    image_nodes = _recursive_find_nodes_by_idname(node_tree, ShaderNodeTypes.IMAGE_TEXTURE)
    if not image_nodes:
        return None

    preferred_textures = []
    if material_info:
        preferred_textures.extend([
            material_info.base_color_texture,
            material_info.emissive_texture,
            material_info.metallic_roughness_texture,
            material_info.normal_texture,
            material_info.occlusion_texture,
        ])

    for texture in preferred_textures:
        if not texture:
            continue
        for node in image_nodes:
            image = getattr(node, "image", None)
            if not image:
                continue
            if texture.image_name and image.name == texture.image_name:
                return node
            if texture.filepath and image.filepath == texture.filepath:
                return node

    return image_nodes[0]


def get_vector_mapping_properties(image_texture):
    transform = _texture_transform_from_mapping(_find_mapping_node(image_texture))
    if not transform:
        return None
    return {
        "rotation": (0.0, 0.0, transform.rotation),
        "scale": (transform.scale[0], transform.scale[1], 1.0),
        "translation": (transform.translation[0], transform.translation[1], 0.0),
    }


def get_movie_texture_properties(image_texture):
    if not image_texture or not hasattr(image_texture, "image") or not image_texture.image:
        logger.warning("No valid image data found in the node.")
        return None
    if image_texture.image.source != "MOVIE":
        return None
    image_user = image_texture.image_user
    return {
        "use_cyclic": image_user.use_cyclic,
        "use_auto_refresh": image_user.use_auto_refresh,
        "frame_start": image_user.frame_start,
        "frame_duration": image_user.frame_duration,
    }


def get_emissive_color(material):
    material_info = analyze_material(material)
    return material_info.emissive_color if material_info else None


def get_diffuse_color(material):
    material_info = analyze_material(material)
    return material_info.base_color if material_info else None
