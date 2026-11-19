# SPDX-License-Identifier: GPL-3.0-or-later
"""Foreign Shape identities must survive the exporter's material-part heuristic."""
from __future__ import annotations

import atexit
import tempfile
import unittest
from pathlib import Path

try:
    import bpy
    HAVE_BPY = True
except ImportError:
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ForeignMaterialPartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addon = tempfile.TemporaryDirectory()
        _register_extension(cls.addon.name)
        # bpy keeps the package registered for later test modules, which may import more submodules lazily.
        atexit.register(cls.addon.cleanup)

    def _import(self, transform, geometry_prefix, named):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        shapes = []
        for i, identity in enumerate(("LeftPanel", "RightPanel")):
            attrs = f' DEF="{identity}"' if named else ""
            shapes.append(
                f'<Shape{attrs}><Appearance><Material/></Appearance>'
                f'<IndexedFaceSet DEF="{geometry_prefix}Panel_m{i}" coordIndex="0 1 2 -1">'
                '<Coordinate point="0 0 0 1 0 0 0 1 0"/></IndexedFaceSet></Shape>')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "foreign.x3d"
            source.write_text('<X3D version="4.0"><Scene>'
                              f'<Transform DEF="{transform}">{"".join(shapes)}</Transform>'
                              '</Scene></X3D>', encoding="utf-8")
            self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(source)), {"FINISHED"})
        return [o for o in bpy.context.scene.objects if o.type == 'MESH']

    def test_foreign_geometry_suffix_does_not_merge_anonymous_shapes(self):
        meshes = self._import("ForeignAssembly", "", False)
        self.assertEqual(len(meshes), 2)
        self.assertEqual({o.data["x3d_def"] for o in meshes}, {"Panel_m0", "Panel_m1"})
        self.assertEqual(len({o.parent for o in meshes}), 1)
        self.assertTrue(all(o.parent.type == 'EMPTY' and o.parent["x3d_def"] == "ForeignAssembly"
                            for o in meshes))

    def test_named_shapes_survive_exporter_looking_geometry_names(self):
        meshes = self._import("OB_Assembly", "ME_", True)
        self.assertEqual(len(meshes), 2)
        self.assertEqual({o["x3d_def"] for o in meshes}, {"LeftPanel", "RightPanel"})
        self.assertEqual({o.data["x3d_def"] for o in meshes}, {"ME_Panel_m0", "ME_Panel_m1"})
        self.assertEqual({o.parent.name for o in meshes}, {"Assembly"})


if __name__ == "__main__":
    unittest.main()
