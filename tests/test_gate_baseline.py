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
        # every rule, not one: a baseline PR that loosens flip or triangles must change the code constant (and so be reviewed as code)
        self.assertEqual(BASELINE["tolerance"], gate.DEFAULT_TOLERANCE)
        self.assertEqual(gate.DEFAULT_TOLERANCE["image_delta"], {"abs": 0.5, "rel": 0.05})
        self.assertEqual(gate.DEFAULT_TOLERANCE["flip"], {"abs": 0.01, "rel": 0.05})
        self.assertEqual(gate.DEFAULT_TOLERANCE["triangles"], {"rel": 0.01})
        self.assertEqual(gate.DEFAULT_TOLERANCE["geometry_share"], {"abs": 0.002, "rel": 0.10})

    def test_rig_fingerprint_matches_the_pins(self):
        pins = json.loads((RIG / "package.json").read_text())["dependencies"]
        rig = BASELINE["rig"]
        self.assertEqual(rig["x_ite"], pins["x_ite"])
        self.assertEqual(rig["babylon"], pins["babylonjs"])
        self.assertEqual(rig["validator"], pins["gltf-validator"])
        for key in ("chromium", "blender", "flip_evaluator", "renderer", "addon_git_revision", "x3d_py", "numpy", "pillow"):
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
                self.assertIn("geometry_share", e, name)
                self.assertIn("geometry_missing_share", e, name)
                if e["geometry_delta"] is None:   # a render that measured nothing needs the written reason, or it is a vacuous check
                    self.assertTrue((e.get("allow_blank") or e.get("allow_empty") or {}).get("reason"), f"{name}: geometry_delta null without allow_blank")
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
        self.assertEqual(len(names), len(set(names)))

    def test_every_ci_scene_really_renders(self):
        """A scene whose renders are all background passes the render checks without measuring (stars-splats did). The CI subset
        may hold only scenes whose baseline measured something: a number, a coverage, no allow_blank / allow_empty, nothing skipped."""
        for n in scene_names("scenes-gate-ci.json"):
            e = BASELINE["scenes"][n]
            self.assertNotIn("allow_blank", e, n)
            self.assertNotIn("allow_empty", e, n)
            self.assertFalse({"geometry_delta", "roundtrip_delta"} & set(e.get("skip", {})), n)
            self.assertIsNotNone(e["geometry_delta"], n)
            self.assertGreater(e["geometry_share"], 0, n)
            self.assertNotEqual(e["glb"]["class"], "empty", n)

    def test_zero_scene_lists_are_caught(self):
        self.assertGreaterEqual(len(scene_names("scenes-gate-ci.json")), 9)
        self.assertGreaterEqual(len(scene_names("probes.json", "scenes-repo.json")), 33)

    def test_ci_pins_match_the_baseline_rig(self):
        m = re.search(r"bpy==([\d.]+)", self.text)
        self.assertTrue(m)
        self.assertEqual(m.group(1), BASELINE["rig"]["blender"])
        self.assertIn(f"flip-evaluator=={BASELINE['rig']['flip_evaluator']}", self.text)
        for pkg, key in (("x3d", "x3d_py"), ("numpy", "numpy"), ("pillow", "pillow")):
            self.assertIn(f"{pkg}=={BASELINE['rig'][key]}", self.text, pkg)

    def test_no_job_installs_x3d_unpinned(self):
        installs = [ln for ln in self.text.splitlines() if "pip install" in ln]
        self.assertTrue(installs)
        for ln in installs:
            for pkg in re.findall(r"(?<![\w-])(x3d|numpy|pillow|flip-evaluator|bpy)(?![\w-])(==[\w.]+)?", ln):
                if pkg[0] in ("x3d", "numpy", "pillow", "flip-evaluator"):
                    self.assertTrue(pkg[1], f"{pkg[0]} is not pinned in: {ln.strip()}")

    def test_the_gate_job_warns_about_a_missing_report_and_has_room_for_one_hung_chunk(self):
        job = self.text[self.text.index("  fidelity-gate:"):]
        self.assertIn("if-no-files-found: warn", job)
        self.assertGreaterEqual(int(re.search(r"timeout-minutes:\s*(\d+)", job).group(1)), 45)


if __name__ == "__main__":
    unittest.main()
