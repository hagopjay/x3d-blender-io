# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Collection instances (Empty with instance_collection) are written as one DEF'd Group and USE'd after.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_collection_instances_bpy
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


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportCollectionInstanceTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_collection_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene

    def _library(self, name="Tree", offset=(0, 0, 0)):
        """A collection of a trunk and a crown that is not linked to the scene (an asset library)."""
        collection = bpy.data.collections.new(name)
        collection.instance_offset = offset
        mesh = bpy.data.meshes.new("Block")
        mesh.from_pydata([(-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0), (-.5, -.5, 1), (.5, -.5, 1),
                          (.5, .5, 1), (-.5, .5, 1)], [], [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                                                          (2, 3, 7, 6), (3, 0, 4, 7)])
        for part, z in (("Trunk", 0.0), ("Crown", 1.0)):
            obj = bpy.data.objects.new(part, mesh)
            obj.location = (0, 0, z)
            collection.objects.link(obj)
        return collection

    def _place(self, collection, name, location):
        empty = bpy.data.objects.new(name, None)
        empty.instance_type = "COLLECTION"
        empty.instance_collection = collection
        empty.location = location
        self.scene.collection.objects.link(empty)
        return empty

    def _export(self):
        path = os.path.join(self.tmpdir, "out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return ET.parse(path).getroot(), path

    def test_three_copies_write_the_content_once(self):
        tree = self._library()
        for index in range(3):
            self._place(tree, f"Tree{index}", (index * 4, 0, 0))
        root, _path = self._export()
        groups = [g for g in root.iter("Group") if g.get("DEF") == "CO_Tree"]
        uses = [g for g in root.iter("Group") if g.get("USE") == "CO_Tree"]
        self.assertEqual((len(groups), len(uses)), (1, 2))
        self.assertEqual(len(list(groups[0].iter("Shape"))), 2)           # trunk and crown, written once
        self.assertEqual(len(list(root.iter("Shape"))), 2)
        self.assertEqual(len([t for t in root.iter("Transform") if (t.get("DEF") or "").startswith("OB_Tree")]), 3 + 2)

    def test_members_sit_at_their_place_in_the_collection_frame(self):
        tree = self._library(offset=(0, 0, 0))
        self._place(tree, "Tree0", (10, 0, 0))
        root, _path = self._export()
        members = {t.get("DEF"): [float(v) for v in t.get("translation").split()]
                   for t in root.iter("Transform") if "." in (t.get("DEF") or "") or "Crown" in (t.get("DEF") or "")}
        crown = next(v for k, v in members.items() if "Crown" in k)
        self.assertAlmostEqual(crown[2], 1.0, places=4)                    # the members stay in Blender axes; the Empty carries the Y-up turn
        self.assertAlmostEqual(crown[0], 0.0, places=4)

    def test_instance_offset_moves_the_origin(self):
        tree = self._library(offset=(0, 0, 1))
        self._place(tree, "Tree0", (0, 0, 0))
        root, _path = self._export()
        crown = next(t for t in root.iter("Transform") if "Crown" in (t.get("DEF") or ""))
        self.assertAlmostEqual(float(crown.get("translation").split()[2]), 0.0, places=4)   # 1 - offset 1

    def test_output_validates(self):
        try:
            import x3d  # noqa: F401
        except ImportError:
            self.skipTest("x3d package not installed")
        tree = self._library()
        self._place(tree, "A", (0, 0, 0))
        self._place(tree, "B", (4, 0, 0))
        _root, path = self._export()
        import sys
        from test_roundtrip_bpy import SOURCE_DIR
        sys.path.insert(0, str(SOURCE_DIR))
        from validate import validate_with_x3d_py
        result = validate_with_x3d_py(path)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()
