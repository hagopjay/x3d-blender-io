# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D 4.0 export: creaseAngle comes back from the sharp edges instead of always being pi.

The importer turns ``creaseAngle`` into sharp edges, but the export wrote pi for any smooth mesh, so a welded box
with creaseAngle 0.35 left as fully smooth. Now the export writes just under the smallest dihedral angle among
the sharp edges (pi when nothing is sharp).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_crease_angle_bpy
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

CUBE = "-1 -1 -1 1 -1 -1 1 1 -1 -1 1 -1 -1 -1 1 1 -1 1 1 1 1 -1 1 1"
CUBE_INDEX = "0 3 2 1 -1 4 5 6 7 -1 0 1 5 4 -1 1 2 6 5 -1 2 3 7 6 -1 3 0 4 7 -1"


def _text(crease):
    return ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>\n"
            "<Shape><IndexedFaceSet creaseAngle='%s' coordIndex='%s'><Coordinate point='%s'/></IndexedFaceSet></Shape>\n"
            "</Scene></X3D>\n" % (crease, CUBE_INDEX, CUBE))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class CreaseAngleExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_crease_")
        _register_extension(cls.tmpdir)

    def _crease_after_round_trip(self, crease):
        src = os.path.join(self.tmpdir, "crease_src.x3d")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_text(crease))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        for polygon in [o for o in bpy.context.scene.objects if o.type == "MESH"][0].data.polygons:
            polygon.use_smooth = True
        out = os.path.join(self.tmpdir, "crease_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        with open(out, encoding="utf-8") as f:
            return float(re.search(r'creaseAngle="([^"]+)"', f.read()).group(1))

    def test_box_edges_stay_sharp(self):
        angle = self._crease_after_round_trip("0.35")
        self.assertAlmostEqual(angle, 1.5708 * 0.999, places=3)

    def test_wide_crease_stays_smooth(self):
        self.assertAlmostEqual(self._crease_after_round_trip("3.14159"), 3.141593, places=4)


if __name__ == "__main__":
    unittest.main()
