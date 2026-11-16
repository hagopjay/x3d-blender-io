# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The lineage report (source/lineage.py): pure Python, no Blender. Fixtures are IR scenes written by the real emitter."""

from __future__ import annotations

import io
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from emit_x3d40 import export_ir_scene
from ir import IRInstance, IRLight, IRMetadata, IRPBRMaterial, IRScene, IRShape, IRTransform, IRViewpoint, IRMeshGeometry
import lineage


def scene(entries=()):
    cube = IRMeshGeometry(name="Cube", coord=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], coord_index=[0, 1, 2, -1])
    mat = IRPBRMaterial(name="Paint", base_color=(0.2, 0.4, 0.6, 0.75), emissive_color=(2.0, 1.0, 0.5, 1.0), roughness=0.5,
                        metallic=0.0)
    lamp = IRInstance(source_key="LIGHT:Lamp", object_name="Lamp", object_type="LIGHT",
                      transform=IRTransform(translation=(0.0, 4.0, 1.0)),
                      light=IRLight(name="Lamp", light_type="POINT", color=(0.25, 0.5, 1.0), intensity=0.4))
    cam = IRInstance(source_key="CAMERA:Cam", object_name="Cam", object_type="CAMERA",
                     transform=IRTransform(translation=(1.0, 2.0, 3.0), rotation_axis_angle=(0.0, 1.0, 0.0, 0.5)),
                     viewpoint=IRViewpoint(name="Cam", description="Cam", field_of_view=0.8))
    box = IRInstance(source_key="MESH:Cube", object_name="Cube.001", object_type="MESH",
                     transform=IRTransform(translation=(1.0, 3.0, -2.0), scale=(2.0, 2.0, 2.0)),
                     shapes=[IRShape(geometry_name="Cube", material_name="Paint")], children=[lamp])
    return IRScene(name="S", metadata=IRMetadata(filename="s.x3d", entries=list(entries)), geometries=[cube], materials=[mat],
                   instances=[box, cam], material_model="classic", material_model_forced=True)


def write(ir, colour_space="SRGB"):
    buf = io.StringIO()
    export_ir_scene(buf, ir, generator="Test v1", version="4.0", colour_space=colour_space)
    return buf.getvalue()


class LineageReport(unittest.TestCase):
    def setUp(self):
        self.ir = scene()
        self.text = write(self.ir)
        self.report = lineage.build_report(self.ir, self.text, colour_space="SRGB")
        self.by = {(r["def"], r["field"]): r for r in self.report["records"]}

    def test_every_record_is_found_and_located(self):
        self.assertTrue(self.report["records"])
        for r in self.report["records"]:
            self.assertEqual(r["status"], "found", r)
            a, b = r["locus"]["span"]
            self.assertEqual(self.text[a:b], r["file_value"])
            self.assertEqual(self.text.count("\n", 0, a) + 1, r["locus"]["line"])

    def test_names_follow_the_emitters_def_rules(self):
        # "Cube.001" is written as OB_Cube_001; the light as LA_Lamp; the camera as CA_Cam; the material as MA_Paint
        for key in [("OB_Cube_001", "translation"), ("LA_Lamp", "intensity"), ("CA_Cam", "fieldOfView"), ("MA_Paint", "diffuseColor")]:
            self.assertIn(key, self.by)
        self.assertEqual(self.by[("OB_Cube_001", "translation")]["source"], dict(datablock="objects", name="Cube.001", path="matrix_world"))

    def test_plain_values_are_verified(self):
        for key in [("OB_Cube_001", "translation"), ("OB_Cube_001", "rotation"), ("LA_Lamp", "intensity"), ("CA_Cam", "fieldOfView"),
                    ("MA_Paint", "diffuseColor")]:
            self.assertEqual(self.by[key]["verdict"], "verified", self.by[key])
            self.assertEqual(self.by[key]["value_status"], "match")

    def test_srgb_encoding_is_recomputed_independently(self):
        r = self.by[("MA_Paint", "diffuseColor")]
        got = [float(x) for x in r["file_value"].split()]
        self.assertAlmostEqual(got[0], 0.4845, places=3)     # sRGB(0.2)
        self.assertEqual(r["value_status"], "match")
        self.assertEqual([s["id"] for s in r["derivation"]], ["linear_to_srgb", "sfcolor_clip", "fmt6"])

    def test_lossy_and_fitted_conversions_are_check(self):
        self.assertEqual(self.by[("MA_Paint", "specularColor")]["verdict"], "check")     # Blinn-Phong fit: no independent recompute
        self.assertIn("phong_from_principled", self.by[("MA_Paint", "specularColor")]["note"])
        r = self.by[("MA_Paint", "emissiveColor")]     # (2, 1, 0.5): a channel above 1 is scaled down, Emission Strength is lost
        self.assertEqual((r["verdict"], r["value_status"]), ("check", "match"))
        self.assertIn("sfcolor_clip", r["note"])

    def test_a_wrong_colour_space_is_caught(self):
        # the file was written sRGB-encoded; a reader that believes the export was AS_IS recomputes different numbers
        wrong = lineage.build_report(self.ir, self.text, colour_space="AS_IS")
        r = {(x["def"], x["field"]): x for x in wrong["records"]}[("MA_Paint", "diffuseColor")]
        self.assertEqual((r["value_status"], r["verdict"]), ("mismatch", "check"))

    def test_an_emitter_that_skips_the_srgb_step_is_caught(self):
        import emit_x3d40
        from unittest import mock
        ir = scene()
        with mock.patch.object(emit_x3d40, "display_colour", lambda rgb, space: tuple(rgb)):   # the regression: colours left linear
            text = write(ir)
        r = {(x["def"], x["field"]): x for x in lineage.build_report(ir, text, colour_space="SRGB")["records"]}[("MA_Paint", "diffuseColor")]
        self.assertEqual((r["value_status"], r["verdict"]), ("mismatch", "check"))
        self.assertIn("0.2", r["file_value"])

    def test_hop_one_from_a_snapshot(self):
        sv = {"LA_Lamp/intensity": [0.7, 1.75, 1]}        # energy 0.7 W, 1.75 W per intensity, made in Blender: 0.7 / 1.75 = 0.4
        good = lineage.build_report(self.ir, self.text, colour_space="SRGB", source_values=sv)
        self.assertTrue({(x["def"], x["field"]): x for x in good["records"]}[("LA_Lamp", "intensity")]["source_ok"])
        bad = lineage.build_report(self.ir, self.text, colour_space="SRGB", source_values={"LA_Lamp/intensity": [0.7, 1.75, 0]})
        r = {(x["def"], x["field"]): x for x in bad["records"]}[("LA_Lamp", "intensity")]
        self.assertTrue(r["source_ok"])                    # imported light: 0.4 either way
        worse = lineage.build_report(self.ir, self.text, colour_space="SRGB", source_values={"LA_Lamp/intensity": [3.5, 1.75, 1]})
        r = {(x["def"], x["field"]): x for x in worse["records"]}[("LA_Lamp", "intensity")]
        self.assertFalse(r["source_ok"])                   # 3.5 / 1.75 = 2, capped to 1, but the IR says 0.4
        self.assertEqual(r["verdict"], "check")

    def test_fov_snapshot(self):
        import math
        t = math.tan(1.2 / 2)
        fov = 2 * math.atan(min(t, t * 9 / 16))         # horizontal fit, 16:9: the smaller side is the vertical one
        ir = scene()
        ir.instances[1].viewpoint.field_of_view = fov
        text = write(ir)
        rep = lineage.build_report(ir, text, colour_space="SRGB", source_values={"CA_Cam/fieldOfView": [1.2, 0, 1920, 1080]})
        r = {(x["def"], x["field"]): x for x in rep["records"]}[("CA_Cam", "fieldOfView")]
        self.assertTrue(r["source_ok"], r)

    def test_summary_and_coverage_are_honest(self):
        s = self.report["summary"]
        self.assertEqual(s["total"], s["verified"] + s["check"] + s["unchecked"])
        self.assertTrue(0 < s["coverage"] < 1)    # the Coordinate point list and others have no record yet
        self.assertEqual(s["unchecked"], 0)

    def test_reverify_detects_an_edit_to_the_file(self):
        self.assertEqual(lineage.reverify(self.report, self.text), [])
        edited = self.text.replace('intensity="0.400000"', 'intensity="0.900000"')
        self.assertNotEqual(edited, self.text)
        problems = lineage.reverify(self.report, edited)
        self.assertTrue(any("LA_Lamp/intensity" in p for p in problems) and any("sha256" in p for p in problems))

    def test_report_hash_is_stable(self):
        again = lineage.build_report(self.ir, write(scene()), colour_space="SRGB")
        self.assertEqual(lineage.report_sha256(self.report), lineage.report_sha256(again))


class HeadMetaCarry(unittest.TestCase):
    """The 4.0 writer keeps every imported head meta, so x3dprov.* entries survive an import and export; they describe the old file."""

    ENTRIES = [("generator", "Other Tool 1"), ("x3dprov.step", "3"), ("x3dprov.sha256", "ab12"), ("reference", "R1"), ("reference", "R2")]

    def test_unknown_meta_survives_in_file_order_after_generator_and_filename(self):
        text = write(scene(self.ENTRIES))
        metas = [(m.attrib["name"], m.attrib["content"]) for m in ET.fromstring(text).iter("meta")]
        names = [n for n, _ in metas]
        self.assertEqual(names[:2], ["generator", "filename"])
        self.assertEqual(names[2:], ["generator", "x3dprov.step", "x3dprov.sha256", "reference", "reference"])
        self.assertEqual(metas[0], ("generator", "Test v1"))     # this export's own generator first, the other tool's after it
        self.assertEqual(metas[2], ("generator", "Other Tool 1"))

    def test_report_lists_carried_meta_as_not_describing_this_file(self):
        ir = scene(self.ENTRIES)
        rep = lineage.build_report(ir, write(ir), colour_space="SRGB")
        self.assertIn(["x3dprov.sha256", "ab12"], rep["carried_head_meta"]["entries"])
        self.assertIn("not this export", rep["carried_head_meta"]["note"])

    def test_dialog_name_replaces_but_unknown_names_are_never_replaced(self):
        ir = scene([("title", "Old"), ("x3dprov.title", "keep")])
        ir.metadata.title = "New"
        metas = dict((m.attrib["name"], m.attrib["content"]) for m in ET.fromstring(write(ir)).iter("meta"))
        self.assertEqual((metas["title"], metas["x3dprov.title"]), ("New", "keep"))


if __name__ == "__main__":
    unittest.main()
