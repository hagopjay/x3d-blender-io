# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The import/export parity manifest (tools/io_sync/parity.json) matches the code. Plain Python, no Blender.

A change that makes the export write a new element, or drops the import of one, fails here until parity.json says
how the other side handles it; a fixed asymmetry must name a test that exists. See docs/IO_SYNC.md.

    cd tests && python -m unittest test_io_parity
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source"
MANIFEST = json.loads((ROOT / "tools" / "io_sync" / "parity.json").read_text())
sys.path.insert(0, str(ROOT / "tools" / "io_sync"))
import check_parity  # noqa: E402
import x3d_diff  # noqa: E402

# the modules that write X3D 4.0 elements
EMITTERS = ("emit_x3d40.py", "splat_native.py", "geospatial.py", "interaction.py", "lineage.py")
ELEMENT = re.compile(r"<([A-Z][A-Za-z0-9]+)[\s/>{'\"]")


def emitted_elements() -> set[str]:
    names = set()
    for module in EMITTERS:
        names |= set(ELEMENT.findall((SOURCE / module).read_text(encoding="utf-8")))
    return names


class ParityManifestTests(unittest.TestCase):

    def test_every_element_the_export_can_write_is_declared(self):
        missing = sorted(emitted_elements() - set(MANIFEST["nodes"]))
        self.assertEqual(missing, [], "add these to tools/io_sync/parity.json with how the import reads them back")

    def test_every_declared_import_exists(self):
        importer = (SOURCE / "import_x3d.py").read_text(encoding="utf-8")
        absent = [name for name, entry in MANIFEST["nodes"].items()
                  if entry["import"] == "yes" and not re.search(r"['\"]%s['\"]" % re.escape(name), importer)]
        self.assertEqual(absent, [], "parity.json says these import, but import_x3d.py never names them")

    def test_entries_use_the_declared_values(self):
        allowed = set(MANIFEST["round_trip_values"])
        for name, entry in MANIFEST["nodes"].items():
            self.assertIn(entry["import"], {"yes", "structural"}, name)
            self.assertIn(entry["round_trip"], allowed, name)
            if entry["round_trip"] in {"lossy", "equivalent"}:
                self.assertTrue(entry.get("note"), f"{name}: say what changes")

    def test_fixed_asymmetries_name_an_existing_test(self):
        tests = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
        for item in MANIFEST["asymmetries"]:
            self.assertIn(item["status"], {"fixed", "open", "by-design"}, item["id"])
            if item["status"] == "fixed":
                self.assertIn(f"def {item['test']}(", tests, item["id"])

    def test_lossy_notes_point_at_a_listed_asymmetry(self):
        ids = {item["id"] for item in MANIFEST["asymmetries"]}
        for name, entry in MANIFEST["nodes"].items():
            for ref in re.findall(r"\((A\d+)\)", entry.get("note", "")):
                self.assertIn(ref, ids, name)


class CheckParityTests(unittest.TestCase):

    def _file(self, folder, text):
        path = Path(folder) / "a.x3d"
        path.write_text(text, encoding="utf-8")
        return path

    def test_declared_elements_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            self._file(folder, '<X3D><Scene><Transform><Shape/></Transform></Scene></X3D>')
            self.assertEqual(check_parity.main([folder]), 0)

    def test_an_undeclared_element_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            self._file(folder, '<X3D><Scene><Billboard/></Scene></X3D>')
            self.assertEqual(check_parity.main([folder]), 1)

    def test_no_files_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(check_parity.main([folder]), 1)


class StructuralDiffTests(unittest.TestCase):
    """tools/io_sync/x3d_diff.py, the comparison the fixed-point gate runs."""

    def _diff(self, a, b, **kw):
        import xml.etree.ElementTree as ET
        return x3d_diff.Differ(**kw).compare(ET.fromstring(a), ET.fromstring(b))

    def test_identical_files_have_no_difference(self):
        doc = '<X3D><Scene><Transform DEF="OB_A" translation="1 2 3"><Shape/></Transform></Scene></X3D>'
        self.assertEqual(self._diff(doc, doc), [])

    def test_numbers_compare_within_tolerance(self):
        a = '<X3D><Transform translation="1 2 3"/></X3D>'
        self.assertEqual(self._diff(a, '<X3D><Transform translation="1.0000001 2 3"/></X3D>'), [])
        found = self._diff(a, '<X3D><Transform translation="1.1 2 3"/></X3D>')
        self.assertEqual([(r["kind"], r["attr"]) for r in found], [("value", "translation")])

    def test_normals_get_the_storage_tolerance(self):
        a = '<X3D><Normal vector="0 0 1"/></X3D>'
        self.assertEqual(self._diff(a, '<X3D><Normal vector="0 0.0005 1"/></X3D>', abs_=1e-4), [])
        self.assertTrue(self._diff('<X3D><Coordinate point="0 0 1"/></X3D>',
                                   '<X3D><Coordinate point="0 0.0005 1"/></X3D>', abs_=1e-4))

    def test_children_align_by_def_not_position(self):
        a = '<X3D><Transform DEF="OB_A"/><Transform DEF="OB_B" translation="1 0 0"/></X3D>'
        b = '<X3D><Transform DEF="OB_B" translation="1 0 0"/></X3D>'
        found = self._diff(a, b)
        self.assertEqual([(r["kind"], r["path"]) for r in found], [("missing", "X3D/Transform[DEF=OB_A]")])

    def test_a_def_less_light_transform_aligns_by_what_it_holds(self):
        a = '<X3D><Transform><PointLight DEF="LA_1"/></Transform><Transform><PointLight DEF="LA_2"/></Transform></X3D>'
        b = '<X3D><Transform><PointLight DEF="LA_2"/></Transform></X3D>'
        found = self._diff(a, b)
        self.assertEqual([r["kind"] for r in found], ["missing"])
        self.assertIn("LA_1", found[0]["path"])

    def test_renamed_def_is_equal_unless_strict(self):
        a = '<X3D><Shape DEF="S"/><Shape USE="S"/></X3D>'
        b = '<X3D><Shape DEF="S_001"/><Shape USE="S_001"/></X3D>'
        self.assertEqual(self._diff(a, b), [])
        strict = self._diff(a, b, strict_defs=True)
        self.assertEqual([(r["attr"], r["a"], r["b"]) for r in strict], [("DEF", "S", "S_001")])

    def test_use_pointing_elsewhere_is_a_difference(self):
        a = '<X3D><Shape DEF="P"/><Shape DEF="Q"/><Shape USE="P"/></X3D>'
        b = '<X3D><Shape DEF="P"/><Shape DEF="Q"/><Shape USE="Q"/></X3D>'
        self.assertEqual([r["attr"] for r in self._diff(a, b)], ["USE"])


if __name__ == "__main__":
    unittest.main()
