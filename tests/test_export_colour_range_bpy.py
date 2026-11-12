# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exporter: per-vertex colours stay inside SFColorRGBA's [0, 1] on the X3D 4.0 path.

A FLOAT_COLOR attribute can hold channels past 1 or below 0 (molecularnodes' pLDDT palette writes a red of
1.000169); the X3D validator then refuses the whole ColorRGBA. Each channel is now clamped, alpha included. The
X3D 3.3 writer reads only the byte colours of mesh.vertex_colors, which cannot leave [0, 1].

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_colour_range_bpy
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

COLOURS = [(1.000169, 0.5, 0.0, 1.0), (-0.01, 0.25, 0.75, 1.0), (1.6, 1.2, 0.5, 1.0), (0.2, 0.4, 0.6, 1.0)]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportColourRangeTests(unittest.TestCase):

    def _export(self, version, domain):
        import bpy
        tmpdir = tempfile.mkdtemp(prefix="x3d_colour_range_")
        _register_extension(tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mesh = bpy.data.meshes.new("Plddt")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        attribute = mesh.color_attributes.new("Color", 'FLOAT_COLOR', domain)
        for index, item in enumerate(attribute.data):
            item.color = COLOURS[index % len(COLOURS)]
        mesh.color_attributes.active_color = attribute
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Plddt", mesh))
        path = os.path.join(tmpdir, "colours_%s_%s.x3d" % (version, domain))
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False),
                         {"FINISHED"})
        nodes = ET.parse(path).getroot().findall(".//ColorRGBA")
        self.assertTrue(nodes, "no ColorRGBA written (%s, %s)" % (version, domain))
        return [float(v) for node in nodes for v in node.attrib["color"].replace(",", " ").split()]

    def test_every_channel_is_inside_zero_one(self):
        for version in ("X3D40",):
            for domain in ("POINT", "CORNER"):
                with self.subTest(version=version, domain=domain):
                    values = self._export(version, domain)
                    self.assertTrue(all(0.0 <= v <= 1.0 for v in values),
                                    [v for v in values if not 0.0 <= v <= 1.0])
                    self.assertIn(1.0, values)       # 1.000169 and 1.6 became 1, not dropped
                    self.assertIn(0.0, values)       # -0.01 became 0


if __name__ == "__main__":
    unittest.main()
