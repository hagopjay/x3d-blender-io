# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Round-trip audit helpers (tools/fidelity_rig/roundtrip_audit.py): plain Python plus numpy, no Blender, no browser.

    cd tests && python -m unittest test_roundtrip_audit
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

RIG = Path(__file__).resolve().parents[1] / "tools" / "fidelity_rig"
sys.path.insert(0, str(RIG))
if np is not None:
    import roundtrip_audit as ra

ORIG = """<X3D version="4.0"><Scene>
<Viewpoint position="0 0 10"/>
<Shape><Appearance><Material diffuseColor="0.8 0.8 0.8" emissiveColor="0.2 0.1 0" specularColor="1 1 1"/></Appearance>
<IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0"/><Color color="0.5 0.5 0.5 0.2 0.4 0.8 1 0 0"/></IndexedFaceSet></Shape>
<Shape><Appearance><UnlitMaterial emissiveColor="0.5 0.25 0.75"/></Appearance><Box/></Shape>
</Scene></X3D>"""


def _re_export(base_encode):
    """What a correct 4.0 re-export looks like: classic colours become linear PhysicalMaterial factors (base_encode=srgb_to_linear),
    or pass through unchanged (identity) when the colour space was AS_IS."""
    def f(*v):
        return " ".join("%.6f" % x for x in base_encode(np.array(v)))
    return f"""<X3D version="4.0"><Scene>
<Viewpoint position="0 0 10"/>
<Shape><Appearance><PhysicalMaterial baseColor="{f(0.8, 0.8, 0.8)}" emissiveColor="{f(0.2, 0.1, 0)}"/></Appearance>
<IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0"/><Color color="{f(0.5, 0.5, 0.5)} {f(0.2, 0.4, 0.8)} {f(1, 0, 0)}"/></IndexedFaceSet></Shape>
<Shape><Appearance><UnlitMaterial emissiveColor="0.5 0.25 0.75"/></Appearance><Box/></Shape>
</Scene></X3D>"""


@unittest.skipIf(np is None, "numpy is not available")
class ColourAuditTests(unittest.TestCase):

    def test_srgb_curve_round_trips(self):
        x = np.linspace(0, 1, 11)
        self.assertLess(float(np.abs(ra.linear_to_srgb(ra.srgb_to_linear(x)) - x).max()), 1e-9)
        self.assertAlmostEqual(float(ra.srgb_to_linear(0.8)), 0.603827, places=5)

    def test_node_counts_and_diff(self):
        a = ra.node_counts(ra.parse(ORIG, text=True))
        b = ra.node_counts(ra.parse(_re_export(ra.srgb_to_linear), text=True))
        diff = ra.count_diff(a, b)
        self.assertIn("Material", diff["lost"])
        self.assertIn("PhysicalMaterial", diff["added"])
        self.assertNotIn("Scene", diff["rows"])

    def test_linear_physical_reexport_of_classic_colours_is_exact(self):
        audit = ra.colour_audit(ra.parse(ORIG, text=True), ra.parse(_re_export(ra.srgb_to_linear), text=True))
        self.assertTrue(audit["shapes"]["ordered"])
        base = audit["fields"]["Material.diffuseColor"]
        self.assertLess(base["ordered_max_abs"], 1e-5)
        self.assertEqual(base["convention_change"], {"display->linear": 1})
        self.assertLess(audit["fields"]["Material.emissiveColor"]["ordered_max_abs"], 1e-5)
        self.assertLess(audit["vertex"]["Color"]["orig_to_re_max"], 1e-4)
        self.assertEqual(audit["fields"]["UnlitMaterial.emissiveColor"]["ordered_max_abs"], 0.0)

    def test_specular_is_reported_dropped_not_as_an_error(self):
        audit = ra.colour_audit(ra.parse(ORIG, text=True), ra.parse(_re_export(ra.srgb_to_linear), text=True))
        spec = audit["fields"]["Material.specularColor"]
        self.assertEqual(spec["dropped"], 1)
        self.assertIsNone(spec["hausdorff_max_abs"])

    def test_as_is_passthrough_is_an_error_the_audit_sees(self):
        # a classic 0.8 written unchanged under PhysicalMaterial (linear) reads as sRGB 0.906: 0.1063 off
        audit = ra.colour_audit(ra.parse(ORIG, text=True), ra.parse(_re_export(lambda v: v), text=True))
        self.assertAlmostEqual(audit["fields"]["Material.diffuseColor"]["ordered_max_abs"], 0.10633, places=3)
        self.assertGreater(audit["vertex"]["Color"]["orig_to_re_max"], 0.1)

    def test_def_use_material_is_resolved(self):
        text = """<X3D><Scene>
<Shape><Appearance DEF="A"><Material DEF="M" diffuseColor="0.1 0.2 0.3"/></Appearance><Box/></Shape>
<Shape><Appearance USE="A"/><Box/></Shape></Scene></X3D>"""
        shapes = ra.material_colours(ra.parse(text, text=True))
        self.assertEqual(len(shapes), 2)
        self.assertEqual(shapes[1]["material"], "Material")
        self.assertAlmostEqual(shapes[1]["colours"]["Material.diffuseColor"][1][1], 0.2)

    def test_image_deltas_and_pose(self):
        a = np.zeros((16, 16, 3)); b = a.copy(); b[4:8, 4:8] = 100
        d = ra.image_deltas(a, b)
        self.assertAlmostEqual(d["mean_abs_delta"], 100 * 16 / 256, places=2)
        self.assertEqual(d["foreground_delta"], 100.0)
        self.assertEqual(ra.image_deltas(a, a)["mean_abs_delta"], 0.0)
        root = ra.parse('<X3D><Scene><Transform translation="0 0 5"><Viewpoint position="0 0 5"/></Transform></Scene></X3D>', text=True)
        pose = ra.viewpoint_pose(root)
        self.assertEqual(pose["position"], [0.0, 0.0, 10.0])
        self.assertEqual(ra.pose_difference(pose, pose)["position"], 0.0)

    def test_glb_audit_reads_base_color_and_vertex_colours(self):
        doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}}]}],
               "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.603827, 0.603827, 0.603827, 1]}},
                             {"emissiveFactor": [0.0, 0.0, 0.0]}],
               "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                             {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC4"}],
               "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 48}]}
        lin = ra.srgb_to_linear(np.array([[0.5, 0.5, 0.5], [0.2, 0.4, 0.8], [1, 0, 0]]))
        blob = struct.pack("<9f", *np.zeros(9)) + b"".join(struct.pack("<4f", *c, 1.0) for c in lin)
        doc["buffers"] = [{"byteLength": len(blob)}]
        js = json.dumps(doc).encode(); js += b" " * (-len(js) % 4)
        blob += b"\0" * (-len(blob) % 4)
        data = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(blob)) + struct.pack("<I4s", len(js), b"JSON") + js \
            + struct.pack("<I4s", len(blob), b"BIN\0") + blob
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.glb")
            Path(path).write_bytes(data)
            got = ra.glb_audit(ra.parse(ORIG, text=True), path)
        self.assertLess(got["base"]["orig_to_glb_max"], 1e-5)
        self.assertLess(got["vertex"]["orig_to_glb_max"], 1e-4)
        self.assertEqual(got["materials"], 2)


if __name__ == "__main__":
    unittest.main()
