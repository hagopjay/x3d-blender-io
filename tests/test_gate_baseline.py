# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The committed export-gate baseline (tools/fidelity_rig/gate-baseline.json) is well-formed and consistent with the rig's
pins, the scenes lists and the CI job. No Blender, no browser.

    cd tests && python -m unittest test_gate_baseline
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RIG = ROOT / "tools" / "fidelity_rig"
sys.path.insert(0, str(RIG))
import gate  # noqa: E402

BASELINE = json.loads((RIG / "gate-baseline.json").read_text())


def scene_names(*files):
    names = []
    for f in files:
        names += [s["name"] for s in json.loads((RIG / f).read_text())]
    return names


class CommittedBaseline(unittest.TestCase):
    def test_schema_and_lint(self):
        self.assertEqual(BASELINE["schema"], gate.BASELINE_SCHEMA)
        self.assertEqual(gate.lint_baseline(BASELINE), [])   # every known / skip / allow_empty has a written reason

    def test_tolerance_rule_is_written_down(self):
        tol = BASELINE["tolerance"]
        self.assertEqual(tol["image_delta"], {"abs": 0.5, "rel": 0.05})
        self.assertIn("flip", tol)
        self.assertIn("triangles", tol)

    def test_rig_fingerprint_matches_the_pins(self):
        pins = json.loads((RIG / "package.json").read_text())["dependencies"]
        rig = BASELINE["rig"]
        self.assertEqual(rig["x_ite"], pins["x_ite"])
        self.assertEqual(rig["babylon"], pins["babylonjs"])
        self.assertEqual(rig["validator"], pins["gltf-validator"])
        for key in ("chromium", "blender", "flip_evaluator", "renderer", "addon_git_revision"):
            self.assertTrue(rig.get(key), key)
        self.assertTrue(rig["blender"].startswith("5.3"))

    def test_every_scene_has_the_values_its_checks_need(self):
        for name, e in BASELINE["scenes"].items():
            skip = e.get("skip", {})
            self.assertIn("warnings", e["validator"], name)
            self.assertIn(e["glb"]["class"], ("triangles", "points", "lines", "points+lines", "empty"), name)
            self.assertIn("nodes_lost", e["reexport"], name)
            if "geometry_delta" not in skip:
                self.assertIn("geometry_delta", e, name)
            if "roundtrip_delta" not in skip:
                self.assertIn("mean_abs_delta", e["roundtrip"], name)
            if e["glb"]["class"] == "empty":
                self.assertIn("allow_empty", e, f"{name}: an empty glb in the baseline needs an allow_empty entry")
            self.assertGreaterEqual(e["validator"]["warnings"], 0)

    def test_scene_lists_are_covered_by_the_baseline(self):
        for f in ("probes.json", "scenes-repo.json", "scenes-gate-ci.json", "scenes-demo.json"):
            for n in scene_names(f):
                self.assertIn(n, BASELINE["scenes"], f"{n} from {f} has no baseline entry")

    def test_repo_scenes_exist(self):
        for f in ("probes.json", "scenes-repo.json", "scenes-gate-ci.json"):
            for s in json.loads((RIG / f).read_text()):
                self.assertTrue((RIG / s["x3d"]).exists(), s["x3d"])

    def test_known_defects_name_the_round_trip_audit_ids(self):
        ids = {k["defect"] for e in BASELINE["scenes"].values() for k in e.get("known", [])}
        self.assertTrue(ids)
        for i in ids:
            self.assertRegex(i, r"^[DH]\d+$")

    def test_no_scratch_paths_in_the_baseline(self):
        text = (RIG / "gate-baseline.json").read_text()
        self.assertNotRegex(text, r"/tmp/|/home/|claude-0|scratchpad")


class CiJob(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    def test_workflow_is_valid_yaml_with_the_gate_job(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        doc = yaml.safe_load(self.text)
        job = doc["jobs"]["fidelity-gate"]
        steps = " ".join(str(s.get("run", "")) + str(s.get("uses", "")) for s in job["steps"])
        for needle in ("bpy==", "npm install", "playwright install --with-deps chromium", "gate.py", "upload-artifact"):
            self.assertIn(needle, steps)
        trigger = doc.get("on", doc.get(True))
        self.assertIn("gate_full", trigger["workflow_dispatch"]["inputs"])

    def test_ci_subset_is_the_five_probes_plus_a_few_showcase_scenes(self):
        names = scene_names("scenes-gate-ci.json")
        probes = scene_names("probes.json")
        self.assertEqual(names[:5], probes)
        self.assertTrue(4 <= len(names) - 5 <= 5, names)

    def test_ci_pins_match_the_baseline_rig(self):
        m = re.search(r"bpy==([\d.]+)", self.text)
        self.assertTrue(m)
        self.assertEqual(m.group(1), BASELINE["rig"]["blender"])
        self.assertIn(f"flip-evaluator=={BASELINE['rig']['flip_evaluator']}", self.text)


if __name__ == "__main__":
    unittest.main()
