# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: a PhysicalMaterial's baseColor (a Material's diffuseColor) multiplies its texture and its Color node, as in
X_ITE 16.7.1 and glTF, instead of being replaced by them; one ImageTexture DEF'd as baseTexture and USE'd as
emissiveTexture loads for both slots.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_base_colour_bpy
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
import zlib

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

HEADER = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          "<X3D profile='Immersive' version='4.0'><Scene>\n")
FOOTER = "</Scene></X3D>\n"
TINT = (0.06, 0.5, 0.48)


def _write_png(path: str, rgb=(250, 200, 150), size: int = 2):
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


QUAD = ("<IndexedFaceSet coordIndex='0 1 2 3 -1' colorPerVertex='true'>"
        "<Coordinate point='-1 -1 0 1 -1 0 1 1 0 -1 1 0'/>{colour}</IndexedFaceSet>")


def _shape(name, material, geometry=None):
    return (f"<Shape DEF='{name}'><Appearance>{material}</Appearance>"
            f"{geometry or QUAD.format(colour='')}</Shape>")


def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')


def _multiplied_by(socket):
    """(the node that feeds a Multiply Mix, its constant colour) for a socket fed by Mix Multiply, else None."""
    if not socket.is_linked or socket.links[0].from_node.bl_idname != "ShaderNodeMix":
        return None
    mix = socket.links[0].from_node
    if (mix.data_type, mix.blend_type) != ('RGBA', 'MULTIPLY'):
        return None
    a, b = (s for s in mix.inputs if s.type == 'RGBA')
    return a, b


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportBaseColourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_basecolour_")
        _register_extension(cls.tmpdir)
        _write_png(os.path.join(cls.tmpdir, "tex.png"))

    def _import(self, name, body, **kwargs):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + body + FOOTER)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, **kwargs), {"FINISHED"})
        return path

    def _mat(self, name):
        import bpy
        return bpy.data.materials[name]

    # D9: one texture under two slots

    def test_def_base_texture_used_as_emissive_texture_loads_both(self):
        self._import("shared.x3d", _shape("S", """
<PhysicalMaterial DEF='MA' baseColor='1 1 1' emissiveColor='1 1 1'>
  <ImageTexture DEF='T' containerField='baseTexture' url='"tex.png"'/>
  <ImageTexture USE='T' containerField='emissiveTexture'/>
</PhysicalMaterial>"""))
        tree = self._mat("MA").node_tree
        bsdf = _principled(self._mat("MA"))
        base = bsdf.inputs["Base Color"]
        emission = bsdf.inputs["Emission Color"]
        self.assertTrue(base.is_linked, "baseTexture was dropped")
        self.assertTrue(emission.is_linked, "emissiveTexture was dropped")
        self.assertEqual(base.links[0].from_node.type, 'TEX_IMAGE')
        self.assertEqual(emission.links[0].from_node.type, 'TEX_IMAGE')
        self.assertTrue(all(n.image is not None for n in tree.nodes if n.type == 'TEX_IMAGE'))

    def test_use_before_def_order_still_loads(self):
        # the USE'd texture is met first when it sits under the first slot
        self._import("shared2.x3d", _shape("S", """
<PhysicalMaterial DEF='MB' baseColor='1 1 1'>
  <ImageTexture DEF='T2' containerField='emissiveTexture' url='"tex.png"'/>
  <ImageTexture USE='T2' containerField='baseTexture'/>
</PhysicalMaterial>"""))
        bsdf = _principled(self._mat("MB"))
        self.assertTrue(bsdf.inputs["Base Color"].is_linked)
        self.assertTrue(bsdf.inputs["Emission Color"].is_linked)

    # D10: baseColor x texture

    def test_physical_base_texture_is_multiplied_by_base_colour(self):
        self._import("tint.x3d", _shape("S", f"""
<PhysicalMaterial DEF='MC' baseColor='{TINT[0]} {TINT[1]} {TINT[2]}'><ImageTexture containerField='baseTexture' url='"tex.png"'/></PhysicalMaterial>"""))
        socket = _principled(self._mat("MC")).inputs["Base Color"]
        a, b = _multiplied_by(socket)
        self.assertTrue(a.is_linked and a.links[0].from_node.type == 'TEX_IMAGE')
        for got, want in zip(b.default_value[:3], (0.06, 0.5, 0.48)):
            self.assertAlmostEqual(got, want, places=5)     # PhysicalMaterial colours are linear: kept as they are
        for got, want in zip(socket.default_value[:3], TINT):
            self.assertAlmostEqual(got, want, places=5)     # where the X3D export reads baseColor

    def test_white_base_colour_adds_no_node(self):
        self._import("white.x3d", _shape("S", """
<PhysicalMaterial DEF='MD'><ImageTexture containerField='baseTexture' url='"tex.png"'/></PhysicalMaterial>"""
                                        .replace("<PhysicalMaterial DEF='MD'>", "<PhysicalMaterial DEF='MD' baseColor='1 1 1'>")))
        mat = self._mat("MD")
        self.assertEqual(_principled(mat).inputs["Base Color"].links[0].from_node.type, 'TEX_IMAGE')
        self.assertFalse(any(n.bl_idname == "ShaderNodeMix" for n in mat.node_tree.nodes))

    def test_classic_diffuse_is_multiplied_into_the_texture(self):
        self._import("classic.x3d", _shape("S", """
<Material DEF='ME' diffuseColor='0.5 0.25 0.1'/><ImageTexture url='"tex.png"'/>"""), color_space='AS_IS')
        socket = _principled(self._mat("ME")).inputs["Base Color"]
        a, b = _multiplied_by(socket)
        self.assertEqual(a.links[0].from_node.type, 'TEX_IMAGE')
        for got, want in zip(b.default_value[:3], (0.5, 0.25, 0.1)):
            self.assertAlmostEqual(got, want, places=5)

    def test_emissive_texture_is_multiplied_by_emissive_colour_and_reaches_the_glb(self):
        import bpy
        self._import("emis.x3d", _shape("S", """
<PhysicalMaterial DEF='MK' baseColor='1 1 1' emissiveColor='0.35 0.2 0.1'><ImageTexture containerField='emissiveTexture' url='"tex.png"'/></PhysicalMaterial>"""))
        socket = _principled(self._mat("MK")).inputs["Emission Color"]
        a, b = _multiplied_by(socket)
        self.assertEqual(a.links[0].from_node.type, 'TEX_IMAGE')
        for got, want in zip(b.default_value[:3], (0.35, 0.2, 0.1)):
            self.assertAlmostEqual(got, want, places=5)
        out = os.path.join(self.tmpdir, "emis.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format='GLB')
        with open(out, "rb") as f:
            f.read(12)
            length, kind = struct.unpack("<II", f.read(8))
            doc = json.loads(f.read(length))
        for got, want in zip(doc["materials"][0]["emissiveFactor"], (0.35, 0.2, 0.1)):
            self.assertAlmostEqual(got, want, places=4)

    def test_physical_colour_node_is_multiplied_by_base_colour(self):
        self._import("vcol.x3d", _shape(
            "S", f"<PhysicalMaterial DEF='MF' baseColor='{TINT[0]} {TINT[1]} {TINT[2]}'/>",
            QUAD.format(colour="<Color color='1 1 1 1 1 1 1 1 1 1 1 1'/>")))
        mat = next(m for m in __import__("bpy").data.materials if m.name.startswith("MF") and m.name.endswith("_colour"))
        socket = _principled(mat).inputs["Base Color"]
        a, b = _multiplied_by(socket)
        self.assertEqual(a.links[0].from_node.type, 'VERTEX_COLOR')
        for got, want in zip(b.default_value[:3], TINT):
            self.assertAlmostEqual(got, want, places=5)

    def test_physical_texture_and_colour_node_use_one_factor(self):
        self._import("both.x3d", _shape(
            "S", f"<PhysicalMaterial DEF='MG' baseColor='{TINT[0]} {TINT[1]} {TINT[2]}'><ImageTexture containerField='baseTexture' url='\"tex.png\"'/></PhysicalMaterial>",
            QUAD.format(colour="<Color color='1 1 1 1 1 1 1 1 1 1 1 1'/>")))
        mat = next(m for m in __import__("bpy").data.materials if m.name.startswith("MG") and m.name.endswith("_colour"))
        tree = mat.node_tree
        mixes = [n for n in tree.nodes if n.bl_idname == "ShaderNodeMix"]
        constants = [tuple(round(c, 4) for c in b.default_value[:3]) for n in mixes
                     for a, b in [tuple(s for s in n.inputs if s.type == 'RGBA')] if not b.is_linked]
        self.assertEqual(constants, [TINT])             # once, not twice

    def test_glb_carries_the_base_colour_factor(self):
        import bpy
        self._import("glb.x3d", "\n".join([
            _shape("Textured", f"<PhysicalMaterial DEF='MH' baseColor='{TINT[0]} {TINT[1]} {TINT[2]}'><ImageTexture containerField='baseTexture' url='\"tex.png\"'/></PhysicalMaterial>"),
            _shape("Coloured", f"<PhysicalMaterial DEF='MI' baseColor='{TINT[0]} {TINT[1]} {TINT[2]}'/>",
                   QUAD.format(colour="<Color color='1 1 1 1 1 1 1 1 1 1 1 1'/>")),
            _shape("White", "<PhysicalMaterial DEF='MJ' baseColor='1 1 1'><ImageTexture containerField='baseTexture' url='\"tex.png\"'/></PhysicalMaterial>"),
        ]))
        out = os.path.join(self.tmpdir, "out.glb")
        bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_vertex_color='MATERIAL')
        with open(out, "rb") as f:
            f.read(12)
            length, kind = struct.unpack("<II", f.read(8))
            doc = json.loads(f.read(length))
        factors = {m["name"].split(".")[0]: m["pbrMetallicRoughness"].get("baseColorFactor", [1, 1, 1, 1]) for m in doc["materials"]}
        for name in ("MH", "MI_colour"):
            for got, want in zip(factors[name][:3], TINT):
                self.assertAlmostEqual(got, want, places=4, msg=name)
        self.assertEqual([round(c, 4) for c in factors["MJ"][:3]], [1.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
