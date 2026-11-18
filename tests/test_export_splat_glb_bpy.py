# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A splat object with x3d_splat_glb exports as a KHR_gaussian_splatting glb beside the file plus an Inline.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_splat_glb_bpy
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportSplatGlbTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_splat_glb_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR.parent / "tools"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        from splat_fixture import build_splat_fixture
        self.helix = build_splat_fixture(count=24)["helix"]

    def _export(self, version="X3D40"):
        path = os.path.join(self.tmpdir, "scene.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False),
                         {"FINISHED"})
        return ET.parse(path).getroot()

    def _glb_json(self, name="HelixSplats.splats.glb"):
        with open(os.path.join(self.tmpdir, name), "rb") as handle:
            data = handle.read()
        self.assertEqual(data[:4], b"glTF")
        length = struct.unpack_from("<I", data, 12)[0]
        return json.loads(data[20:20 + length])

    def test_inline_and_glb_replace_the_splat_node(self):
        self.helix.data["x3d_splat_glb"] = True
        root = self._export()
        inline = root.find(".//Inline")
        self.assertEqual(inline.get("url").strip('"'), "HelixSplats.splats.glb")
        self.assertIsNone(root.find(".//PointSet"))
        document = self._glb_json()
        self.assertEqual(document["extensionsUsed"], ["KHR_gaussian_splatting"])
        self.assertEqual(document["accessors"][0]["count"], 24)

    def test_higher_degree_colour_is_dropped_with_a_diagnostic(self):
        self.helix.data["x3d_splat_glb"] = True                  # the fixture carries degree-1 coefficients
        root = self._export()
        info = " ".join(m.get("content", "") for m in root.iter("meta"))
        self.assertIn("spherical harmonics above degree 0 are not written to the glb", info)
        self.assertNotIn("KHR_gaussian_splatting:SH_DEGREE_1_COEF_0", self._glb_json()["meshes"][0]["primitives"][0]["attributes"])

    def test_without_the_property_nothing_changes(self):
        root = self._export("X3D41")
        self.assertIsNotNone(root.find(".//GaussianSplats"))
        self.assertIsNone(root.find(".//Inline"))
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, "HelixSplats.splats.glb")))

    def test_output_validates(self):
        try:
            import x3d  # noqa: F401
        except ImportError:
            self.skipTest("x3d package not installed")
        self.helix.data["x3d_splat_glb"] = True
        self._export()
        sys.path.insert(0, str(SOURCE_DIR))
        from validate import validate_with_x3d_py
        result = validate_with_x3d_py(os.path.join(self.tmpdir, "scene.x3d"))
        self.assertTrue(result.valid, result.errors)


if __name__ == "__main__":
    unittest.main()
