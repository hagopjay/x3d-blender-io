# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: an UnlitMaterial shows emissiveColor x emissiveTexture, as X_ITE draws it.

A texture linked straight into the Principled BSDF's Emission Color replaces the
socket's colour, so the glass of a warm lamp (emissiveColor 0.96 0.845 0.69 over a
glow texture) rendered as the bare texture. The importer now multiplies the texture
by the colour in a Mix node, keeps the colour on the socket for the exporter, and
adds no node when the colour is white.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_unlit_bpy
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
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
WARM = (0.96, 0.845, 0.69)


def _write_png(path: str, rgb=(250, 200, 150), size: int = 2):
    """A tiny opaque RGB PNG, written without Pillow."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _shape(name: str, material: str) -> str:
    return f"<Shape DEF='{name}'><Appearance>{material}</Appearance><Box size='1 1 1'/></Shape>"


def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportUnlitEmissiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import bpy
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_unlit_")
        _register_extension(cls.tmpdir)
        _write_png(os.path.join(cls.tmpdir, "glow.png"))
        tex = "<ImageTexture containerField='emissiveTexture' url='\"glow.png\"'/>"
        body = "\n".join([
            _shape("Tinted", f"<UnlitMaterial DEF='MA_Tinted' emissiveColor='{WARM[0]} {WARM[1]} {WARM[2]}'>{tex}</UnlitMaterial>"),
            _shape("White", f"<UnlitMaterial DEF='MA_White'>{tex}</UnlitMaterial>"),
            _shape("Flat", "<UnlitMaterial DEF='MA_Flat' emissiveColor='0.2 0.4 0.6'/>"),
        ])
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(cls.tmpdir, "unlit.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + body + FOOTER)
        assert bpy.ops.import_scene.x3d(filepath=path) == {"FINISHED"}
        cls.mats = {m.name: m for m in bpy.data.materials}

    def _emission(self, name):
        p = _principled(self.mats[name])
        return p.inputs.get("Emission Color") or p.inputs.get("Emission")

    def test_texture_times_colour(self):
        socket = self._emission("MA_Tinted")
        self.assertTrue(socket.is_linked)
        mix = socket.links[0].from_node
        self.assertEqual(mix.bl_idname, "ShaderNodeMix")
        self.assertEqual((mix.data_type, mix.blend_type), ('RGBA', 'MULTIPLY'))
        self.assertAlmostEqual(mix.inputs[0].default_value, 1.0)
        color_a, color_b = (s for s in mix.inputs if s.type == 'RGBA')
        self.assertTrue(color_a.is_linked)
        image_node = color_a.links[0].from_node
        self.assertEqual(image_node.type, 'TEX_IMAGE')
        self.assertTrue(image_node.image.filepath.endswith("glow.png"), image_node.image.filepath)
        for got, want in zip(color_b.default_value[:3], WARM):
            self.assertAlmostEqual(got, want, places=5)
        # the colour also stays on the socket, where the exporter reads it
        for got, want in zip(socket.default_value[:3], WARM):
            self.assertAlmostEqual(got, want, places=5)

    def test_white_colour_adds_no_node(self):
        socket = self._emission("MA_White")
        self.assertTrue(socket.is_linked)
        self.assertEqual(socket.links[0].from_node.type, 'TEX_IMAGE')
        self.assertFalse(any(n.bl_idname == "ShaderNodeMix" for n in self.mats["MA_White"].node_tree.nodes))

    def test_untextured_colour_unchanged(self):
        socket = self._emission("MA_Flat")
        self.assertFalse(socket.is_linked)
        for got, want in zip(socket.default_value[:3], (0.2, 0.4, 0.6)):
            self.assertAlmostEqual(got, want, places=5)

    def test_export_keeps_colour_and_texture(self):
        import bpy
        out = os.path.join(self.tmpdir, "unlit_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        root = ET.parse(out).getroot()
        mats = {n.attrib.get("DEF"): n for n in root.iter() if n.tag in ("UnlitMaterial", "PhysicalMaterial")}
        tinted = next(n for d, n in mats.items() if d and d.endswith("MA_Tinted"))   # the exporter prefixes its own MA_
        got = [float(v) for v in tinted.attrib["emissiveColor"].split()[:3]]
        for g, w in zip(got, WARM):
            self.assertAlmostEqual(g, w, places=3)
        self.assertTrue(any(c.tag == "ImageTexture" for c in tinted.iter()), ET.tostring(tinted, encoding="unicode"))


if __name__ == "__main__":
    unittest.main()
