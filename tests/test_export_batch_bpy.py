# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Batch export writes one file per collection, object, hierarchy or scene, holding that item and nothing else.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_batch_bpy
"""

from __future__ import annotations

import os
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


def _transforms(path):
    if path.endswith(".x3dz"):
        import gzip
        with gzip.open(path, "rb") as handle:
            root = ET.fromstring(handle.read())
    else:
        root = ET.parse(path).getroot()
    return sorted(node.attrib["DEF"][3:] for node in root.iter("Transform") if node.attrib.get("DEF", "").startswith("OB_"))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportBatchTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_batch_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        self.red = bpy.data.collections.new("Red")
        self.blue = bpy.data.collections.new("Blue")
        self.inner = bpy.data.collections.new("Inner")
        scene.collection.children.link(self.red)
        scene.collection.children.link(self.blue)
        self.blue.children.link(self.inner)          # Blue holds objects only through its child
        self._cube("RedCube", self.red, 0)
        self._cube("InnerCube", self.inner, 3)
        self._cube("Loose", scene.collection, 6)     # directly in the scene collection
        other = bpy.data.scenes.new("Other")
        self._cube("OtherCube", other.collection, 9)  # in another scene only

    def _cube(self, name, collection, x):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        obj.location.x = x
        collection.objects.link(obj)
        return obj

    def _batch(self, mode, filename="scene.x3d", **options):
        out = os.path.join(self.tmpdir, mode.lower())
        os.makedirs(out)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=os.path.join(out, filename), x3d_version="X3D40",
                                                  use_selection=False, batch_mode=mode, **options), {"FINISHED"})
        return {name: _transforms(os.path.join(out, name)) for name in sorted(os.listdir(out))
                if name.endswith((".x3d", ".x3dz"))}

    def test_collection_files_hold_only_their_collection(self):
        files = self._batch("COLLECTION")
        self.assertEqual(files, {"scene_Blue.x3d": ["InnerCube"], "scene_Red.x3d": ["RedCube"]})

    def test_object_batch_covers_the_current_scene_only(self):
        files = self._batch("OBJECT")
        self.assertEqual(set(files), {"scene_RedCube.x3d", "scene_InnerCube.x3d", "scene_Loose.x3d"})
        for name, transforms in files.items():
            self.assertEqual(transforms, [name[len("scene_"):-len(".x3d")]])

    def test_hierarchy_batch_covers_the_current_scene_only(self):
        self.assertEqual(set(self._batch("OBJECT_HIERARCHY")),
                         {"scene_RedCube.x3d", "scene_InnerCube.x3d", "scene_Loose.x3d"})

    def test_compressed_batch_keeps_the_file_prefix(self):
        files = self._batch("OBJECT", filename="scene.x3dz", use_compress=True)
        self.assertEqual(set(files), {"scene_RedCube.x3dz", "scene_InnerCube.x3dz", "scene_Loose.x3dz"})
        self.assertEqual(files["scene_Loose.x3dz"], ["Loose"])

    def test_scene_batch_writes_every_scene(self):
        files = self._batch("SCENE")
        self.assertEqual(files["scene_Scene.x3d"], ["InnerCube", "Loose", "RedCube"])
        self.assertEqual(files["scene_Other.x3d"], ["OtherCube"])


if __name__ == "__main__":
    unittest.main()
