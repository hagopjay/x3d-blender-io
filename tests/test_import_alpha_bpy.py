# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: a texture's alpha makes the surface transparent, as X_ITE draws it.

X3D 4.0 draws alpha = (1 - transparency) x texture alpha. The importer used the texture's
alpha only for a PhysicalMaterial with alphaMode BLEND or MASK, and there without the
material's transparency, so with alphaMode AUTO (the default) an RGBA glow or halo on a
quad, and any UnlitMaterial, rendered as an opaque rectangle. Now the colour texture's
alpha (an UnlitMaterial's emissive texture) feeds the Principled Alpha, times
1 - transparency in a Multiply node. With AUTO only an image with a pixel that is not
opaque counts, so files without texture alpha import as before.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_alpha_bpy
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


def _write_png(path: str, pixels, alpha: bool):
    """A tiny 2 x 2 PNG (RGBA when ``alpha``, else RGB), written without Pillow."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    rows = [pixels[0:2], pixels[2:4]]
    raw = b"".join(b"\x00" + b"".join(bytes(p if alpha else p[:3]) for p in row) for row in rows)
    colour_type = 6 if alpha else 2
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, colour_type, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _shape(name: str, appearance: str) -> str:
    return f"<Shape DEF='{name}'><Appearance{appearance}</Appearance><Rectangle2D size='1 1'/></Shape>"


def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')


GLOW = [(255, 160, 80, 255), (255, 160, 80, 128), (255, 160, 80, 32), (255, 160, 80, 0)]
SOLID = [(200, 200, 200, 255)] * 4


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportTextureAlphaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import bpy
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_alpha_")
        _register_extension(cls.tmpdir)
        _write_png(os.path.join(cls.tmpdir, "glow.png"), GLOW, alpha=True)
        _write_png(os.path.join(cls.tmpdir, "solid_rgba.png"), SOLID, alpha=True)
        _write_png(os.path.join(cls.tmpdir, "solid_rgb.png"), SOLID, alpha=False)

        def tex(url, field="emissiveTexture"):
            return f"<ImageTexture containerField='{field}' url='\"{url}\"'/>"
        body = "\n".join([
            _shape("UnlitFaded", f"><UnlitMaterial DEF='MA_UnlitFaded' transparency='0.25'>{tex('glow.png')}</UnlitMaterial>"),
            _shape("UnlitGlow", f"><UnlitMaterial DEF='MA_UnlitGlow'>{tex('glow.png')}</UnlitMaterial>"),
            _shape("UnlitSolidRGBA", f"><UnlitMaterial DEF='MA_UnlitSolidRGBA'>{tex('solid_rgba.png')}</UnlitMaterial>"),
            _shape("UnlitSolidRGB", f"><UnlitMaterial DEF='MA_UnlitSolidRGB'>{tex('solid_rgb.png')}</UnlitMaterial>"),
            _shape("PhysicalGlow", f"><PhysicalMaterial DEF='MA_PhysicalGlow' transparency='0.5'>"
                                   f"{tex('glow.png', 'baseTexture')}</PhysicalMaterial>"),
            _shape("PhysicalMask", f" alphaMode='MASK' alphaCutoff='0.4'><PhysicalMaterial DEF='MA_PhysicalMask' transparency='0.5'>"
                                   f"{tex('glow.png', 'baseTexture')}</PhysicalMaterial>"),
        ])
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.path = os.path.join(cls.tmpdir, "alpha.x3d")
        with open(cls.path, "w", encoding="utf-8") as f:
            f.write(HEADER + body + FOOTER)
        assert bpy.ops.import_scene.x3d(filepath=cls.path) == {"FINISHED"}
        cls.mats = {m.name: m for m in bpy.data.materials}

    def _alpha(self, name):
        return _principled(self.mats[name]).inputs["Alpha"]

    def test_unlit_texture_alpha_times_transparency(self):
        socket = self._alpha("MA_UnlitFaded")
        self.assertTrue(socket.is_linked)
        multiply = socket.links[0].from_node
        self.assertEqual((multiply.bl_idname, multiply.operation), ("ShaderNodeMath", 'MULTIPLY'))
        self.assertAlmostEqual(multiply.inputs[1].default_value, 0.75, places=5)
        source = multiply.inputs[0].links[0]
        self.assertEqual(source.from_node.type, 'TEX_IMAGE')
        self.assertEqual(source.from_socket.name, "Alpha")
        self.assertTrue(source.from_node.image.filepath.endswith("glow.png"), source.from_node.image.filepath)
        # 1 - transparency stays on the socket, where the exporter reads it
        self.assertAlmostEqual(socket.default_value, 0.75, places=5)
        self.assertEqual(self.mats["MA_UnlitFaded"].surface_render_method, 'BLENDED')

    def test_unlit_texture_alpha_alone_links_directly(self):
        socket = self._alpha("MA_UnlitGlow")
        self.assertTrue(socket.is_linked)
        self.assertEqual(socket.links[0].from_node.type, 'TEX_IMAGE')
        self.assertEqual(socket.links[0].from_socket.name, "Alpha")
        self.assertEqual(self.mats["MA_UnlitGlow"].surface_render_method, 'BLENDED')

    def test_opaque_images_stay_opaque(self):
        for name in ("MA_UnlitSolidRGBA", "MA_UnlitSolidRGB"):
            with self.subTest(name=name):
                self.assertFalse(self._alpha(name).is_linked)
                self.assertNotEqual(self.mats[name].surface_render_method, 'BLENDED')

    def test_physical_base_texture_alpha_with_auto(self):
        socket = self._alpha("MA_PhysicalGlow")
        self.assertTrue(socket.is_linked)
        multiply = socket.links[0].from_node
        self.assertEqual(multiply.operation, 'MULTIPLY')
        self.assertAlmostEqual(multiply.inputs[1].default_value, 0.5, places=5)
        self.assertEqual(multiply.inputs[0].links[0].from_node.type, 'TEX_IMAGE')
        self.assertEqual(self.mats["MA_PhysicalGlow"].surface_render_method, 'BLENDED')

    def test_mask_cuts_the_product(self):
        socket = self._alpha("MA_PhysicalMask")
        self.assertTrue(socket.is_linked)
        cut = socket.links[0].from_node
        self.assertEqual((cut.bl_idname, cut.operation), ("ShaderNodeMath", 'GREATER_THAN'))
        self.assertAlmostEqual(cut.inputs[1].default_value, 0.4, places=5)
        multiply = cut.inputs[0].links[0].from_node
        self.assertEqual(multiply.operation, 'MULTIPLY')
        self.assertEqual(multiply.inputs[0].links[0].from_node.type, 'TEX_IMAGE')
        self.assertEqual(self.mats["MA_PhysicalMask"].surface_render_method, 'DITHERED')

    def test_export_keeps_transparency_and_texture(self):
        import bpy
        out = os.path.join(self.tmpdir, "alpha_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        root = ET.parse(out).getroot()
        # the exporter prefixes its own MA_ and may write the unlit surface as a PhysicalMaterial
        apps = {}
        for app in root.iter("Appearance"):
            for m in app:
                if m.tag in ("UnlitMaterial", "PhysicalMaterial"):
                    apps[(m.attrib.get("DEF") or "").split("MA_")[-1]] = (app, m)
        app, material = apps["UnlitFaded"]
        self.assertAlmostEqual(float(material.attrib.get("transparency", "0")), 0.25, places=3)
        self.assertEqual(app.attrib.get("alphaMode"), "BLEND")
        self.assertTrue(any(c.tag == "ImageTexture" for c in material.iter()), ET.tostring(material, encoding="unicode"))
        self.assertIsNone(apps["UnlitSolidRGBA"][0].attrib.get("alphaMode"))


if __name__ == "__main__":
    unittest.main()
