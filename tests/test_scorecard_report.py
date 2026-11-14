# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorecard report rendering: scorecard.md tables and the self-contained scorecard.html. No browser."""
import json
import re
import tempfile
import unittest
from pathlib import Path

import scorecard_fixtures as fx
from scorecard import report, schema

EMPTY = dict(fx.PASS_GLB, verdict="empty", triangles=0, empty=True)
TABLE = {
    "alpha": {"xite": 0.1, "babylon_addon_glb": (0.0234, None), "blender_eevee": 0.3},
    "beta": {"xite": 0.04, "babylon_addon_glb": (0.0567, EMPTY), "blender_eevee": 0.08},
}


def doc():
    return fx.doc_from(TABLE, not_run=("castle_native", "babylon_castle_glb"), failed={("beta", "blender_eevee"): "EEVEE: worker died <b>"})


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.md = report.render_markdown(doc())

    def test_sections_and_footnotes(self):
        for h in ("## 1. FLIP against the Cycles reference", "## 2. Engine means", "## 3. Paired difference against X_ITE", "## 5. Validator verdicts"):
            self.assertIn(h, self.md)
        for k in "FGXVTDNR":
            self.assertRegex(self.md, rf"(?m)^\[\^{k}\]: ")

    def test_every_footnote_marker_has_a_definition(self):
        used = set(re.findall(r"\[\^(\w)\]", re.sub(r"(?m)^\[\^\w\]:.*$", "", self.md)))
        defined = set(re.findall(r"(?m)^\[\^(\w)\]: ", self.md))
        self.assertTrue(used <= defined, used - defined)

    def test_cells_carry_flip_and_marks(self):
        self.assertIn("| alpha | 0.1000 x✓ | 0.0234 ✓ |", self.md)
        self.assertIn("0.0567 ∅", self.md)             # the EMPTY glb is marked, not hidden
        self.assertIn("failed", self.md)               # the failed EEVEE cell

    def test_common_set_is_stated(self):
        self.assertIn("Common scene set: 1 of 2 scenes", self.md)
        self.assertIn("`alpha`", self.md)

    def test_engine_mean_over_common_set(self):
        self.assertIn("| X_ITE | 1 | 0.1000 |", self.md)

    def test_not_run_legs_listed_with_reason(self):
        self.assertIn("`castle_native`", self.md)
        self.assertIn("CASTLE_RENDER is not set", self.md)

    def test_eevee_column_is_labelled(self):
        self.assertIn("Blender EEVEE", self.md)

    def test_paired_table(self):
        self.assertIn("| Babylon (add-on glb) | 2 |", self.md)

    def test_tool_versions_named_in_footnotes(self):
        for s in ("flip-evaluator 1.7", "Khronos glTF-Validator 2.0.0-dev.3.10", "X_ITE 16.7.1", "Babylon.js 9.32.0", "Chromium Chrome/153.0.0.0"):
            self.assertIn(s, self.md)

    def test_cell_text(self):
        self.assertEqual(report.cell(None), "—")
        self.assertEqual(report.cell(schema.new_leg_record("xite", schema.NOT_APPLICABLE, "r")), "n/a")
        self.assertEqual(report.cell(schema.new_leg_record("xite", schema.NOT_RUN, "r")), "not run")

    def test_empty_document_renders(self):
        md = report.render_markdown(fx.doc_from({}))
        self.assertIn("Cross-engine scorecard", md)


class HtmlTests(unittest.TestCase):
    def test_self_contained_and_themed(self):
        h = report.render_html(doc(), None)
        self.assertIn("prefers-color-scheme:dark", h)
        self.assertIn('name=\'viewport\'', h)
        self.assertNotRegex(h, r"(src|href)=['\"]https?://")
        self.assertNotIn("<link", h)
        self.assertEqual(h.count("<script"), 1)         # the one inline script (the map toggle)

    def test_html_escapes_reasons(self):
        h = report.render_html(doc(), None)
        self.assertIn("worker died &lt;b&gt;", h)
        self.assertNotIn("worker died <b>", h)

    def test_every_footnote_reference_resolves(self):
        h = report.render_html(doc(), None)
        refs = set(re.findall(r'href="#fn-(\w)"', h))
        ids = set(re.findall(r'id=\'fn-(\w)\'', h))
        self.assertTrue(refs and refs <= ids, refs - ids)

    def test_marks_have_tooltips(self):
        h = report.render_html(doc(), None)
        self.assertRegex(h, r'<span class="m bad" title="gltf-validator 2\.0\.0-dev\.3\.10: 0 errors, 0 warnings, 0 triangles, EMPTY')

    def test_contact_sheet_embeds_thumbnails(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow missing")
        with tempfile.TemporaryDirectory() as td:
            d = doc()
            for s in d["scenes"]:
                (Path(td) / "scenes" / s["name"]).mkdir(parents=True)
                for leg, r in s["legs"].items():
                    if r["status"] == schema.OK:
                        p = Path(td) / "scenes" / s["name"] / f"{leg}.png"
                        Image.new("RGB", (512, 512), (40, 90, 160)).save(p)
                        r["image"] = f"scenes/{s['name']}/{leg}.png"
                        if "flip_vs_reference" in r["metrics"]:
                            hp = Path(td) / "scenes" / s["name"] / f"flip_{leg}.png"
                            Image.new("RGB", (512, 512), (80, 0, 90)).save(hp)
                            r["metrics"]["flip_vs_reference"]["heat"] = f"scenes/{s['name']}/flip_{leg}.png"
            h = report.render_html(d, td)
            self.assertGreater(h.count("data:image/jpeg;base64,"), 8)
            self.assertIn("alpha", h)
            self.assertLess(len(h), 2_000_000)

    def test_build_writes_both_files(self):
        with tempfile.TemporaryDirectory() as td:
            with open(Path(td) / "results.json", "w") as f:
                json.dump(doc(), f)
            problems = report.build(td)
            self.assertEqual(problems, [])
            self.assertTrue((Path(td) / "scorecard.md").stat().st_size > 1000)
            self.assertTrue((Path(td) / "scorecard.html").stat().st_size > 1000)


if __name__ == "__main__":
    unittest.main()
