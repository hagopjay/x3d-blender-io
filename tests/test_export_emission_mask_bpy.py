# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export: an emission strength driven by a procedural mask must not light the whole surface.

The LUMEN Interference Atelier drives Principled Emission Strength from a contour mask built from the world height
(Geometry > Separate XYZ > Math). The resolver cannot read geometry, took the Math chain's first input (26 for an
'altitude x 26' node) and exported emissiveColor at full strength over the whole sheet, so a teal-to-copper surface
came out as a self-lit pastel in X_ITE. An unreadable strength now leaves the emission out.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_emission_mask_bpy
"""

from __future__ import annotations

import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension


def _material(driven: bool, strength: float = 2.0):
    mat = bpy.data.materials.new("emit_test_%s" % driven)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Emission Color"].default_value = (0.18, 0.65, 0.5, 1.0)
    bsdf.inputs["Emission Strength"].default_value = strength
    if driven:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = 26.0
        gt = nt.nodes.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
        nt.links.new(sep.outputs["Z"], mul.inputs[0])
        nt.links.new(mul.outputs["Value"], gt.inputs[0])
        nt.links.new(gt.outputs["Value"], bsdf.inputs["Emission Strength"])
    return mat


@unittest.skipUnless(HAVE_BPY, "needs bpy")
class EmissionMaskTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        _register_extension(self._tmp.name)
        from io_scene_x3d.material import analyze_material
        self.analyze = analyze_material

    def test_geometry_driven_strength_leaves_emission_out(self):
        info = self.analyze(_material(driven=True))
        self.assertEqual(tuple(info.emissive_color[:3]), (0.0, 0.0, 0.0))

    def test_constant_strength_still_exports(self):
        info = self.analyze(_material(driven=False, strength=2.0))
        self.assertAlmostEqual(info.emissive_color[1], 1.3)


if __name__ == "__main__":
    unittest.main()
