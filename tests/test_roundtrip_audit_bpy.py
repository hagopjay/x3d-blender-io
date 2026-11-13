# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Round-trip audit on a probe, without a browser: the add-on's import (defaults) and X3D 4.0 export (defaults), and the
Blender glTF export of the same scene, through tools/fidelity_rig/roundtrip_audit.py. Under the default sRGB colour space
the classic Material colours of the p2 probe come back (as linear PhysicalMaterial factors) to within the 6-decimal text
the writer uses, and the glb's baseColorFactor is the original colour converted sRGB -> linear. Under AS_IS the same
check reports the error the audit exists to show. Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_roundtrip_audit_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    import numpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

RIG = Path(__file__).resolve().parents[1] / "tools" / "fidelity_rig"
PROBE = RIG / "probes" / "p2-point-classic.x3d"


@unittest.skipUnless(HAVE_BPY, "bpy (and numpy) are not available")
class RoundTripAuditTests(unittest.TestCase):

    def setUp(self):
        import bpy
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_roundtrip_audit_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(RIG))
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _round_trip(self, color_space):
        import bpy
        import roundtrip_audit as ra
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(PROBE), color_space=color_space), {"FINISHED"})
        out_x3d = os.path.join(self.tmpdir, f"re_{color_space}.x3d")
        out_glb = os.path.join(self.tmpdir, f"re_{color_space}.glb")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out_x3d, x3d_version="X3D40"), {"FINISHED"})
        self.assertEqual(bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_renderable=True), {"FINISHED"})
        orig = ra.parse(str(PROBE))
        return ra.colour_audit(orig, ra.parse(out_x3d)), ra.glb_audit(orig, out_glb), ra.parse(out_x3d)

    def test_srgb_default_round_trips_classic_colours_and_the_glb_factor(self):
        audit, glb, re_root = self._round_trip("SRGB")
        self.assertTrue(audit["shapes"]["ordered"])
        self.assertLess(audit["fields"]["Material.diffuseColor"]["ordered_max_abs"], 1e-4)
        self.assertEqual(audit["fields"]["Material.diffuseColor"]["convention_change"], {"display->linear": 3})
        self.assertEqual(audit["fields"]["Material.specularColor"]["dropped"], 3)   # PhysicalMaterial has no specularColor
        self.assertLess(glb["base"]["orig_to_glb_max"], 1e-4)
        self.assertEqual(audit["material_classes"]["re"], {"PhysicalMaterial": 3})

    def test_as_is_shows_the_error_the_audit_is_for(self):
        audit, glb, _ = self._round_trip("AS_IS")
        # 0.8 written unchanged under PhysicalMaterial (linear) is drawn as sRGB 0.906
        self.assertAlmostEqual(audit["fields"]["Material.diffuseColor"]["ordered_max_abs"], 0.1063, places=3)
        self.assertGreater(glb["base"]["orig_to_glb_max"], 0.15)   # glb baseColorFactor 0.8 against the expected linear 0.604


if __name__ == "__main__":
    unittest.main()
