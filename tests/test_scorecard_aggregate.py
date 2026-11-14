# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorecard aggregation: common scene set, engine means, paired difference against X_ITE, noise floor, not-run legs. No browser."""
import unittest

import scorecard_fixtures as fx
from scorecard import report, schema

TABLE = {
    "s1": {"xite": 0.10, "babylon_addon_glb": 0.06, "blender_eevee": 0.20},
    "s2": {"xite": 0.04, "babylon_addon_glb": 0.05, "blender_eevee": 0.08},
    "s3": {"xite": 0.20, "babylon_addon_glb": 0.10},                 # EEVEE has no result here
    "s4": {"xite": 0.02, "babylon_addon_glb": 0.01, "blender_eevee": 0.04},
}


def doc():
    return fx.doc_from(TABLE, not_run=("castle_native", "babylon_castle_glb"))


class AggregateTests(unittest.TestCase):
    def test_compared_legs_are_the_scored_engine_legs_in_registry_order(self):
        self.assertEqual(report.compared_legs(doc()), ["xite", "babylon_addon_glb", "blender_eevee"])

    def test_common_set_needs_every_compared_leg(self):
        d = doc()
        legs = report.compared_legs(d)
        self.assertEqual(report.common_set(d, legs), ["s1", "s2", "s4"])
        self.assertEqual(report.common_set(d, ["xite", "babylon_addon_glb"]), ["s1", "s2", "s3", "s4"])

    def test_failed_leg_leaves_the_common_set(self):
        d = fx.doc_from(TABLE, not_run=("castle_native", "babylon_castle_glb"), failed={("s2", "xite"): "render failed"})
        self.assertEqual(report.common_set(d, report.compared_legs(d)), ["s1", "s4"])

    def test_engine_means_over_common_and_own_sets(self):
        d = doc()
        legs = report.compared_legs(d)
        cs = report.common_set(d, legs)
        m = report.engine_means(d, legs, cs)
        self.assertAlmostEqual(m["xite"]["mean_common"], (0.10 + 0.04 + 0.02) / 3)
        self.assertAlmostEqual(m["xite"]["mean_own"], (0.10 + 0.04 + 0.20 + 0.02) / 4)
        self.assertEqual((m["xite"]["n_common"], m["xite"]["n_own"]), (3, 4))
        self.assertEqual((m["blender_eevee"]["n_common"], m["blender_eevee"]["n_own"]), (3, 3))
        self.assertAlmostEqual(m["blender_eevee"]["mean_common"], (0.20 + 0.08 + 0.04) / 3)
        self.assertAlmostEqual(m["babylon_addon_glb"]["geometry_common"], 4 * (0.06 + 0.05 + 0.01) / 3)

    def test_paired_difference_vs_xite(self):
        d = doc()
        p = report.paired_vs_xite(d, report.compared_legs(d))
        self.assertNotIn("xite", p)
        b = p["babylon_addon_glb"]
        diffs = [0.06 - 0.10, 0.05 - 0.04, 0.10 - 0.20, 0.01 - 0.02]
        self.assertAlmostEqual(b["mean_diff"], sum(diffs) / 4)
        self.assertEqual((b["n"], b["wins"], b["losses"], b["ties"]), (4, 3, 1, 0))
        self.assertEqual(p["blender_eevee"]["n"], 3)           # only the scenes both have
        self.assertEqual(p["blender_eevee"]["scenes"], ["s1", "s2", "s4"])

    def test_bootstrap_is_deterministic_and_brackets_the_mean(self):
        xs = [-0.04, 0.01, -0.1, -0.01, 0.02, -0.03]
        a, b = report.bootstrap_ci(xs), report.bootstrap_ci(xs)
        self.assertEqual(a, b)
        mean = sum(xs) / len(xs)
        self.assertLess(a[0], mean)
        self.assertGreater(a[1], mean)
        self.assertEqual(report.bootstrap_ci([0.1]), (None, None))

    def test_bootstrap_constant_sample_collapses(self):
        lo, hi = report.bootstrap_ci([0.05] * 6)
        self.assertAlmostEqual(lo, 0.05)
        self.assertAlmostEqual(hi, 0.05)

    def test_noise_floor(self):
        f = report.noise_floor(doc())
        self.assertEqual(f["n"], 4)
        self.assertAlmostEqual(f["mean"], 0.001)

    def test_not_run_legs_carry_their_reason(self):
        nr = report.not_run_legs(doc())
        self.assertEqual(set(nr), {"castle_native", "babylon_castle_glb"})
        self.assertIn("CASTLE_RENDER", nr["castle_native"]["reason"])
        self.assertEqual(nr["castle_native"]["statuses"], ["not-run"])

    def test_failures_listed_with_reasons(self):
        d = fx.doc_from(TABLE, failed={("s2", "xite"): "xite render failed: timeout"})
        self.assertIn(("s2", "xite", "failed", "xite render failed: timeout"), report.failures(d))

    def test_flip_of_ignores_non_ok_and_missing_metrics(self):
        r = schema.new_leg_record("xite", schema.FAILED, "x")
        r["metrics"] = {"flip_vs_reference": {"mean": 0.5}}
        self.assertIsNone(report.flip_of(r))
        self.assertIsNone(report.flip_of(None))
        self.assertIsNone(report.flip_of(fx.ok_rec("xite")))

    def test_validator_summary_counts_and_flags(self):
        empty = dict(fx.PASS_GLB, verdict="empty", triangles=0, empty=True)
        d = fx.doc_from({"a": {"xite": 0.1, "babylon_addon_glb": (0.1, empty)}, "b": {"xite": 0.1, "babylon_addon_glb": 0.2}})
        v = report.validator_summary(d)["babylon_addon_glb"]
        self.assertEqual(v["counts"], {"empty": 1, "pass": 1})
        self.assertEqual([f[0] for f in v["flagged"]], ["a"])
        self.assertEqual(report.validator_summary(d)["xite"]["kind"], "x3d-wellformed")

    def test_empty_run_aggregates_do_not_raise(self):
        d = fx.doc_from({})
        sm = report.summary(d)
        self.assertEqual((sm["legs"], sm["common"]), ([], []))


if __name__ == "__main__":
    unittest.main()
