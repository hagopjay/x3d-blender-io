# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Round trip of an IndexedLineSet: the X3D 4.0 export keeps lines.

An IndexedLineSet imports as a Blender curve; its evaluated mesh has edges and no faces, and the
export used to write nothing for it, so the 12 evidence-graded travel legs of the Shroud "journey"
scene vanished from every export.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_lines_bpy
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

SCENE = """<?xml version='1.0' encoding='UTF-8'?>
<X3D profile='Immersive' version='4.0'><Scene>
<Shape>
  <Appearance><Material emissiveColor='0 1 0'/></Appearance>
  <IndexedLineSet coordIndex='0 1 2 -1 3 4 -1'>
    <Coordinate point='0 0 0, 1 0 0, 1 1 0, 0 0 1, 0 1 1'/>
  </IndexedLineSet>
</Shape>
</Scene></X3D>
"""


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class IndexedLineSetRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_lines_")
        _register_extension(cls.tmpdir)

    def _roundtrip(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        src = os.path.join(self.tmpdir, "lines.x3d")
        with open(src, "w", encoding="utf-8") as f:
            f.write(SCENE)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        out = os.path.join(self.tmpdir, "lines_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return out

    def test_export_keeps_both_polylines(self):
        out = self._roundtrip()
        nodes = list(ET.parse(out).getroot().iter("IndexedLineSet"))
        self.assertEqual(len(nodes), 1)
        index = [int(v) for v in nodes[0].get("coordIndex").split()]
        self.assertEqual(index.count(-1), 2)
        lengths = [len(part.split()) for part in " ".join(map(str, index)).split("-1")[:2]]
        self.assertEqual(lengths, [3, 2])
        coord = nodes[0].find("Coordinate").get("point").split()
        self.assertEqual(len(coord), 5 * 3)

    def test_reimport_gives_a_curve_with_two_splines(self):
        import bpy
        out = self._roundtrip()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=out), {"FINISHED"})
        curves = [o for o in bpy.context.scene.objects if o.type == "CURVE"]
        self.assertEqual(len(curves), 1)
        self.assertEqual(len(curves[0].data.splines), 2)


if __name__ == "__main__":
    unittest.main()
