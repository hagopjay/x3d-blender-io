# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D 4.0 Phong lighting (17.2.2.5) in EEVEE, with Blender 5.3's Material Lighting nodes. Opt-in (import option
"X3D lighting"); docs/LIGHTING.md has the measurements.

A classic X3D Material (Material, TwoSidedMaterial) normally imports as a Principled BSDF lit by Blender's lights, which
fall off as 1/d^2 and know nothing of X3D's attenuation, radius, beamWidth or ambientIntensity. With this option on, the
material also gets an EEVEE-only output with the node group "X3D Phong", which runs X3D's own lighting equation once
per light (Light Evaluation, Light Accumulation) and reads each light's X3D fields from custom properties on the light
object (the Attribute node's Light mode). Cycles keeps rendering the Principled BSDF (the plain fallback).

    fragmentColor = emissive + sum_i on_i x color_i x attenuation_i x spot_i
                    x (ambientIntensity_i x ambientIntensity x diffuse + intensity_i x diffuse x (N . L)
                       + intensity_i x specular x (N . H) ^ (shininess x 128))

The X3D spec says nothing about colour spaces, so the reading is an option (READINGS):
  LINEAR_VALUES  the file's numbers are linear values; Blender's view transform encodes the result for the display.
                 X3DOM 1.8.3 as it ships, X_ITE 16.8.1 with ColorSpace LINEAR, PhysicalMaterial's and glTF's reading.
  DISPLAY        the numbers are display values, lit as they are and shown as they are: the scene's view transform
                 becomes Raw. X_ITE 16.8.1 as it ships, X3DOM 1.8.3 with gammaCorrectionDefault "none".
  SRGB_DECODED   the numbers are sRGB-coded: decoded, lit, encoded by the view transform. No browser measured does this.

Light properties (on the light object, read per light by the group; a light without them adds nothing):
  x3d_phong_kind 1 directional, 2 point, 3 spot     x3d_phong_intensity, x3d_phong_ambient, x3d_phong_on (0 or 1)
  x3d_phong_color (in the reading's working space)  x3d_phong_attenuation (c1, c2, c3)
  x3d_phong_radius (Blender units; < 0 unlimited)   x3d_phong_frame (Blender length of one unit of the light's frame)
  x3d_phong_axis (world direction the light shines) x3d_phong_beam, x3d_phong_cutoff (radians)
The headlight is a sun of energy 1e-6 parented to the bound camera (make_headlight), which the X3D writers skip.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

GROUP_NAME = "X3D Phong"
GROUP_VERSION = 2
READINGS = ("LINEAR_VALUES", "DISPLAY", "SRGB_DECODED")
MATERIAL_PROPERTY = "x3d_phong"        # on a material: the file's Material fields, as read
LIGHT_PREFIX = "x3d_phong_"
SCENE_PROPERTY = "x3d_phong_reading"   # on the scene: the reading the import used
KINDS = {"DirectionalLight": 1, "PointLight": 2, "SpotLight": 3}
NO_CONE = 4.0                          # a cut-off past pi (and a beam 0.1 inside it): spot_i = 1 for a non-spot light


def resolve(value):
    """The import option, or the BLENDER_X3D_LIGHTING environment variable, as a reading, or None (off)."""
    import os
    raw = str(value or "").strip().upper()
    if raw in ("", "AUTO"):
        raw = os.environ.get("BLENDER_X3D_LIGHTING", "").strip().upper()
    raw = {"LINEAR": "LINEAR_VALUES", "X3DOM": "LINEAR_VALUES", "ON": "LINEAR_VALUES", "X_ITE": "DISPLAY",
           "XITE": "DISPLAY", "SRGB": "SRGB_DECODED"}.get(raw, raw)
    return raw if raw in READINGS else None


def srgb_to_linear(value):
    value = max(0.0, float(value))
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def working(colour, reading):
    """A file colour in the reading's working space (what the group multiplies)."""
    colour = tuple(float(channel) for channel in tuple(colour)[:3])
    return tuple(srgb_to_linear(channel) for channel in colour) if reading == "SRGB_DECODED" else colour


def material_fields(mat, ancestry):
    """A classic Material node's lighting fields, with X3D 4.0's defaults (12.4.5)."""
    if mat is None:
        return {"diffuseColor": (0.8, 0.8, 0.8), "emissiveColor": (0.0, 0.0, 0.0), "specularColor": (0.0, 0.0, 0.0),
                "shininess": 0.2, "ambientIntensity": 0.2, "transparency": 0.0}
    return {"diffuseColor": tuple(mat.getFieldAsFloatTuple("diffuseColor", (0.8, 0.8, 0.8), ancestry)),
            "emissiveColor": tuple(mat.getFieldAsFloatTuple("emissiveColor", (0.0, 0.0, 0.0), ancestry)),
            "specularColor": tuple(mat.getFieldAsFloatTuple("specularColor", (0.0, 0.0, 0.0), ancestry)),
            "shininess": mat.getFieldAsFloat("shininess", 0.2, ancestry),
            "ambientIntensity": mat.getFieldAsFloat("ambientIntensity", 0.2, ancestry),
            "transparency": mat.getFieldAsFloat("transparency", 0.0, ancestry)}


def light_fields(node, spec, ancestry, version=4.0):
    """A light node's lighting fields, with X3D's defaults. A SpotLight's beamWidth and cutOffAngle defaults changed in
    X3D 4.0 (3 pi / 16 and pi / 2; X3D 3.x and VRML97: pi / 2 and pi / 4), so the file's version picks them."""
    four = version >= 4.0
    fields = {"kind": KINDS[spec], "intensity": node.getFieldAsFloat("intensity", 1.0, ancestry),
              "ambientIntensity": node.getFieldAsFloat("ambientIntensity", 0.0, ancestry),
              "color": tuple(node.getFieldAsFloatTuple("color", (1.0, 1.0, 1.0), ancestry)),
              "on": node.getFieldAsBool("on", True, ancestry)}
    if spec != "DirectionalLight":
        attenuation = node.getFieldAsFloatTuple("attenuation", (1.0, 0.0, 0.0), ancestry)
        fields["attenuation"] = tuple((list(attenuation) + [0.0, 0.0, 0.0])[:3])
        fields["radius"] = node.getFieldAsFloat("radius", 100.0, ancestry)
    if spec == "SpotLight":
        fields["beamWidth"] = node.getFieldAsFloat("beamWidth", 3.0 * math.pi / 16.0 if four else math.pi / 2.0,
                                                   ancestry)
        fields["cutOffAngle"] = node.getFieldAsFloat("cutOffAngle", math.pi / 2.0 if four else math.pi / 4.0, ancestry)
    return fields


def tag_light(bpyob, fields, frame, reading):
    """Write a light's X3D fields onto its object for the group (see the module docstring)."""
    bpyob[LIGHT_PREFIX + "kind"] = int(fields["kind"])
    bpyob[LIGHT_PREFIX + "intensity"] = max(0.0, float(fields["intensity"]))
    bpyob[LIGHT_PREFIX + "ambient"] = max(0.0, float(fields["ambientIntensity"]))
    bpyob[LIGHT_PREFIX + "on"] = 1.0 if fields["on"] else 0.0
    bpyob[LIGHT_PREFIX + "color"] = list(working(fields["color"], reading))
    bpyob[LIGHT_PREFIX + "attenuation"] = [float(c) for c in fields.get("attenuation", (1.0, 0.0, 0.0))]
    radius = fields.get("radius", -1.0)
    bpyob[LIGHT_PREFIX + "radius"] = float(radius) * frame if radius >= 0.0 else -1.0
    bpyob[LIGHT_PREFIX + "frame"] = float(frame) if frame > 0.0 else 1.0
    if fields["kind"] == 3:
        cut_off = min(max(float(fields["cutOffAngle"]), 0.0), math.pi / 2.0)
        beam = min(max(float(fields["beamWidth"]), 0.0), cut_off)
        bpyob[LIGHT_PREFIX + "cutoff"] = cut_off
        bpyob[LIGHT_PREFIX + "beam"] = min(beam, cut_off - 1e-6)   # beam = cut-off: a hard edge (no division by 0)
    else:
        bpyob[LIGHT_PREFIX + "cutoff"], bpyob[LIGHT_PREFIX + "beam"] = NO_CONE, NO_CONE - 0.1   # ramp > 1 up to pi
    sync_axis(bpyob)


def sync_axis(bpyob):
    """The light's world direction (its -Z), which the group's cone uses; kept up to date by the depsgraph handler."""
    axis = (bpyob.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    old = bpyob.get(LIGHT_PREFIX + "axis")
    if old is None or any(abs(a - b) > 1e-7 for a, b in zip(old, axis)):
        bpyob[LIGHT_PREFIX + "axis"] = list(axis)


@bpy.app.handlers.persistent
def on_depsgraph_update(scene, depsgraph=None):
    """A moved or turned X3D light keeps its cone pointing where the light points (persistent: it stays registered
    when a .blend is opened)."""
    for update in getattr(depsgraph, "updates", ()):
        ob = getattr(update.id, "original", update.id)
        if isinstance(ob, bpy.types.Object) and ob.type == 'LIGHT' and update.is_updated_transform \
                and (LIGHT_PREFIX + "kind") in ob:
            sync_axis(ob)


class _Graph:
    """A small helper for building the group: each call adds one node and returns its output socket."""

    def __init__(self, tree):
        self.tree, self.count = tree, 0

    def feed(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        elif value is not None:
            socket.default_value = value

    def node(self, kind, inputs=(), **settings):
        node = self.tree.nodes.new(kind)
        for key, value in settings.items():
            setattr(node, key, value)
        for index, value in enumerate(inputs):
            self.feed(node.inputs[index], value)
        self.count += 1
        node.location = (200 * (self.count // 12), -160 * (self.count % 12))
        return node

    def math(self, operation, a, b=None, clamp=False):
        return self.node("ShaderNodeMath", (a, b), operation=operation, use_clamp=clamp).outputs[0]

    def vector(self, operation, a, b=None):
        node = self.node("ShaderNodeVectorMath", (a, b), operation=operation)
        return node.outputs["Value" if operation == 'DOT_PRODUCT' else "Vector"]

    def scale(self, vector, factor):
        node = self.node("ShaderNodeVectorMath", (vector,), operation='SCALE')
        self.feed(node.inputs["Scale"], factor)
        return node.outputs["Vector"]

    def light(self, name, vector=False):
        """One of the light's x3d_phong_ properties, read per light (the Attribute node's Light mode)."""
        node = self.node("ShaderNodeAttribute", attribute_type='LIGHT', attribute_name=LIGHT_PREFIX + name)
        return node.outputs["Vector" if vector else "Fac"]


def group():
    """The shared "X3D Phong" node group (built once per file, rebuilt when GROUP_VERSION changes)."""
    tree = bpy.data.node_groups.get(GROUP_NAME)
    if tree is not None and tree.get("x3d_phong_version") == GROUP_VERSION:
        return tree
    if tree is None:
        tree = bpy.data.node_groups.new(GROUP_NAME, 'ShaderNodeTree')
    tree.nodes.clear()
    tree.interface.clear()
    for name, kind, value in (("Diffuse", 'NodeSocketColor', (0.8, 0.8, 0.8, 1.0)),
                              ("Specular", 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0)),
                              ("Emissive", 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0)),
                              ("Exponent", 'NodeSocketFloat', 25.6), ("Ambient", 'NodeSocketFloat', 0.2),
                              ("Alpha", 'NodeSocketFloat', 1.0)):
        socket = tree.interface.new_socket(name, in_out='INPUT', socket_type=kind)
        socket.default_value = value
    tree.interface.new_socket("Shader", in_out='OUTPUT', socket_type='NodeSocketShader')
    tree["x3d_phong_version"] = GROUP_VERSION
    g = _Graph(tree)
    given = g.node("NodeGroupInput").outputs
    diffuse, specular, emissive = given["Diffuse"], given["Specular"], given["Emissive"]
    exponent, ambient = given["Exponent"], given["Ambient"]
    geometry = g.node("ShaderNodeNewGeometry").outputs
    normal, view = geometry["Normal"], geometry["Incoming"]

    # Per light: Light Evaluation gives L (towards the light) and the distance; Light Accumulation sums what we give it.
    evaluation = g.node("ShaderNodeLightEvaluation", (None, geometry["Position"], normal), mode='DIFFUSE').outputs
    towards, distance = evaluation["Direction"], evaluation["Distance"]
    n_dot_l = g.math('MAXIMUM', g.vector('DOT_PRODUCT', normal, towards), 0.0)
    half = g.vector('NORMALIZE', g.vector('ADD', towards, view))
    shine = g.math('POWER', g.math('MAXIMUM', g.vector('DOT_PRODUCT', normal, half), 0.0), exponent)
    local = g.math('DIVIDE', distance, g.light("frame"))          # the distance in the light's own frame
    c = g.node("ShaderNodeSeparateXYZ", (g.light("attenuation", vector=True),)).outputs
    falloff = g.math('ADD', g.math('ADD', c[0], g.math('MULTIPLY', c[1], local)),
                     g.math('MULTIPLY', c[2], g.math('MULTIPLY', local, local)))
    attenuation = g.math('DIVIDE', 1.0, g.math('MAXIMUM', falloff, 1.0))
    radius = g.light("radius")
    in_reach = g.math('MAXIMUM', g.math('LESS_THAN', radius, 0.0),
                      g.math('SUBTRACT', 1.0, g.math('GREATER_THAN', distance, radius)))
    along = g.vector('DOT_PRODUCT', g.scale(towards, -1.0), g.light("axis", vector=True))
    angle = g.math('ARCCOSINE', g.math('MINIMUM', g.math('MAXIMUM', along, -1.0), 1.0))
    cut_off = g.light("cutoff")
    spot = g.math('DIVIDE', g.math('SUBTRACT', cut_off, angle), g.math('SUBTRACT', cut_off, g.light("beam")),
                  clamp=True)
    level = g.math('MULTIPLY', g.math('MULTIPLY', g.light("on"), in_reach), g.math('MULTIPLY', attenuation, spot))
    intensity = g.light("intensity")
    lit = g.math('ADD', g.math('MULTIPLY', g.light("ambient"), ambient), g.math('MULTIPLY', intensity, n_dot_l))
    terms = g.vector('ADD', g.scale(diffuse, lit), g.scale(specular, g.math('MULTIPLY', intensity, shine)))
    contribution = g.vector('MULTIPLY', g.scale(terms, level), g.light("color", vector=True))
    accumulation = g.node("ShaderNodeLightAccumulation")
    g.feed(accumulation.inputs["Diffuse Light"], contribution)
    accumulation.inputs["Diffuse Color"].default_value = (1.0, 1.0, 1.0, 1.0)

    glow = g.node("ShaderNodeEmission", (emissive, 1.0)).outputs[0]
    lit_shader = g.node("ShaderNodeAddShader", (accumulation.outputs["Shader"], glow)).outputs[0]
    clear = g.node("ShaderNodeBsdfTransparent").outputs[0]
    surface = g.node("ShaderNodeMixShader", (given["Alpha"], clear, lit_shader)).outputs[0]
    g.feed(g.node("NodeGroupOutput").inputs[0], surface)
    return tree


def apply_material(bpymat, fields, reading):
    """Give a classic material its EEVEE "X3D Phong" output; the Principled BSDF output stays for Cycles."""
    tree = bpymat.node_tree
    if tree is None:
        return None
    existing = [node for node in tree.nodes if node.bl_idname == 'ShaderNodeOutputMaterial' and node.target != 'EEVEE']
    for output in existing:
        output.target = 'CYCLES'
    node = tree.nodes.new('ShaderNodeGroup')
    node.node_tree = group()
    node.name = node.label = GROUP_NAME
    node.location = (300, -400)
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    output.target = 'EEVEE'
    output.location = (600, -400)
    tree.links.new(node.outputs[0], output.inputs['Surface'])
    for socket, field in (("Diffuse", "diffuseColor"), ("Specular", "specularColor"), ("Emissive", "emissiveColor")):
        node.inputs[socket].default_value = working(fields[field], reading) + (1.0,)
    node.inputs["Exponent"].default_value = max(0.0, float(fields["shininess"])) * 128.0
    node.inputs["Ambient"].default_value = max(0.0, float(fields["ambientIntensity"]))
    node.inputs["Alpha"].default_value = 1.0 - min(max(float(fields["transparency"]), 0.0), 1.0)
    # a texture or per-vertex colour feeding the Principled base colour feeds X3D's diffuse colour too
    bsdf = next((n for n in tree.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled'), None)
    if bsdf is not None and bsdf.inputs["Base Color"].is_linked:
        source = bsdf.inputs["Base Color"].links[0].from_socket
        if reading == "DISPLAY":   # Blender decodes an sRGB image; the display reading lights the stored values
            gamma = tree.nodes.new('ShaderNodeGamma')
            gamma.inputs[1].default_value = 1.0 / 2.2
            tree.links.new(source, gamma.inputs[0])
            source = gamma.outputs[0]
        tree.links.new(source, node.inputs["Diffuse"])
    bpymat[MATERIAL_PROPERTY] = {key: list(value) if isinstance(value, tuple) else value for key, value in fields.items()}
    return node


HEADLIGHT_PROPERTY = "x3d_phong_headlight"   # extract.PHONG_HEADLIGHT_PROPERTY: neither X3D writer exports it
HEADLIGHT_ENERGY = 1e-6


def make_headlight(scene, camera, collection, reading):
    """X3D's headlight (NavigationInfo headlight, on by default) is a DirectionalLight of intensity 1, colour white,
    ambientIntensity 0, along the view (X3D 4.0 23.4.4). Here it is a sun parented to the bound camera, pointing where
    the camera looks, with the X3D Phong light properties, so the group lights it as it lights a DirectionalLight.
    The group reads only those properties, so its Blender energy is 1e-6 W/m2: EEVEE leaves a light of energy 0 out
    of the light loop (measured, Blender 5.3.0), and Cycles and the Principled BSDF do not see a microwatt. None
    without a camera."""
    if camera is None:
        return None
    data = bpy.data.lights.new("X3D headlight", 'SUN')
    data.energy = HEADLIGHT_ENERGY
    data.use_shadow = False
    sun = bpy.data.objects.new("X3D headlight", data)
    (collection or scene.collection).objects.link(sun)
    sun.parent = camera
    sun.matrix_parent_inverse.identity()   # the camera's own frame: its -Z is the view
    sun[HEADLIGHT_PROPERTY] = True
    sun.hide_select = True
    bpy.context.view_layer.update()
    tag_light(sun, {"kind": 1, "intensity": 1.0, "ambientIntensity": 0.0, "color": (1.0, 1.0, 1.0), "on": True},
              1.0, reading)
    return sun


def finish(scene, reading):
    """Scene settings the reading needs. X3D's lit colour goes to the display unchanged but for the sRGB encoding:
    Standard (not Blender's default AgX, which tone-maps), or Raw for DISPLAY, which shows the lit numbers as they are;
    no look, exposure 0, gamma 1."""
    scene[SCENE_PROPERTY] = reading
    view = scene.view_settings
    view.view_transform = 'Raw' if reading == "DISPLAY" else 'Standard'
    view.look = 'None'
    view.exposure, view.gamma = 0.0, 1.0
