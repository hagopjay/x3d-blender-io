# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Adversarial checks for the checks: semantic changes and failed runs must not pass."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "io_sync"))
import fixed_point
import x3d_diff


class AdversarialDiffTests(unittest.TestCase):
    def diff(self, a, b):
        return x3d_diff.Differ(rel=1e-4, abs_=1e-4).compare(ET.fromstring(a), ET.fromstring(b))

    def test_topology_indices_do_not_use_coordinate_tolerance(self):
        self.assertTrue(self.diff('<IndexedFaceSet coordIndex="100000 2 3 -1"/>',
                                  '<IndexedFaceSet coordIndex="100001 2 3 -1"/>'))

    def test_reordering_selected_children_changes_meaning(self):
        children = {
            "Switch": ('<Transform DEF="A" translation="1 0 0"/>', '<Transform DEF="B" translation="2 0 0"/>'),
            "LOD": ('<Shape DEF="A"><Box/></Shape>', '<Shape DEF="B"><Sphere/></Shape>'),
            "CADLayer": ('<Shape DEF="A"><Box/></Shape>', '<Shape DEF="B"><Sphere/></Shape>'),
            "MultiTexture": ('<ImageTexture DEF="A" url="&quot;a.png&quot;"/>', '<ImageTexture DEF="B" url="&quot;b.png&quot;"/>'),
            "MultiTextureCoordinate": ('<TextureCoordinate DEF="A" point="0 0"/>',
                                       '<TextureCoordinate DEF="B" point="1 1"/>'),
            "MultiTextureTransform": ('<TextureTransform DEF="A" scale="1 1"/>',
                                      '<TextureTransform DEF="B" scale="2 2"/>'),
        }
        for tag, (a, b) in children.items():
            with self.subTest(tag=tag):
                self.assertTrue(self.diff(f'<{tag}>{a}{b}</{tag}>', f'<{tag}>{b}{a}</{tag}>'))

    def test_grouping_order_still_aligns_by_identity(self):
        self.assertEqual(self.diff('<Group><Shape DEF="A"/><Shape DEF="B"/></Group>',
                                   '<Group><Shape DEF="B"/><Shape DEF="A"/></Group>'), [])

    def test_different_root_node_types_are_not_equal(self):
        self.assertTrue(self.diff('<Shape/>', '<Transform/>'))

    def test_script_source_is_compared_before_and_after_field_children(self):
        for a, b in (('<Script>var gain=1;</Script>', '<Script>var gain=2;</Script>'),
                     ('<Script><field name="x"/>var gain=1;</Script>',
                      '<Script><field name="x"/>var gain=2;</Script>')):
            with self.subTest(a=a):
                self.assertTrue(self.diff(a, b))

    def test_indentation_has_no_semantic_effect(self):
        self.assertEqual(self.diff('<Group><Shape/></Group>', '<Group>\n  <Shape/>\n</Group>'), [])


class FixedPointDriverTests(unittest.TestCase):
    def prepare(self, root, profiles=None):
        suite, out = root / "suite", root / "out"
        suite.mkdir()
        out.mkdir()
        if profiles is None:
            profiles = {"main": {"file": "scene.x3d", "export": {}}}
        (suite / "x3d_suite_manifest.json").write_text(json.dumps({"profiles": profiles}))
        (suite / "scene.x3d").write_text('<X3D><Scene/></X3D>')
        return suite, out

    def run_check(self, suite, out, profiles=()):
        return fixed_point.run(suite, out, "unused-blender", profiles, 1e-4, 1e-4)

    def test_unknown_profile_cannot_skip_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            suite, out = self.prepare(Path(directory))
            with patch.object(fixed_point.subprocess, "run") as proc:
                self.assertEqual(self.run_check(suite, out, ["typo"]), 1)
                proc.assert_not_called()

    def test_empty_manifest_is_not_a_successful_run(self):
        with tempfile.TemporaryDirectory() as directory:
            suite, out = self.prepare(Path(directory), {})
            self.assertEqual(self.run_check(suite, out), 1)

    def test_stale_success_does_not_hide_a_failed_current_leg(self):
        with tempfile.TemporaryDirectory() as directory:
            suite, out = self.prepare(Path(directory))
            stale = out / "main" / "suite__scene"
            stale.mkdir(parents=True)
            for name in ("e1.x3d", "e2.x3d"):
                (stale / name).write_text('<X3D><Scene/></X3D>')
            with patch.object(fixed_point.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "FAIL", "")):
                self.assertEqual(self.run_check(suite, out), 1)
            self.assertIn("error", json.loads((out / "summary.json").read_text())["main"])

    def test_current_complete_outputs_pass_and_are_identified(self):
        with tempfile.TemporaryDirectory() as directory:
            suite, out = self.prepare(Path(directory))

            def leg(cmd, **kwargs):
                run_root = Path(cmd[cmd.index("--") + 1])
                expected = run_root / "suite__scene"
                expected.mkdir(parents=True)
                for name in ("e1.x3d", "e2.x3d"):
                    (expected / name).write_text('<X3D><Scene/></X3D>')
                for name in ("s1.json", "s2.json"):
                    (expected / name).write_text('{}')
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

            with patch.object(fixed_point.subprocess, "run", side_effect=leg):
                self.assertEqual(self.run_check(suite, out), 0)
            row = json.loads((out / "summary.json").read_text())["main"]
            self.assertTrue((Path(row["artifacts"]) / "e2.x3d").is_file())


if __name__ == "__main__":
    unittest.main()
