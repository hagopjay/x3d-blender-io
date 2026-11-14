# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export gate logic (tools/fidelity_rig/gate.py): thresholds, EMPTY classification, baseline update refusals, report
formatting and the exit-code flow, all on synthetic measurements. No Blender, no browser, no node.

    cd tests && python -m unittest test_gate_logic
"""

from __future__ import annotations

import copy
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

RIG = Path(__file__).resolve().parents[1] / "tools" / "fidelity_rig"
sys.path.insert(0, str(RIG))
import gate  # noqa: E402

TOL = gate.DEFAULT_TOLERANCE


def measured(**over):
    """A clean measurement of a scene with surfaces: valid glb, 100 triangles, small deltas, nothing lost."""
    m = dict(
        scene="s", glb_leg=dict(ok=True, blender="5.3.0"),
        validator=dict(ok_ran=True, errors=0, warnings=0, infos=0, hints=0, version="2.0.0-dev.3.10", not_validated=[]),
        glb={"class": "triangles", "triangles": 100, "points": 0, "lines": 0},
        x3d=dict(surface=True, lines=False, points=False, splats=False),
        glb_render_ok=True, geometry_delta=2.0, geometry_share=0.3, geometry_missing_share=0.01, xite_foreground_share=0.4,
        reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=0, nodes_lost=1, lost_types=["Material"]),
        roundtrip=dict(render_ok=True, mean_abs_delta=5.0, flip=0.05))
    m.update(over)
    return m


def baseline_entry(**over):
    e = dict(validator=dict(warnings=0), glb={"class": "triangles", "triangles": 100, "points": 0, "lines": 0}, geometry_delta=2.0,
             reexport=dict(nodes_lost=1), roundtrip=dict(mean_abs_delta=5.0, flip=0.05), geometry_share=0.3, geometry_missing_share=0.01)
    e.update(over)
    return e


def by_check(results):
    return {r["check"]: r for r in results}


class Thresholds(unittest.TestCase):
    def test_tolerance_rule(self):
        rule = TOL["image_delta"]   # max(0.5, 5%)
        self.assertEqual(gate.allowed_max(0.0, rule), 0.5)
        self.assertAlmostEqual(gate.allowed_max(5.0, rule), 5.5)           # 5% of 5 is 0.25, so the 0.5 floor applies
        self.assertAlmostEqual(gate.allowed_max(40.0, rule), 42.0)         # 5% of 40 is 2.0
        self.assertAlmostEqual(gate.improved_below(40.0, rule), 38.0)
        self.assertAlmostEqual(gate.allowed_max(0.05, TOL["flip"]), 0.06)  # flip: max(0.01, 5%)

    def test_clean_scene_passes(self):
        res = gate.evaluate_scene(measured(), baseline_entry(), TOL)
        self.assertEqual({r["check"]: r["status"] for r in res}, {c: "PASS" for c in gate.CHECKS})
        self.assertEqual(gate.scene_verdict(res), "PASS")

    def test_geometry_delta_edges(self):
        e = baseline_entry(geometry_delta=40.0)
        for gd, want in [(42.0, "PASS"), (42.01, "FAIL"), (38.0, "PASS"), (37.9, "IMPROVED")]:
            r = by_check(gate.evaluate_scene(measured(geometry_delta=gd), e, TOL))["geometry_delta"]
            self.assertEqual(r["status"], want, (gd, r))

    def test_roundtrip_delta_and_flip_edges(self):
        e = baseline_entry()
        r = lambda **k: by_check(gate.evaluate_scene(measured(roundtrip=dict(render_ok=True, **k)), e, TOL))["roundtrip_delta"]  # noqa: E731
        self.assertEqual(r(mean_abs_delta=5.5, flip=0.05)["status"], "PASS")
        self.assertEqual(r(mean_abs_delta=5.6, flip=0.05)["status"], "FAIL")
        self.assertEqual(r(mean_abs_delta=5.0, flip=0.07)["status"], "FAIL")
        self.assertIn("FLIP", r(mean_abs_delta=5.0, flip=0.07)["detail"])
        self.assertEqual(r(mean_abs_delta=4.4, flip=0.05)["status"], "IMPROVED")
        self.assertEqual(r(mean_abs_delta=5.0, flip=0.03)["status"], "IMPROVED")

    def test_validator_errors_and_warnings(self):
        bad = measured(validator=dict(ok_ran=True, errors=2, warnings=0, version="v"))
        self.assertEqual(by_check(gate.evaluate_scene(bad, baseline_entry(), TOL))["validator"]["status"], "FAIL")
        warn = measured(validator=dict(ok_ran=True, errors=0, warnings=3, version="v"))
        r = by_check(gate.evaluate_scene(warn, baseline_entry(validator=dict(warnings=2)), TOL))["validator"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("3 warnings > baseline 2", r["detail"])
        self.assertEqual(by_check(gate.evaluate_scene(warn, baseline_entry(validator=dict(warnings=3)), TOL))["validator"]["status"], "PASS")
        self.assertEqual(by_check(gate.evaluate_scene(warn, baseline_entry(validator=dict(warnings=5)), TOL))["validator"]["status"], "IMPROVED")
        # errors fail whatever the baseline says (a baseline cannot hold an error count)
        e = baseline_entry()
        e["validator"]["errors"] = 9
        self.assertEqual(by_check(gate.evaluate_scene(bad, e, TOL))["validator"]["status"], "FAIL")

    def test_validator_did_not_run_fails(self):
        m = measured(validator=dict(ok_ran=False, error="cannot load gltf-validator"))
        r = by_check(gate.evaluate_scene(m, baseline_entry(), TOL))["validator"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("did not run", r["detail"])

    def test_reexport_checks(self):
        e = baseline_entry()
        lost2 = measured(reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=0, nodes_lost=2, lost_types=["Material", "Text"]))
        r = by_check(gate.evaluate_scene(lost2, e, TOL))["reexport"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("2 node types lost > baseline 1", r["detail"])
        self.assertIn("Text", r["detail"])
        lost0 = measured(reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=0, nodes_lost=0, lost_types=[]))
        self.assertEqual(by_check(gate.evaluate_scene(lost0, e, TOL))["reexport"]["status"], "IMPROVED")
        broken = measured(reexport=dict(leg_ok=True, well_formed=False, structural_errors=["mismatched tag"], x3d_py="ok", x3d_py_errors=0, nodes_lost=1))
        self.assertEqual(by_check(gate.evaluate_scene(broken, e, TOL))["reexport"]["status"], "FAIL")
        xe = measured(reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=3, nodes_lost=1))
        r = by_check(gate.evaluate_scene(xe, e, TOL))["reexport"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("x3d.py reports 3 errors", r["detail"])
        missing = measured(reexport=dict(leg_ok=True, well_formed=True, x3d_py=None, x3d_py_errors=0, nodes_lost=1))
        self.assertIn("not installed", by_check(gate.evaluate_scene(missing, e, TOL))["reexport"]["detail"])

    def test_no_glb_and_no_reexport_fail_unless_skipped_with_a_reason(self):
        m = measured(glb_leg=dict(ok=False, error="the importer raised"), reexport=dict(leg_ok=False, error="boom"))
        res = by_check(gate.evaluate_scene(m, baseline_entry(), TOL))
        self.assertEqual(res["validator"]["status"], "FAIL")
        self.assertIn("the importer raised", res["validator"]["detail"])
        self.assertEqual(res["reexport"]["status"], "FAIL")
        e = baseline_entry(skip=dict(validator="singular parent matrix", reexport="same import failure"))
        res = by_check(gate.evaluate_scene(m, e, TOL))
        self.assertEqual(res["validator"]["status"], "SKIP")
        self.assertEqual(res["reexport"]["status"], "SKIP")
        self.assertEqual(gate.scene_verdict(list(res.values())), "PASS")

    def test_missing_render_fails_unless_skipped(self):
        m = measured(glb_render_ok=False, roundtrip=dict(render_ok=False))
        res = by_check(gate.evaluate_scene(m, baseline_entry(), TOL))
        self.assertEqual(res["geometry_delta"]["status"], "FAIL")
        self.assertEqual(res["roundtrip_delta"]["status"], "FAIL")
        e = baseline_entry(skip=dict(geometry_delta="SwiftShader page crash", roundtrip_delta="SwiftShader page crash"))
        res = by_check(gate.evaluate_scene(m, e, TOL))
        self.assertEqual(res["geometry_delta"]["status"], "SKIP")
        self.assertEqual(res["roundtrip_delta"]["status"], "SKIP")

    def test_skip_entry_takes_an_unstable_check_out_of_the_gate_even_when_it_measured(self):
        e = baseline_entry(skip=dict(roundtrip_delta="renders differently on every run", geometry_delta="same"))
        m = measured(geometry_delta=99.0, roundtrip=dict(render_ok=True, mean_abs_delta=99.0, flip=0.9))
        res = by_check(gate.evaluate_scene(m, e, TOL))
        self.assertEqual(res["roundtrip_delta"]["status"], "SKIP")
        self.assertIn("renders differently on every run", res["roundtrip_delta"]["detail"])
        self.assertIn("99.0", res["roundtrip_delta"]["detail"])
        self.assertEqual(res["geometry_delta"]["status"], "SKIP")
        self.assertEqual(gate.scene_verdict(list(res.values())), "PASS")

    def test_per_scene_tolerance_override_for_run_dependent_scenes(self):
        e = baseline_entry(geometry_delta=40.0, tolerance=dict(geometry_delta=dict(abs=20.0), reason="animated: sampled at run-dependent moments"))
        for gd, want in [(59.0, "PASS"), (60.5, "FAIL"), (24.0, "PASS"), (19.0, "IMPROVED")]:
            r = by_check(gate.evaluate_scene(measured(geometry_delta=gd), e, TOL))["geometry_delta"]
            self.assertEqual(r["status"], want, (gd, r))
        # the override is for that check only: the round-trip check keeps the header rule
        r = by_check(gate.evaluate_scene(measured(roundtrip=dict(render_ok=True, mean_abs_delta=6.0, flip=0.05)), e, TOL))["roundtrip_delta"]
        self.assertEqual(r["status"], "FAIL")
        self.assertEqual(gate.lint_baseline(dict(scenes=dict(s=e))), [])
        for bad in (dict(geometry_delta=dict(abs=20.0)), dict(flip=dict(abs=1.0), reason="x"), dict(reason="UNEXPLAINED: x")):
            self.assertTrue(gate.lint_baseline(dict(scenes=dict(s=baseline_entry(tolerance=bad)))), bad)

    def test_geometry_not_visible(self):
        # Babylon.js drew nothing although the baseline has geometry: fail
        r = by_check(gate.evaluate_scene(measured(geometry_delta=None), baseline_entry(), TOL))["geometry_delta"]
        self.assertEqual(r["status"], "FAIL")
        # ... and nothing in the baseline either: a render that measured nothing is VACUOUS, not a pass (F2)
        r = by_check(gate.evaluate_scene(measured(geometry_delta=None), baseline_entry(geometry_delta=None), TOL))["geometry_delta"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("vacuous", r["detail"])
        self.assertIn("100 triangles that Babylon.js did not draw", r["detail"])

    def test_scene_without_baseline_fails(self):
        res = gate.evaluate_scene(measured(), None, TOL)
        self.assertEqual(by_check(res)["baseline"]["status"], "FAIL")
        self.assertEqual(gate.scene_verdict(res), "FAIL")
        self.assertEqual(by_check(res)["geometry_delta"]["status"], "SKIP")

    def test_known_defects_annotate_but_do_not_excuse(self):
        e = baseline_entry(known=[dict(defect="D4", reason="splats degrade to a PointSet", checks=["roundtrip_delta"])])
        res = by_check(gate.evaluate_scene(measured(), e, TOL))
        self.assertEqual(res["roundtrip_delta"]["known"], ["D4"])
        self.assertEqual(res["geometry_delta"]["known"], [])
        worse = by_check(gate.evaluate_scene(measured(roundtrip=dict(render_ok=True, mean_abs_delta=9.0, flip=0.05)), e, TOL))
        self.assertEqual(worse["roundtrip_delta"]["status"], "FAIL")   # known only explains the baseline value, it is no free pass


class EmptyGlb(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(gate.classify_glb(36, 0, 0), "triangles")
        self.assertEqual(gate.classify_glb(36, 5, 0), "triangles")
        self.assertEqual(gate.classify_glb(0, 3, 0), "points")
        self.assertEqual(gate.classify_glb(0, 0, 2), "lines")
        self.assertEqual(gate.classify_glb(0, 1, 1), "points+lines")
        self.assertEqual(gate.classify_glb(0, 0, 0), "empty")

    def glb_for(self, cls, tris=0):
        return {"class": cls, "triangles": tris, "points": 1 if "points" in cls else 0, "lines": 1 if "lines" in cls else 0}

    def test_empty_glb_with_x3d_geometry_fails_although_the_validator_is_clean(self):
        m = measured(glb=self.glb_for("empty"))
        res = by_check(gate.evaluate_scene(m, baseline_entry(glb={"class": "empty", "triangles": 0}), TOL))
        self.assertEqual(res["validator"]["status"], "PASS")
        self.assertEqual(res["glb_content"]["status"], "FAIL")
        self.assertIn("EMPTY", res["glb_content"]["detail"])
        self.assertIn("surface", res["glb_content"]["detail"])

    def test_empty_glb_allowed_only_by_a_baseline_entry_with_a_reason(self):
        m = measured(glb=self.glb_for("empty"))
        e = baseline_entry(allow_empty=dict(reason="the Inline target is a glb the importer cannot read"))
        r = by_check(gate.evaluate_scene(m, e, TOL))["glb_content"]
        self.assertEqual(r["status"], "PASS")
        self.assertIn("allowed: the Inline target", r["detail"])
        self.assertEqual(gate.lint_baseline(dict(scenes=dict(s=e))), [])
        e["allow_empty"]["reason"] = ""
        self.assertTrue(gate.lint_baseline(dict(scenes=dict(s=e))))

    def test_allow_empty_that_is_no_longer_needed_is_flagged_as_an_improvement(self):
        e = baseline_entry(allow_empty=dict(reason="was empty"))
        r = by_check(gate.evaluate_scene(measured(), e, TOL))["glb_content"]
        self.assertEqual(r["status"], "IMPROVED")

    def test_empty_glb_of_an_empty_scene_passes(self):
        m = measured(glb=self.glb_for("empty"), x3d=dict(surface=False, lines=False, points=False, splats=False))
        r = by_check(gate.evaluate_scene(m, baseline_entry(glb={"class": "empty", "triangles": 0}), TOL))["glb_content"]
        self.assertEqual(r["status"], "PASS")

    def test_points_only_glb_is_classified_separately(self):
        pts = measured(glb=self.glb_for("points"), x3d=dict(surface=False, lines=False, points=True, splats=True))
        r = by_check(gate.evaluate_scene(pts, baseline_entry(glb={"class": "points", "triangles": 0}), TOL))["glb_content"]
        self.assertEqual(r["status"], "PASS")
        self.assertIn("points-only glb", r["detail"])
        surf = measured(glb=self.glb_for("points"), x3d=dict(surface=True, lines=False, points=True, splats=False))
        r = by_check(gate.evaluate_scene(surf, baseline_entry(glb={"class": "points", "triangles": 0}), TOL))["glb_content"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("points-only glb", r["detail"])
        lines = measured(glb=self.glb_for("lines"), x3d=dict(surface=False, lines=True, points=False, splats=False))
        self.assertEqual(by_check(gate.evaluate_scene(lines, baseline_entry(glb={"class": "lines", "triangles": 0}), TOL))["glb_content"]["status"], "PASS")

    def test_triangle_count_may_not_fall_below_baseline(self):
        e = baseline_entry(glb={"class": "triangles", "triangles": 1000})
        for tris, want in [(1000, "PASS"), (990, "PASS"), (989, "FAIL"), (2000, "PASS")]:   # tolerance 1%
            m = measured(glb={"class": "triangles", "triangles": tris, "points": 0, "lines": 0})
            self.assertEqual(by_check(gate.evaluate_scene(m, e, TOL))["glb_content"]["status"], want, tris)

    def test_primitive_modes_read_from_a_real_glb_container(self):
        js = dict(asset=dict(version="2.0"), meshes=[dict(primitives=[dict(mode=0), dict(mode=1), dict(mode=3), dict(), dict(mode=5)])])
        body = json.dumps(js).encode()
        body += b" " * (-len(body) % 4)
        data = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(body)) + struct.pack("<II", len(body), 0x4E4F534A) + body
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.glb"
            p.write_bytes(data)
            self.assertEqual(gate.glb_primitive_counts(str(p)), (1, 2, 2))
            p.write_bytes(b"nope")
            with self.assertRaises(ValueError):
                gate.glb_primitive_counts(str(p))

    def test_x3d_renderable_kinds(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "a.x3d").write_text('<X3D><Scene><Shape><PointSet/></Shape><Shape><IndexedLineSet/></Shape></Scene></X3D>')
            self.assertEqual(gate.x3d_renderables(str(td / "a.x3d")), dict(surface=False, lines=True, points=True, splats=False))
            (td / "b.x3d").write_text('<X3D><Scene><Inline url=\'"a.x3d" "x"\'/><Shape><Box/></Shape></Scene></X3D>')
            self.assertEqual(gate.x3d_renderables(str(td / "b.x3d")), dict(surface=True, lines=True, points=True, splats=False))
            (td / "c.x3d").write_text('<X3D><Scene><Inline url=\'"a.x3d"\'/></Scene></X3D>')
            self.assertTrue(gate.x3d_renderables(str(td / "c.x3d"))["points"])   # geometry that only an Inline brings counts
            (td / "d.x3d").write_text('<X3D><Scene><ProtoDeclare name="P"><ProtoBody><Shape><Box/></Shape></ProtoBody></ProtoDeclare><Viewpoint/></Scene></X3D>')
            self.assertEqual(gate.x3d_renderables(str(td / "d.x3d")), dict(surface=False, lines=False, points=False, splats=False))
            (td / "e.x3d").write_text('<X3D><Scene><GaussianSplats/></Scene></X3D>')
            self.assertTrue(gate.x3d_renderables(str(td / "e.x3d"))["splats"])
            (td / "loop.x3d").write_text('<X3D><Scene><Inline url=\'"loop.x3d"\'/></Scene></X3D>')
            self.assertFalse(any(gate.x3d_renderables(str(td / "loop.x3d")).values()))   # an Inline cycle terminates
            self.assertFalse(any(gate.x3d_renderables(str(td / "missing.x3d")).values()))


class BaselineUpdate(unittest.TestCase):
    def base(self):
        return dict(schema=gate.BASELINE_SCHEMA, tolerance=TOL, scenes=dict(s=baseline_entry()))

    def test_new_scene_is_recorded(self):
        new, moves, ref = gate.merge_baseline(dict(scenes={}), dict(s=measured()))
        self.assertEqual(ref, [])
        self.assertEqual(new["scenes"]["s"], baseline_entry())
        self.assertTrue(any("new scene" in x for x in moves))

    def test_worse_values_are_refused_and_keep_the_old_threshold(self):
        old = self.base()
        m = measured(geometry_delta=9.0, roundtrip=dict(render_ok=True, mean_abs_delta=7.0, flip=0.2),
                     reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=0, nodes_lost=3, lost_types=[]),
                     validator=dict(ok_ran=True, errors=0, warnings=2, version="v"))
        new, moves, ref = gate.merge_baseline(old, dict(s=m))
        self.assertEqual(new["scenes"]["s"], old["scenes"]["s"])
        joined = "\n".join(ref)
        for key in ("geometry_delta 2.0 -> 9.0", "roundtrip.mean_abs_delta 5.0 -> 7.0", "roundtrip.flip 0.05 -> 0.2",
                    "reexport.nodes_lost 1 -> 3", "validator.warnings 0 -> 2"):
            self.assertIn(key, joined)
        self.assertEqual(moves, [])

    def test_allow_worse_loosens_and_says_so(self):
        old = self.base()
        new, moves, ref = gate.merge_baseline(old, dict(s=measured(geometry_delta=9.0)), allow_worse=True)
        self.assertEqual(new["scenes"]["s"]["geometry_delta"], 9.0)
        self.assertEqual(ref, [])
        self.assertTrue(any("LOOSENED" in x for x in moves))

    def test_better_values_tighten_and_noise_is_ignored(self):
        old = self.base()
        new, moves, ref = gate.merge_baseline(old, dict(s=measured(geometry_delta=1.995, roundtrip=dict(render_ok=True, mean_abs_delta=3.0, flip=0.05))))
        self.assertEqual(new["scenes"]["s"]["geometry_delta"], 2.0)             # 0.005 is noise: no churn on a rerun
        self.assertEqual(new["scenes"]["s"]["roundtrip"]["mean_abs_delta"], 3.0)
        self.assertTrue(any("tightened" in x for x in moves))
        self.assertEqual(ref, [])
        again, moves2, _ = gate.merge_baseline(new, dict(s=measured(geometry_delta=1.995, roundtrip=dict(render_ok=True, mean_abs_delta=3.0, flip=0.05))))
        self.assertEqual(again, new)
        self.assertEqual(moves2, [])

    def test_losing_the_visible_geometry_is_worse(self):
        new, moves, ref = gate.merge_baseline(self.base(), dict(s=measured(geometry_delta=None)))
        self.assertEqual(new["scenes"]["s"]["geometry_delta"], 2.0)
        self.assertTrue(ref)

    def test_triangles_are_a_floor(self):
        old = dict(scenes=dict(s=baseline_entry(glb={"class": "triangles", "triangles": 1000, "points": 0, "lines": 0})))
        m = lambda t: measured(glb={"class": "triangles", "triangles": t, "points": 0, "lines": 0})  # noqa: E731
        new, moves, ref = gate.merge_baseline(old, dict(s=m(900)))
        self.assertEqual(new["scenes"]["s"]["glb"]["triangles"], 1000)
        self.assertTrue(ref)
        new, moves, ref = gate.merge_baseline(old, dict(s=m(995)))   # inside the tolerance: unchanged
        self.assertEqual((new["scenes"]["s"]["glb"]["triangles"], ref, moves), (1000, [], []))
        new, moves, ref = gate.merge_baseline(old, dict(s=m(1500)))
        self.assertEqual(new["scenes"]["s"]["glb"]["triangles"], 1500)

    def test_hard_failures_are_never_recorded(self):
        bad_cases = [
            measured(validator=dict(ok_ran=True, errors=1, warnings=0, version="v")),
            measured(glb={"class": "empty", "triangles": 0, "points": 0, "lines": 0}),
            measured(glb_leg=dict(ok=False, error="boom")),
            measured(reexport=dict(leg_ok=True, well_formed=False, x3d_py="ok", x3d_py_errors=0, nodes_lost=0)),
            measured(reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=2, nodes_lost=0)),
        ]
        for m in bad_cases:
            new, moves, ref = gate.merge_baseline(dict(scenes={}), dict(s=m))
            self.assertNotIn("s", new["scenes"], m)
            self.assertTrue(ref, m)

    def test_allow_worse_records_failures_only_as_unexplained_entries_that_fail_the_lint(self):
        m = measured(glb={"class": "empty", "triangles": 0, "points": 0, "lines": 0})
        new, moves, ref = gate.merge_baseline(dict(scenes={}), dict(s=m), allow_worse=True)
        self.assertEqual(ref, [])
        self.assertTrue(new["scenes"]["s"]["allow_empty"]["reason"].startswith("UNEXPLAINED"))
        self.assertTrue(any("UNEXPLAINED" in p for p in gate.lint_baseline(new)))
        m = measured(glb_leg=dict(ok=False, error="boom"))
        new, moves, ref = gate.merge_baseline(dict(scenes={}), dict(s=m), allow_worse=True)
        self.assertTrue(new["scenes"]["s"]["skip"]["validator"].startswith("UNEXPLAINED"))

    def test_hand_written_entries_survive_an_update(self):
        e = baseline_entry(known=[dict(defect="D1", reason="light scoping", checks=["roundtrip_delta"])],
                           skip=dict(geometry_delta="page crash"), allow_empty=dict(reason="inline glb"))
        old = dict(scenes=dict(s=e))
        new, _, _ = gate.merge_baseline(old, dict(s=measured(roundtrip=dict(render_ok=True, mean_abs_delta=1.0, flip=0.01))))
        for k in ("known", "skip", "allow_empty"):
            self.assertEqual(new["scenes"]["s"][k], e[k])
        self.assertEqual(new["scenes"]["s"]["roundtrip"]["mean_abs_delta"], 1.0)

    def test_scenes_not_run_are_left_alone(self):
        old = self.base()
        old["scenes"]["other"] = baseline_entry()
        new, _, _ = gate.merge_baseline(old, dict(s=measured()))
        self.assertEqual(new["scenes"]["other"], baseline_entry())

    def test_lint(self):
        good = dict(scenes=dict(s=baseline_entry(known=[dict(defect="D4", reason="r", checks=["roundtrip_delta"])], skip=dict(reexport="why"))))
        self.assertEqual(gate.lint_baseline(good), [])
        for bad in (dict(known=[dict(defect="splats", reason="r", checks=[])]), dict(known=[dict(defect="D4", reason="r", checks=["nope"])]),
                    dict(known=[dict(defect="D4", reason="", checks=[])]), dict(skip=dict(nope="r")), dict(skip=dict(reexport="UNEXPLAINED: x"))):
            self.assertTrue(gate.lint_baseline(dict(scenes=dict(s=baseline_entry(**bad)))), bad)


def blank_measurement(**over):
    """stars-splats as it was measured: points-only glb, every render pure background (the F2 scene)."""
    m = measured(xite_foreground_share=0.0, geometry_delta=None, geometry_share=0.0, geometry_missing_share=0.0,
                 glb={"class": "points", "triangles": 0, "points": 1, "lines": 0},
                 x3d=dict(surface=False, lines=False, points=True, splats=True),
                 roundtrip=dict(render_ok=True, mean_abs_delta=0.0, flip=0.0))
    m.update(over)
    return m


def blank_entry(**over):
    e = baseline_entry(glb={"class": "points", "triangles": 0, "points": 1, "lines": 0}, geometry_delta=None,
                       roundtrip=dict(mean_abs_delta=0.0, flip=0.0), geometry_share=0.0, geometry_missing_share=0.0)
    e.update(over)
    return e


class VacuousRenders(unittest.TestCase):
    """F2: a render check that passes because every render is background passes without measuring anything."""

    def test_blank_renders_with_null_baseline_no_longer_pass(self):
        res = by_check(gate.evaluate_scene(blank_measurement(), blank_entry(), TOL))
        self.assertEqual(res["geometry_delta"]["status"], "FAIL")
        self.assertIn("vacuous", res["geometry_delta"]["detail"])
        self.assertIn("allow_blank", res["geometry_delta"]["detail"])
        self.assertEqual(res["roundtrip_delta"]["status"], "FAIL")
        self.assertIn("vacuous", res["roundtrip_delta"]["detail"])
        self.assertEqual(gate.scene_verdict(list(res.values())), "FAIL")

    def test_zero_deltas_do_not_pass_a_blank_reference(self):
        m = measured(xite_foreground_share=0.0, roundtrip=dict(render_ok=True, mean_abs_delta=0.0, flip=0.0))
        e = baseline_entry(roundtrip=dict(mean_abs_delta=0.0, flip=0.0))
        self.assertEqual(by_check(gate.evaluate_scene(m, e, TOL))["roundtrip_delta"]["status"], "FAIL")
        m["xite_foreground_share"] = 0.02   # the same numbers on a reference that shows something are a real zero
        self.assertEqual(by_check(gate.evaluate_scene(m, e, TOL))["roundtrip_delta"]["status"], "PASS")

    def test_x_ite_blank_while_babylon_draws_is_vacuous_too(self):
        r = by_check(gate.evaluate_scene(measured(xite_foreground_share=0.0), baseline_entry(), TOL))["geometry_delta"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("X_ITE renders only the background", r["detail"])

    def test_allow_blank_with_a_written_reason_passes_and_says_so(self):
        e = blank_entry(allow_blank=dict(reason="X_ITE draws no splats in SwiftShader (Confirmed 13 Nov 2026)"))
        res = by_check(gate.evaluate_scene(blank_measurement(), e, TOL))
        for chk in ("geometry_delta", "roundtrip_delta"):
            self.assertEqual(res[chk]["status"], "PASS", chk)
            self.assertIn("not measured", res[chk]["detail"])
            self.assertIn("allowed: X_ITE draws no splats", res[chk]["detail"])
        self.assertEqual(gate.lint_baseline(dict(scenes=dict(s=e))), [])
        e["allow_blank"]["reason"] = " "
        self.assertTrue(gate.lint_baseline(dict(scenes=dict(s=e))))
        e["allow_blank"]["reason"] = "UNEXPLAINED: recorded by --allow-worse"
        self.assertTrue(gate.lint_baseline(dict(scenes=dict(s=e))))

    def test_allow_empty_covers_a_scene_with_nothing_to_draw(self):
        m = blank_measurement(glb={"class": "empty", "triangles": 0, "points": 0, "lines": 0},
                              x3d=dict(surface=False, lines=False, points=False, splats=False))
        e = blank_entry(glb={"class": "empty", "triangles": 0, "points": 0, "lines": 0}, allow_empty=dict(reason="a placeholder Shape"))
        res = by_check(gate.evaluate_scene(m, e, TOL))
        self.assertEqual(res["geometry_delta"]["status"], "PASS")
        self.assertEqual(res["roundtrip_delta"]["status"], "PASS")

    def test_a_skip_entry_still_outranks(self):
        e = blank_entry(skip=dict(geometry_delta="page crash", roundtrip_delta="page crash"))
        res = by_check(gate.evaluate_scene(blank_measurement(), e, TOL))
        self.assertEqual(res["geometry_delta"]["status"], "SKIP")
        self.assertEqual(res["roundtrip_delta"]["status"], "SKIP")

    def test_babylon_drawing_nothing_of_a_glb_with_triangles_is_vacuous(self):
        # X_ITE shows the scene, Babylon.js draws no pixel of a glb that holds 100 triangles, and the baseline never saw geometry either
        m = measured(geometry_delta=None, geometry_share=0.0)
        r = by_check(gate.evaluate_scene(m, baseline_entry(geometry_delta=None, geometry_share=0.0), TOL))["geometry_delta"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("100 triangles that Babylon.js did not draw", r["detail"])

    def test_an_allow_blank_that_is_no_longer_needed_is_flagged(self):
        e = baseline_entry(allow_blank=dict(reason="was blank"))
        res = gate.evaluate_scene(measured(), e, TOL)
        row = by_check(res)["baseline"]
        self.assertEqual(row["status"], "IMPROVED")
        self.assertIn("allow_blank", row["detail"])
        self.assertEqual(gate.scene_verdict(res), "IMPROVED")

    def test_update_does_not_record_a_vacuous_render_without_a_reason(self):
        new, moves, ref = gate.merge_baseline(dict(scenes={}), dict(s=blank_measurement()))
        self.assertNotIn("s", new["scenes"])
        self.assertTrue(any("VACUOUS" in x for x in ref), ref)
        # --allow-worse records it, with a reason a person must replace (the lint fails until then)
        new, moves, ref = gate.merge_baseline(dict(scenes={}), dict(s=blank_measurement()), allow_worse=True)
        self.assertTrue(new["scenes"]["s"]["allow_blank"]["reason"].startswith("UNEXPLAINED"))
        self.assertTrue(any("UNEXPLAINED" in p for p in gate.lint_baseline(new)))
        # with the written reason in place the update records the numbers and refuses nothing
        old = dict(scenes=dict(s=blank_entry(allow_blank=dict(reason="X_ITE draws no splats"))))
        new, moves, ref = gate.merge_baseline(old, dict(s=blank_measurement()))
        self.assertEqual(ref, [])
        self.assertEqual(new["scenes"]["s"]["allow_blank"], old["scenes"]["s"]["allow_blank"])   # hand-written, never touched

    def test_update_does_not_record_a_scene_without_renders(self):
        m = measured(glb_render_ok=False, roundtrip=dict(render_ok=False))
        new, moves, ref = gate.merge_baseline(dict(scenes={}), dict(s=m))
        self.assertNotIn("s", new["scenes"])
        self.assertIn("render missing", "\n".join(ref))
        new, _, ref = gate.merge_baseline(dict(scenes={}), dict(s=m), allow_worse=True)
        self.assertTrue(new["scenes"]["s"]["skip"]["geometry_delta"].startswith("UNEXPLAINED"))
        self.assertTrue(new["scenes"]["s"]["skip"]["roundtrip_delta"].startswith("UNEXPLAINED"))


class GeometryTheDeltaCannotSee(unittest.TestCase):
    """F3: geometry_delta is a mean over the pixels Babylon.js drew, so geometry the glb lost does not move it."""

    def check(self, m=None, e=None):
        return by_check(gate.evaluate_scene(m or measured(), e or baseline_entry(), TOL))["geometry_delta"]

    def test_pixels_x_ite_draws_and_babylon_leaves_empty_fail_although_the_delta_is_unchanged(self):
        r = self.check(measured(geometry_missing_share=0.08))   # delta still 2.0
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("X_ITE draws 0.08 of the frame", r["detail"])
        self.assertEqual(self.check(measured(geometry_missing_share=0.011))["status"], "PASS")   # inside max(0.002, 10%)
        self.assertEqual(self.check(measured(geometry_missing_share=0.013))["status"], "FAIL")

    def test_babylon_covering_less_of_the_frame_fails(self):
        self.assertEqual(self.check(measured(geometry_share=0.28))["status"], "PASS")    # floor 0.3 - max(0.002, 10%) = 0.27
        r = self.check(measured(geometry_share=0.26))
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("covers 0.26 of the frame", r["detail"])

    def test_animated_scene_override_widens_the_share_rules_only(self):
        e = baseline_entry(tolerance=dict(geometry_share=dict(abs=0.02), reason="animated: sampled at run-dependent moments"))
        self.assertEqual(self.check(measured(geometry_missing_share=0.025), e)["status"], "PASS")
        self.assertEqual(self.check(measured(geometry_missing_share=0.05), e)["status"], "FAIL")
        self.assertEqual(self.check(measured(geometry_delta=9.0), e)["status"], "FAIL")   # the delta keeps the header rule
        self.assertEqual(gate.lint_baseline(dict(scenes=dict(s=e))), [])
        e["tolerance"].pop("reason")
        self.assertTrue(gate.lint_baseline(dict(scenes=dict(s=e))))

    def test_a_baseline_without_the_shares_does_not_gate_them(self):
        e = baseline_entry()
        del e["geometry_share"], e["geometry_missing_share"]
        self.assertEqual(self.check(measured(geometry_missing_share=0.9, geometry_share=0.0), e)["status"], "PASS")

    def test_lost_lines_or_points_fail_even_when_the_triangles_are_all_there(self):
        e = baseline_entry(glb={"class": "triangles", "triangles": 100, "points": 5, "lines": 3})
        ok = measured(glb={"class": "triangles", "triangles": 100, "points": 5, "lines": 3})
        self.assertEqual(by_check(gate.evaluate_scene(ok, e, TOL))["glb_content"]["status"], "PASS")
        lost = measured(glb={"class": "triangles", "triangles": 100, "points": 5, "lines": 0})
        r = by_check(gate.evaluate_scene(lost, e, TOL))["glb_content"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("0 lines primitives < baseline 3", r["detail"])

    def test_update_treats_the_shares_as_floor_and_ceiling(self):
        old = dict(scenes=dict(s=baseline_entry()))
        new, moves, ref = gate.merge_baseline(old, dict(s=measured(geometry_missing_share=0.2)))
        self.assertEqual(new["scenes"]["s"]["geometry_missing_share"], 0.01)
        self.assertTrue(any("geometry_missing_share" in x for x in ref))
        new, moves, ref = gate.merge_baseline(old, dict(s=measured(geometry_share=0.1)))
        self.assertEqual(new["scenes"]["s"]["geometry_share"], 0.3)
        self.assertTrue(any("geometry_share" in x for x in ref))
        new, moves, ref = gate.merge_baseline(old, dict(s=measured(geometry_missing_share=0.0, geometry_share=0.5)))
        self.assertEqual((new["scenes"]["s"]["geometry_missing_share"], new["scenes"]["s"]["geometry_share"], ref), (0.0, 0.5, []))

    def test_a_class_change_follows_the_triangle_decision(self):
        # the glb dropped from 36 triangles to 18 lines: the triangles drop is refused, so the class must not be recorded as lines either
        old = dict(scenes=dict(s=baseline_entry(glb={"class": "triangles", "triangles": 36, "points": 0, "lines": 0})))
        m = measured(glb={"class": "lines", "triangles": 18, "points": 0, "lines": 1}, x3d=dict(surface=False, lines=True, points=False, splats=False))
        new, moves, ref = gate.merge_baseline(old, dict(s=m))
        self.assertEqual(new["scenes"]["s"]["glb"]["class"], "triangles")
        self.assertEqual(new["scenes"]["s"]["glb"]["triangles"], 36)
        self.assertTrue(any("glb.class" in x for x in ref) and any("glb.triangles" in x for x in ref), ref)
        # a class that gains kinds of geometry is an improvement and is recorded
        old = dict(scenes=dict(s=baseline_entry(glb={"class": "lines", "triangles": 0, "points": 0, "lines": 1})))
        m = measured(glb={"class": "triangles", "triangles": 40, "points": 0, "lines": 1})
        new, moves, ref = gate.merge_baseline(old, dict(s=m))
        self.assertEqual((new["scenes"]["s"]["glb"]["class"], ref), ("triangles", []))


class FlipFailure(unittest.TestCase):
    """F5: a FLIP that could not be computed must not switch the FLIP gate off."""

    def test_flip_none_fails_when_the_baseline_has_a_flip(self):
        m = measured(roundtrip=dict(render_ok=True, mean_abs_delta=5.0, flip=None, flip_error="flip-evaluator is not installed"))
        r = by_check(gate.evaluate_scene(m, baseline_entry(), TOL))["roundtrip_delta"]
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("FLIP not measured", r["detail"])
        self.assertIn("flip-evaluator is not installed", r["detail"])
        self.assertIn("0.05", r["detail"])

    def test_flip_none_without_a_baseline_flip_still_gates_the_delta(self):
        e = baseline_entry(roundtrip=dict(mean_abs_delta=5.0))
        m = measured(roundtrip=dict(render_ok=True, mean_abs_delta=5.0, flip=None))
        self.assertEqual(by_check(gate.evaluate_scene(m, e, TOL))["roundtrip_delta"]["status"], "PASS")
        m = measured(roundtrip=dict(render_ok=True, mean_abs_delta=9.0, flip=None))
        self.assertEqual(by_check(gate.evaluate_scene(m, e, TOL))["roundtrip_delta"]["status"], "FAIL")

    def test_a_tool_the_baseline_recorded_but_this_run_cannot_report_is_a_fingerprint_difference(self):
        base = dict(x_ite="16.7.1", flip_evaluator="1.7", x3d_py="4.0.65.8", numpy="2.5.3", pillow="12.3.0")
        self.assertEqual(gate.compare_fingerprint(base, dict(base)), {})
        self.assertEqual(gate.compare_fingerprint(base, dict(base, flip_evaluator=None)), {"flip_evaluator": ("1.7", None)})
        self.assertEqual(gate.compare_fingerprint(base, dict(base, x3d_py="4.0.66.0")), {"x3d_py": ("4.0.65.8", "4.0.66.0")})
        self.assertEqual(set(gate.compare_fingerprint(base, dict(base, numpy="2.6.0", pillow="13.0.0"))), {"numpy", "pillow"})
        self.assertEqual(gate.compare_fingerprint(dict(x_ite="16.7.1"), dict(x_ite="16.7.1", x3d_py="9")), {})   # a header without the key says nothing
        self.assertEqual(gate.compare_fingerprint(base, dict(base, chromium="150")), {})   # baseline lacks chromium here

    def test_the_fingerprint_names_the_python_libraries_the_checks_depend_on(self):
        import importlib.metadata as md
        fp = gate.fingerprint(str(RIG.parents[1] / "source"), {}, "153.0.1")
        self.assertEqual(set(("x3d_py", "numpy", "pillow", "flip_evaluator")) - set(fp), set())
        for key, pkg in (("x3d_py", "x3d"), ("numpy", "numpy"), ("pillow", "pillow"), ("flip_evaluator", "flip-evaluator")):
            try:
                want = md.version(pkg)
            except md.PackageNotFoundError:
                want = None
            self.assertEqual(fp[key], want, key)


class ToleranceHeader(unittest.TestCase):
    """F10: the baseline header cannot loosen the rules; they live in the code."""

    def test_header_must_equal_the_code_constant(self):
        self.assertEqual(gate.lint_baseline(dict(tolerance=copy.deepcopy(TOL), scenes={})), [])
        self.assertEqual(gate.lint_baseline(dict(scenes={})), [])
        for key, loose in (("flip", {"abs": 1.0, "rel": 0}), ("triangles", {"rel": 0.9}), ("image_delta", {"abs": 50, "rel": 1}),
                           ("geometry_share", {"abs": 1.0, "rel": 1})):
            tol = copy.deepcopy(TOL)
            tol[key] = loose
            problems = gate.lint_baseline(dict(tolerance=tol, scenes={}))
            self.assertTrue(any("tolerance header" in p for p in problems), key)
        tol = copy.deepcopy(TOL)
        del tol["flip"]
        self.assertTrue(gate.lint_baseline(dict(tolerance=tol, scenes={})))


class Report(unittest.TestCase):
    def test_report_lists_failures_improvements_known_and_the_summary(self):
        ok = gate.evaluate_scene(measured(), baseline_entry(), TOL)
        bad = gate.evaluate_scene(measured(geometry_delta=30.0, glb={"class": "empty", "triangles": 0, "points": 0, "lines": 0}),
                                  baseline_entry(known=[dict(defect="D7", reason="r", checks=["geometry_delta"])]), TOL)
        better = gate.evaluate_scene(measured(roundtrip=dict(render_ok=True, mean_abs_delta=1.0, flip=0.01)), baseline_entry(), TOL)
        rows = [dict(scene=n, verdict=gate.scene_verdict(c), checks=c) for n, c in (("a-ok", ok), ("b-bad", bad), ("c-better", better))]
        text = gate.format_report(rows, "FINGERPRINT differs", 12.0)
        self.assertIn("PASS     a-ok", text)
        self.assertIn("FAIL     b-bad", text)
        self.assertIn("IMPROVED c-better", text)
        self.assertIn("glb_content", text)
        self.assertIn("EMPTY glb", text)
        self.assertIn("[known D7]", text)
        self.assertIn("GATE FAIL: 2/3 scenes pass, 1 fail: b-bad", text)
        self.assertIn("1 improved", text)
        self.assertIn("FINGERPRINT differs", text)
        all_ok = gate.format_report(rows[:1])
        self.assertIn("GATE PASS: 1/1", all_ok)

    def test_fingerprint_comparison(self):
        base = dict(x_ite="16.7.1", babylon="9.32.0", chromium="153.0.7000.1", blender="5.3.0", validator="2.0.0-dev.3.10", addon_git_revision="aaa")
        same = dict(base, chromium="153.0.9999.9", addon_git_revision="bbb")
        self.assertEqual(gate.compare_fingerprint(base, same), {})
        self.assertEqual(gate.compare_fingerprint(base, dict(base, blender="4.5.1", chromium="154.0.1")),
                         {"blender": ("5.3.0", "4.5.1"), "chromium": ("153", "154")})
        self.assertEqual(gate.compare_fingerprint(None, same), {})


class Flow(unittest.TestCase):
    """main() with the measuring stubbed out: results are written before the exit code, update refusals exit 1."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)
        self.scenes = self.dir / "scenes.json"
        self.scenes.write_text(json.dumps([dict(name="s", x3d="probes/p1-point-physical.x3d")]))
        self.baseline = self.dir / "baseline.json"
        self.label = "gate-unit-test-" + str(os.getpid())
        self.meas = dict(s=measured(), t=measured())
        self.orig = gate.run_gate
        gate.run_gate = lambda scenes, label, src, jobs=1, chunk=8, reuse=False: (
            {sc["name"]: copy.deepcopy(self.meas[sc["name"]]) for sc in scenes}, "153.0.1")   # only the scenes asked for, like the real thing
        self.fp = dict(x_ite="16.7.1", babylon="9.32.0", blender="5.3.0", validator="2.0.0-dev.3.10", flip_evaluator="1.7",
                       x3d_py="4.0.65.8", numpy="2.5.3", pillow="12.3.0", addon_git_revision="abc", addon_source_dirty=False)
        self.orig_fp = gate.fingerprint
        gate.fingerprint = lambda src, ms, chromium: dict(self.fp, chromium=chromium)
        self.outdir = RIG / "out" / self.label

    def tearDown(self):
        gate.run_gate, gate.fingerprint = self.orig, self.orig_fp
        import shutil
        shutil.rmtree(self.outdir, ignore_errors=True)
        self.td.cleanup()

    def run_main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gate.main(["--scenes", str(self.scenes), "--baseline", str(self.baseline), "--label", self.label, *args])
        return code, buf.getvalue()

    def test_update_then_check_then_regression(self):
        code, out = self.run_main("--update-baseline")
        self.assertEqual(code, 0, out)
        written = json.loads(self.baseline.read_text())
        self.assertEqual(written["scenes"]["s"], baseline_entry())
        self.assertEqual(written["rig"]["x_ite"], "16.7.1")
        self.assertEqual(written["schema"], gate.BASELINE_SCHEMA)
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("GATE PASS", out)
        self.meas["s"]["geometry_delta"] = 50.0
        json_out = self.dir / "res.json"
        code, out = self.run_main("--json", str(json_out))
        self.assertEqual(code, 1)
        self.assertIn("FAIL     s", out)
        results = json.loads((self.outdir / "gate_results.json").read_text())   # written whatever the verdict
        self.assertEqual(results["scenes"][0]["verdict"], "FAIL")
        self.assertEqual(json.loads(json_out.read_text())["schema"], gate.RESULTS_SCHEMA)

    def test_update_refuses_to_loosen_without_allow_worse(self):
        self.run_main("--update-baseline")
        self.meas["s"]["geometry_delta"] = 50.0
        code, out = self.run_main("--update-baseline")
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", out)
        self.assertEqual(json.loads(self.baseline.read_text())["scenes"]["s"]["geometry_delta"], 2.0)
        code, out = self.run_main("--update-baseline", "--allow-worse")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(self.baseline.read_text())["scenes"]["s"]["geometry_delta"], 50.0)
        self.assertIn("LOOSENED", out)

    def test_improvement_is_reported_and_can_fail_the_run(self):
        self.run_main("--update-baseline")
        self.meas["s"]["roundtrip"] = dict(render_ok=True, mean_abs_delta=0.5, flip=0.01)
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("IMPROVED", out)
        code, out = self.run_main("--fail-on-improvement")
        self.assertEqual(code, 1)

    def test_unexplained_baseline_reason_fails_the_run(self):
        self.run_main("--update-baseline")
        data = json.loads(self.baseline.read_text())
        data["scenes"]["s"]["skip"] = dict(reexport="UNEXPLAINED: left by --allow-worse")
        self.baseline.write_text(json.dumps(data))
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("BASELINE LINT", out)

    def write_scenes(self, *names):
        self.scenes.write_text(json.dumps([dict(name=n, x3d="probes/p1-point-physical.x3d") for n in names]))

    def test_zero_scenes_is_an_error_not_a_green_run(self):   # F11
        self.scenes.write_text("[]")
        with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()):
            gate.main(["--scenes", str(self.scenes), "--baseline", str(self.baseline), "--label", self.label])
        self.assertIn("no scenes to run", str(cm.exception))
        self.assertFalse((self.outdir / "gate_results.json").exists())   # nothing was "measured"
        # one empty file next to a real one is fine
        other = self.dir / "other.json"
        other.write_text("[]")
        self.write_scenes("s")
        self.run_main("--update-baseline")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gate.main(["--scenes", str(other), str(self.scenes), "--baseline", str(self.baseline), "--label", self.label])
        self.assertEqual(code, 0, buf.getvalue())

    def test_a_loosened_tolerance_header_fails_the_run(self):   # F10
        self.run_main("--update-baseline")
        data = json.loads(self.baseline.read_text())
        data["tolerance"]["flip"] = {"abs": 1.0, "rel": 0}
        self.baseline.write_text(json.dumps(data))
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("BASELINE LINT: tolerance header differs", out)

    def test_a_flip_that_cannot_be_computed_fails_the_run(self):   # F5
        self.run_main("--update-baseline")
        self.meas["s"]["roundtrip"] = dict(render_ok=True, mean_abs_delta=5.0, flip=None, flip_error="boom")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("FLIP not measured (boom)", out)

    def test_a_missing_python_library_is_a_strict_fingerprint_failure(self):   # F5, F6
        self.run_main("--update-baseline")
        self.assertEqual(json.loads(self.baseline.read_text())["rig"]["x3d_py"], "4.0.65.8")
        self.fp["flip_evaluator"] = None
        code, out = self.run_main()
        self.assertEqual(code, 0)   # without --strict-fingerprint it only warns
        self.assertIn("flip_evaluator 1.7 -> None", out)
        code, out = self.run_main("--strict-fingerprint")
        self.assertEqual(code, 1)
        self.fp["flip_evaluator"], self.fp["x3d_py"] = "1.7", "4.0.66.0"
        code, out = self.run_main("--strict-fingerprint")
        self.assertEqual(code, 1)
        self.assertIn("x3d_py 4.0.65.8 -> 4.0.66.0", out)

    def test_a_partial_update_on_another_rig_does_not_restamp_the_header(self):   # F8a
        self.write_scenes("s", "t")
        self.run_main("--update-baseline")
        before = self.baseline.read_text()
        self.fp["blender"] = "5.4.0"
        self.write_scenes("s")
        self.meas["s"]["geometry_delta"] = 1.0   # a real improvement that would otherwise be recorded
        code, out = self.run_main("--update-baseline")
        self.assertEqual(code, 1)
        self.assertIn("BASELINE UPDATE REFUSED", out)
        self.assertIn("blender 5.3.0 -> 5.4.0", out)
        self.assertEqual(self.baseline.read_text(), before)   # nothing was written
        # a full run on the new rig re-baselines the header
        self.write_scenes("s", "t")
        code, out = self.run_main("--update-baseline")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(self.baseline.read_text())["rig"]["blender"], "5.4.0")

    def test_a_partial_update_on_the_same_rig_is_fine_and_keeps_the_other_scenes(self):   # F8a
        self.write_scenes("s", "t")
        self.run_main("--update-baseline")
        self.write_scenes("s")
        self.meas["s"]["geometry_delta"] = 1.0
        code, out = self.run_main("--update-baseline")
        self.assertEqual(code, 0, out)
        data = json.loads(self.baseline.read_text())
        self.assertEqual((data["scenes"]["s"]["geometry_delta"], data["scenes"]["t"]["geometry_delta"]), (1.0, 2.0))

    def test_update_exits_1_when_it_leaves_a_scene_failing(self):   # F8b
        self.run_main("--update-baseline")
        # FLIP could not be computed: the update cannot record a value, and the scene fails against the baseline it just wrote
        self.meas["s"]["roundtrip"] = dict(render_ok=True, mean_abs_delta=5.0, flip=None, flip_error="boom")
        code, out = self.run_main("--update-baseline")
        self.assertEqual(code, 1, out)
        self.assertIn("update leaves 1 scene(s) failing", out)
        self.assertIn("GATE FAIL", out)

    def test_update_refuses_a_new_scene_whose_renders_crashed(self):   # F8b
        self.write_scenes("s", "t")
        self.run_main("--update-baseline")
        data = json.loads(self.baseline.read_text())
        del data["scenes"]["t"]
        self.baseline.write_text(json.dumps(data))
        self.meas["t"] = measured(glb_render_ok=False, geometry_delta=None, roundtrip=dict(render_ok=False))
        code, out = self.run_main("--update-baseline")
        self.assertEqual(code, 1)
        self.assertIn("render missing", out)
        self.assertNotIn("t", json.loads(self.baseline.read_text())["scenes"])

    def test_fingerprint_difference_warns_and_strict_fails(self):
        self.run_main("--update-baseline")
        data = json.loads(self.baseline.read_text())
        data["rig"]["blender"] = "4.5.0"
        self.baseline.write_text(json.dumps(data))
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("FINGERPRINT differs", out)
        code, out = self.run_main("--strict-fingerprint")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
