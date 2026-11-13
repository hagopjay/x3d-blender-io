# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An imported Inline is written relative to the folder the export goes to (round-trip audit D3).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_inline_bpy
"""

from __future__ import annotations

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

PART = ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>"
        "<Shape><Appearance><Material diffuseColor='0.8 0.2 0.2'/></Appearance><Box/></Shape></Scene></X3D>\n")
STAGE = ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>"
         "<Inline url='\"{url}\"'/></Scene></X3D>\n")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportInlineTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_inline_export_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.src = os.path.join(self.tmpdir, "src")
        self.out = os.path.join(self.tmpdir, "elsewhere", "deeper")
        os.makedirs(os.path.join(self.src, "parts"))
        os.makedirs(self.out)
        with open(os.path.join(self.src, "parts", "part.x3d"), "w", encoding="utf-8") as handle:
            handle.write(PART)

    def _import_stage(self, url):
        path = os.path.join(self.src, "stage.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(STAGE.format(url=url))
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})

    def _export(self, **options):
        path = os.path.join(self.out, "stage_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        return ET.parse(path).getroot(), path

    def test_the_inline_url_points_at_the_target_from_the_new_folder(self):
        self._import_stage("parts/part.x3d")
        root, path = self._export()
        url = root.find(".//Inline").attrib["url"].strip('"')
        self.assertEqual(url, "../../src/parts/part.x3d")
        self.assertTrue(os.path.isfile(os.path.join(self.out, url)))
        self.assertEqual(os.listdir(self.out), ["stage_out.x3d"], "the export copied files it was not asked to")

    def test_the_url_is_unchanged_when_the_file_is_exported_beside_its_target(self):
        self._import_stage("parts/part.x3d")
        path = os.path.join(self.src, "stage_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        self.assertEqual(ET.parse(path).getroot().find(".//Inline").attrib["url"].strip('"'), "parts/part.x3d")

    def test_a_missing_target_keeps_its_url_and_says_so_in_the_file(self):
        self._import_stage("parts/missing.x3d")
        root, path = self._export()
        self.assertEqual(root.find(".//Inline").attrib["url"].strip('"'), "parts/missing.x3d")
        info = [m.attrib["content"] for m in root.iter("meta") if m.attrib.get("name") == "info"]
        self.assertTrue(any("missing.x3d" in text and "not found" in text for text in info), info)


if __name__ == "__main__":
    unittest.main()
