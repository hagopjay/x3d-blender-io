# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A filled UnlitMaterial shape reaches glTF as KHR_materials_unlit, with its Color or ColorRGBA as COLOR_0.

X_ITE 16.7.1 draws an UnlitMaterial with its Unlit shader (x_ite.js, Unlit2.glsl.js, getEmissiveColor): no lighting,
``vec4 (emissiveColor, 1 - transparency)``, or ``vec4 (color.rgb, color.a * (1 - transparency))`` when the geometry
has a Color or ColorRGBA node (X3D_COLOR_MATERIAL), times the emissiveTexture; a ColorRGBA makes the geometry
transparent (ColorRGBA: setTransparent (true)), so the Shape blends under alphaMode AUTO. The importer kept such a
surface a Principled BSDF with a black Base Color and the colour as emission: Blender's glTF exporter wrote
baseColorFactor 0 0 0, emissiveFactor 1 1 1, KHR_materials_specular and COLOR_0, which glTF multiplies into the
black baseColor only, so Babylon.js drew the habsburg demo's Cloth, FellMat and BeadMat white where X_ITE draws the
vertex colours. Material, TwoSidedMaterial and PhysicalMaterial shapes stay as they were, and the X3D exports write
the UnlitMaterial back with the same emissiveColor and transparency (X3D 4.0), or as a Material that draws only the
emissiveColor (X3D 3.3).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_unlit_colour_bpy
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension
from test_import_alpha_bpy import _write_png

TRI = ("<Transform DEF='%s'><Shape><Appearance>%s</Appearance><IndexedFaceSet coordIndex='0 1 2 -1'>"
       "<Coordinate point='0 0 0 1 0 0 0 1 0'/><TextureCoordinate point='0 0 1 0 0 1'/>%s</IndexedFaceSet>"
       "</Shape></Transform>")
COLOR = "<Color color='1 0 0 0 0.5 0 0 0 1'/>"
COLOR_RGBA = "<ColorRGBA color='1 0 0 0.5 0 0.5 0 1 0 0 1 0.25'/>"
TEXTURE = "<ImageTexture containerField='emissiveTexture' url='\"solid.png\"'/>"
SHAPES = {
    "Cloth": ("<UnlitMaterial DEF='Cloth' emissiveColor='0.2 0.2 0.2'/>", COLOR),
    "Fell": ("<UnlitMaterial DEF='Fell' transparency='0.5'/>", COLOR_RGBA),
    "Plain": ("<UnlitMaterial DEF='Plain' emissiveColor='0.5 0.25 1' transparency='0.25'/>", ""),
    "PlainColoured": ("<UnlitMaterial USE='Plain'/>", COLOR),       # one material, with and without a Color node
    "Textured": (f"<UnlitMaterial DEF='Textured'>{TEXTURE}</UnlitMaterial>", COLOR),
    "Classic": ("<Material DEF='Classic' diffuseColor='0.5 0.5 0.5'/>", COLOR),
    "TwoSided": ("<TwoSidedMaterial DEF='TwoSided' diffuseColor='0.5 0.5 0.5'/>", COLOR),
    "Physical": ("<PhysicalMaterial DEF='Physical' baseColor='0.5 0.5 0.5'/>", COLOR),
}
SCENE = ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Full' version='4.0'><Scene>"
         + "".join(TRI % (name, appearance, colour) for name, (appearance, colour) in SHAPES.items())
         + "</Scene></X3D>\n")
LINEAR_HALF = 0.214041     # sRGB 0.5, as X_ITE reads a Color under an UnlitMaterial (display space)


def _glb(path):
    """(json, binary chunk) of a .glb."""
    with open(path, "rb") as f:
        raw = f.read()
    length = struct.unpack("<I", raw[12:16])[0]
    gltf = json.loads(raw[20:20 + length])
    rest = raw[20 + length:]
    return gltf, rest[8:8 + struct.unpack("<I", rest[:4])[0]]


def _accessor(gltf, blob, index):
    """An accessor's values as lists of floats (normalized integers scaled to 0..1)."""
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    fmt, scale = {5126: ("f", 1.0), 5123: ("H", 65535.0), 5121: ("B", 255.0)}[acc["componentType"]]
    size = struct.calcsize("<" + fmt)
    stride = view.get("byteStride", size * width)
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return [[v / scale if fmt != "f" else v for v in struct.unpack_from("<%d%s" % (width, fmt), blob, start + i * stride)]
            for i in range(acc["count"])]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class UnlitColourTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import bpy
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_unlit_colour_")
        _register_extension(cls.tmpdir)
        _write_png(os.path.join(cls.tmpdir, "solid.png"), [(200, 100, 50, 255)] * 4, alpha=False)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(cls.tmpdir)
        path = os.path.join(cls.tmpdir, "in.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(SCENE)
        assert bpy.ops.import_scene.x3d(filepath=path, color_space='SRGB') == {"FINISHED"}
        out = os.path.join(cls.tmpdir, "out.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
        cls.gltf, cls.blob = _glb(out)
        nodes = {node["name"]: node for node in cls.gltf["nodes"] if "mesh" in node}
        cls.prims = {name: cls.gltf["meshes"][nodes[name]["mesh"]]["primitives"][0] for name in SHAPES}

    def material(self, name):
        return self.gltf["materials"][self.prims[name]["material"]]

    def colours(self, name):
        prim = self.prims[name]
        self.assertIn("COLOR_0", prim["attributes"], name)
        return _accessor(self.gltf, self.blob, prim["attributes"]["COLOR_0"])

    def assertNear(self, got, want, places=3):
        self.assertEqual(len(got), len(want), (got, want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=places, msg=(got, want))

    def test_color_node_reaches_the_pixel_as_color_0_of_an_unlit_material(self):
        # the colours replace emissiveColor: a white factor (glTF's default), alpha 1 - transparency, and the
        # Color's linear values in COLOR_0
        for name, factor, mode in (("Cloth", None, None), ("PlainColoured", [1.0, 1.0, 1.0, 0.75], "BLEND")):
            with self.subTest(shape=name):
                material = self.material(name)
                self.assertIn("KHR_materials_unlit", material.get("extensions", {}))
                self.assertNotIn("emissiveFactor", material)
                if factor is None:
                    self.assertIsNone(material["pbrMetallicRoughness"].get("baseColorFactor"))
                else:
                    self.assertNear(material["pbrMetallicRoughness"]["baseColorFactor"], factor)
                self.assertEqual(material.get("alphaMode"), mode)
                rgb = sorted(tuple(round(v, 3) for v in c[:3]) for c in self.colours(name))
                self.assertEqual(rgb, [(0.0, 0.0, 1.0), (0.0, round(LINEAR_HALF, 3), 0.0), (1.0, 0.0, 0.0)])

    def test_color_rgba_alpha_times_one_minus_transparency_blends(self):
        material = self.material("Fell")
        self.assertIn("KHR_materials_unlit", material.get("extensions", {}))
        self.assertEqual(material.get("alphaMode"), "BLEND")
        self.assertNear(material["pbrMetallicRoughness"]["baseColorFactor"], [1.0, 1.0, 1.0, 0.5])
        colours = self.colours("Fell")
        self.assertEqual(sorted(round(c[3], 3) for c in colours), [0.25, 0.5, 1.0])
        self.assertEqual(sorted(tuple(round(v, 3) for v in c[:3]) for c in colours),
                         [(0.0, 0.0, 1.0), (0.0, round(LINEAR_HALF, 3), 0.0), (1.0, 0.0, 0.0)])

    def test_unlit_material_without_colours_is_khr_materials_unlit(self):
        material = self.material("Plain")
        self.assertIn("KHR_materials_unlit", material.get("extensions", {}))
        self.assertNotIn("emissiveFactor", material)
        self.assertEqual(material.get("alphaMode"), "BLEND")
        # linear emissiveColor (sRGB 0.5 0.25 1) and 1 - transparency
        self.assertNear(material["pbrMetallicRoughness"]["baseColorFactor"], [LINEAR_HALF, 0.050876, 1.0, 0.75])
        self.assertNotIn("COLOR_0", self.prims["Plain"]["attributes"])

    def test_emissive_texture_becomes_the_base_colour_texture_times_the_colours(self):
        material = self.material("Textured")
        self.assertIn("KHR_materials_unlit", material.get("extensions", {}))
        self.assertIn("baseColorTexture", material["pbrMetallicRoughness"])
        self.assertIsNone(material["pbrMetallicRoughness"].get("baseColorFactor"))
        self.assertEqual(len(self.colours("Textured")), 3)

    def test_lit_materials_with_colours_are_unchanged(self):
        import bpy
        for name in ("Classic", "TwoSided", "Physical"):
            with self.subTest(shape=name):
                self.assertNotIn("KHR_materials_unlit", self.material(name).get("extensions", {}))
                material = bpy.data.objects[name].data.materials[0]
                self.assertTrue(any(n.type == 'BSDF_PRINCIPLED' for n in material.node_tree.nodes))
                self.assertFalse(any(n.type == 'EMISSION' for n in material.node_tree.nodes))

    def _export(self, version):
        import bpy
        path = os.path.join(self.tmpdir, f"out_{version}.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False),
                         {"FINISHED"})
        return ET.parse(path).getroot()

    def test_x3d40_export_writes_the_unlit_material_back(self):
        root = self._export("X3D40")
        written = {}
        for transform in root.iter("Transform"):
            material = transform.find(".//UnlitMaterial")
            if transform.get("DEF", "").replace("OB_", "") in SHAPES and material is not None:
                written[transform.get("DEF").replace("OB_", "")] = material
        self.assertEqual(set(written), {"Cloth", "Fell", "Plain", "PlainColoured", "Textured"})
        expect = {"Cloth": ([0.2, 0.2, 0.2], 0.0), "Fell": ([1.0, 1.0, 1.0], 0.5), "Plain": ([0.5, 0.25, 1.0], 0.25),
                  "PlainColoured": ([0.5, 0.25, 1.0], 0.25), "Textured": ([1.0, 1.0, 1.0], 0.0)}
        for name, (emissive, transparency) in expect.items():
            with self.subTest(shape=name):
                self.assertNear([float(v) for v in written[name].attrib["emissiveColor"].split()], emissive)
                self.assertAlmostEqual(float(written[name].attrib.get("transparency", "0")), transparency, places=3)
        self.assertIsNotNone(written["Textured"].find("ImageTexture"))

    def test_x3d33_export_writes_an_emissive_only_material(self):
        root = self._export("X3D33")
        written = {}
        for transform in root.iter("Transform"):
            name = transform.get("DEF", "").replace("_TRANSFORM", "")
            material = transform.find(".//Material")
            if name in SHAPES and material is not None:
                written[name] = material
        expect = {"Cloth": ([0.2, 0.2, 0.2], 0.0), "Fell": ([1.0, 1.0, 1.0], 0.5), "Plain": ([0.5, 0.25, 1.0], 0.25)}
        for name, (emissive, transparency) in expect.items():
            with self.subTest(shape=name):
                self.assertNear([float(v) for v in written[name].attrib["emissiveColor"].split()], emissive, places=2)
                self.assertNear([float(v) for v in written[name].attrib["diffuseColor"].split()], [0.0, 0.0, 0.0])
                self.assertAlmostEqual(float(written[name].attrib["transparency"]), transparency, places=3)


if __name__ == "__main__":
    unittest.main()


GLTF_UNLIT = {
    "asset": {"version": "2.0"},
    "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "Quad"}],
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}]}],
    "materials": [{"name": "Glass", "alphaMode": "BLEND", "extensions": {"KHR_materials_unlit": {}},
                   "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "baseColorTexture": {"index": 0}}}],
    "textures": [{"source": 0}], "images": [{"uri": "glass.png"}],
    "extensionsUsed": ["KHR_materials_unlit"],
    "accessors": [
        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
        {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"}],
    "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 24}],
}


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class GltfUnlitAlphaTests(unittest.TestCase):

    def test_a_texture_alpha_is_not_written_as_transparency(self):
        # Blender's glTF importer links the alpha Mix Shader's factor straight to the texture's alpha for alphaMode
        # BLEND, leaving the factor's default 0.5 on the socket; X_ITE draws (1 - transparency) x the texture alpha
        # (Unlit2.glsl getEmissiveColor), so the X3D export must not add a transparency of 0.5 on top
        import base64
        import bpy
        tmpdir = tempfile.mkdtemp(prefix="x3d_gltf_unlit_")
        _register_extension(tmpdir)
        _write_png(os.path.join(tmpdir, "glass.png"), [(255, 255, 255, 64)] * 4, alpha=True)
        data = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0) + struct.pack("<6f", 0, 0, 1, 0, 0, 1)
        gltf = dict(GLTF_UNLIT, buffers=[{"byteLength": len(data),
                                          "uri": "data:application/octet-stream;base64," + base64.b64encode(data).decode()}])
        path = os.path.join(tmpdir, "glass.gltf")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(gltf, f)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.gltf(filepath=path), {"FINISHED"})
        out = os.path.join(tmpdir, "glass.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        material = ET.parse(out).getroot().find(".//UnlitMaterial")
        self.assertIsNotNone(material)
        self.assertAlmostEqual(float(material.attrib.get("transparency", 0.0)), 0.0, places=4)
