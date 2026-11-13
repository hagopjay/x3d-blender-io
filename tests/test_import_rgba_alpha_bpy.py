# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A ColorRGBA's alpha on a surface without a material reaches the glb, as X_ITE draws it.

X_ITE 16.7.1 draws a Shape whose Appearance has no material node (or that has no Appearance) with its default
UnlitMaterial, whose shader takes ``vec4 (color.rgb, color.a * (1 - transparency))`` (Unlit2.glsl,
getEmissiveColor), and a ColorRGBA makes the geometry transparent (X3DGeometryNode.set_color__), so under alphaMode
AUTO the Shape blends (X3DShapeNode.set_transparent__). The importer kept the alpha in the ColorPerCorner attribute
but its unlit material read only the colour: Blender's glTF exporter wrote KHR_materials_unlit with a VEC3 COLOR_0
and alphaMode OPAQUE (the earth-clouds demo's cloud layer came out as an opaque shell). A Color node stays opaque, and
the X3D 4.0 export writes the ColorRGBA back unchanged.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_rgba_alpha_bpy
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

TRI = ("<Transform DEF='%s'><Shape>%s<IndexedFaceSet coordIndex='0 1 2 -1'>"
       "<Coordinate point='0 0 0 1 0 0 0 1 0'/>%s</IndexedFaceSet></Shape></Transform>")
RGBA = [1.0, 0.0, 0.0, 0.25, 0.0, 1.0, 0.0, 0.5, 0.0, 0.0, 1.0, 0.75]
COLOR_RGBA = "<ColorRGBA color='%s'/>" % " ".join("%g" % v for v in RGBA)
COLOR_RGB = "<Color color='1 0 0 0 1 0 0 0 1'/>"
SCENE = ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Full' version='4.0'><Scene>"
         + TRI % ("NoMaterial", "<Appearance/>", COLOR_RGBA)
         + TRI % ("NoAppearance", "", COLOR_RGBA)
         + TRI % ("Opaque", "<Appearance/>", COLOR_RGB)
         + TRI % ("ForcedOpaque", "<Appearance alphaMode='OPAQUE'/>", COLOR_RGBA)
         + "</Scene></X3D>\n")


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
class ColourRGBAAlphaTests(unittest.TestCase):

    def setUp(self):
        import bpy
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_rgba_alpha_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        path = os.path.join(self.tmpdir, "in.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(SCENE)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        self.objects = {ob.name: ob for ob in bpy.context.scene.objects if ob.type == 'MESH'}
        self.assertEqual(set(self.objects), {"NoMaterial", "NoAppearance", "Opaque", "ForcedOpaque"})

    def test_colour_rgba_alpha_makes_the_glb_blend_with_the_alpha_in_color_0(self):
        import bpy
        out = os.path.join(self.tmpdir, "out.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
        gltf, blob = _glb(out)
        nodes = {node["name"]: node for node in gltf["nodes"] if "mesh" in node}
        for name in ("NoMaterial", "NoAppearance", "Opaque"):
            with self.subTest(shape=name):
                prim = gltf["meshes"][nodes[name]["mesh"]]["primitives"][0]
                material = gltf["materials"][prim["material"]]
                self.assertIn("KHR_materials_unlit", material.get("extensions", {}))
                colours = _accessor(gltf, blob, prim["attributes"]["COLOR_0"])
                if name == "Opaque":                            # a Color node: no alpha, still opaque
                    self.assertIsNone(material.get("alphaMode"))
                    self.assertTrue(all(len(c) == 3 or abs(c[3] - 1.0) < 1e-3 for c in colours), colours)
                    continue
                self.assertEqual(material.get("alphaMode"), "BLEND")
                self.assertEqual(sorted(round(c[3], 3) for c in colours), [0.25, 0.5, 0.75])
                self.assertEqual(sorted(tuple(round(v, 3) for v in c[:3]) for c in colours),
                                 [(0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)])

    def test_alpha_mode_opaque_keeps_a_colour_rgba_shape_opaque(self):
        # X_ITE takes the transparency from the geometry only under alphaMode AUTO (X3DShapeNode.set_transparent__)
        # and draws alphaMode OPAQUE with alpha 1 (X3D_ALPHA_MODE_OPAQUE)
        import bpy
        out = os.path.join(self.tmpdir, "opaque.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
        gltf, _blob = _glb(out)
        node = next(node for node in gltf["nodes"] if node.get("name") == "ForcedOpaque")
        material = gltf["materials"][gltf["meshes"][node["mesh"]]["primitives"][0]["material"]]
        self.assertIn("KHR_materials_unlit", material.get("extensions", {}))
        self.assertIsNone(material.get("alphaMode"))
        self.assertNotEqual(self.objects["ForcedOpaque"].data.materials[0].surface_render_method, "BLENDED")

    def test_blender_material_takes_the_alpha_from_the_colour_attribute(self):
        for name in ("NoMaterial", "NoAppearance"):
            with self.subTest(shape=name):
                material = self.objects[name].data.materials[0]
                self.assertEqual(material.surface_render_method, "BLENDED")
                attributes = [n for n in material.node_tree.nodes if n.type == 'VERTEX_COLOR']
                self.assertEqual(len(attributes), 1)
                self.assertTrue(attributes[0].outputs["Alpha"].is_linked)
        opaque = self.objects["Opaque"].data.materials[0]
        self.assertNotEqual(opaque.surface_render_method, "BLENDED")

    def test_x3d40_export_writes_the_colour_rgba_back_unchanged(self):
        import bpy
        path = os.path.join(self.tmpdir, "out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        root = ET.parse(path).getroot()
        written = {}
        for transform in root.iter("Transform"):
            node = transform.find(".//ColorRGBA")
            if node is not None and transform.get("DEF", "").replace("OB_", "") in self.objects:
                written[transform.get("DEF").replace("OB_", "")] = (node, transform.find(".//UnlitMaterial"))
        self.assertEqual(set(written), {"NoMaterial", "NoAppearance", "Opaque", "ForcedOpaque"})
        for name in ("NoMaterial", "NoAppearance"):
            with self.subTest(shape=name):
                node, material = written[name]
                values = [float(v) for v in node.attrib["color"].split()]
                self.assertEqual(len(values), len(RGBA))
                for got, want in zip(values, RGBA):
                    self.assertAlmostEqual(got, want, places=5)
                # the alpha stays in the ColorRGBA only, not again as the material's transparency
                self.assertIsNotNone(material)
                self.assertNotIn("transparency", material.attrib)
        values = [float(v) for v in written["Opaque"][0].attrib["color"].split()]
        self.assertEqual(values[3::4], [1.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
