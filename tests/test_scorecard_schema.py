# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorecard results schema: record constructors, validator verdicts and marks, check_results. Needs no browser and no Blender."""
import copy
import unittest

import scorecard_fixtures as fx
from scorecard import schema


class VerdictTests(unittest.TestCase):
    SUM = dict(errors=0, warnings=0, triangles=24, version="2.0.0-dev.3.10", infos=0, hints=0)

    def test_pass(self):
        v = schema.gltf_verdict(self.SUM, None, True)
        self.assertEqual(v["verdict"], "pass")
        self.assertFalse(v["empty"])
        self.assertEqual(schema.mark(v), "✓")

    def test_warnings_mark(self):
        v = schema.gltf_verdict(dict(self.SUM, warnings=2), None, True)
        self.assertEqual(v["verdict"], "pass")
        self.assertEqual(schema.mark(v), "✓w")

    def test_errors_fail(self):
        v = schema.gltf_verdict(dict(self.SUM, errors=3), None, True)
        self.assertEqual((v["verdict"], schema.mark(v)), ("fail", "✗"))

    def test_zero_triangles_with_geometry_is_empty(self):
        """A glb that validates but draws nothing, from an X3D that has geometry: the structure-only validator passes it, the gate must not."""
        v = schema.gltf_verdict(dict(self.SUM, triangles=0), None, True)
        self.assertEqual((v["verdict"], v["empty"], schema.mark(v)), ("empty", True, "∅"))

    def test_zero_triangles_without_geometry_is_not_empty(self):
        v = schema.gltf_verdict(dict(self.SUM, triangles=0), None, False)
        self.assertEqual(v["verdict"], "pass")
        self.assertTrue(v["zero_triangles"])
        self.assertFalse(v["empty"])

    def test_unknown_geometry_counts_as_empty(self):
        self.assertEqual(schema.gltf_verdict(dict(self.SUM, triangles=0), None, None)["verdict"], "empty")

    def test_errors_beat_empty(self):
        self.assertEqual(schema.gltf_verdict(dict(self.SUM, triangles=0, errors=1), None, True)["verdict"], "fail")

    def test_validator_did_not_run_is_never_a_pass(self):
        v = schema.gltf_verdict(None, "node missing", True)
        self.assertEqual((v["verdict"], schema.mark(v)), ("error", "?"))

    def test_x3d_marks(self):
        self.assertEqual(schema.mark(schema.x3d_verdict(dict(verdict="pass"))), "x✓")
        self.assertEqual(schema.mark(schema.x3d_verdict(dict(verdict="fail", error="boom"))), "x✗")
        self.assertEqual(schema.mark(schema.x3d_verdict(dict(verdict="not-checked"))), "x?")
        self.assertEqual(schema.mark(None), "")

    def test_mark_title_names_the_tool_result(self):
        t = schema.mark_title(schema.gltf_verdict(dict(self.SUM, triangles=0), None, True))
        self.assertIn("gltf-validator 2.0.0-dev.3.10", t)
        self.assertIn("EMPTY", t)


class RecordTests(unittest.TestCase):
    def test_new_record_has_every_field(self):
        r = schema.new_leg_record("xite", schema.NOT_RUN, "why")
        for k in ("leg", "engine", "engine_version", "status", "reason", "input", "validator", "image", "seconds", "config", "metrics", "notes", "tool"):
            self.assertIn(k, r)

    def test_records_do_not_share_mutable_state(self):
        a, b = schema.new_leg_record("xite"), schema.new_leg_record("xite")
        a["notes"].append("x")
        a["metrics"]["k"] = 1
        self.assertEqual((b["notes"], b["metrics"]), ([], {}))

    def test_registry(self):
        self.assertEqual(set(schema.LEG_IDS), {"xite", "babylon_addon_glb", "babylon_castle_glb", "castle_native", "blender_eevee", "blender_cycles"})
        self.assertEqual(schema.LEGS["blender_eevee"]["engine"], "Blender EEVEE (BLENDER_EEVEE)")
        self.assertNotIn("blender_cycles", schema.ENGINE_LEGS)
        self.assertEqual({k for k, v in schema.LEGS.items() if v["optional"]}, {"babylon_castle_glb", "castle_native"})


class CheckResultsTests(unittest.TestCase):
    def good(self):
        return fx.doc_from({"a": {"xite": 0.01, "babylon_addon_glb": 0.02}, "b": {"xite": 0.03, "babylon_addon_glb": 0.04}},
                           not_run=("castle_native", "babylon_castle_glb", "blender_eevee"))

    def test_conforming_document(self):
        self.assertEqual(schema.check_results(self.good()), [])

    def test_missing_leg_is_a_problem(self):
        d = self.good()
        del d["scenes"][0]["legs"]["castle_native"]
        self.assertTrue(any("castle_native" in p and "missing" in p for p in schema.check_results(d)))

    def test_not_run_needs_a_reason(self):
        d = self.good()
        d["scenes"][0]["legs"]["castle_native"]["reason"] = None
        self.assertTrue(any("needs a reason" in p for p in schema.check_results(d)))

    def test_ok_needs_validator_input_image_version(self):
        for field, text in (("validator", "validator"), ("input", "input"), ("image", "image"), ("engine_version", "engine_version")):
            d = self.good()
            d["scenes"][0]["legs"]["xite"][field] = None
            self.assertTrue(any(text in p for p in schema.check_results(d)), field)

    def test_validator_kind_must_match_input_kind(self):
        d = self.good()
        d["scenes"][0]["legs"]["babylon_addon_glb"]["validator"] = fx.X3D_OK
        self.assertTrue(any("does not match input kind" in p for p in schema.check_results(d)))

    def test_bad_status_and_wrong_schema_id(self):
        d = self.good()
        d["scenes"][0]["legs"]["xite"]["status"] = "maybe"
        d["schema"] = "other"
        probs = schema.check_results(d)
        self.assertTrue(any("status 'maybe'" in p for p in probs))
        self.assertTrue(any("schema is" in p for p in probs))

    def test_duplicate_scene_names(self):
        d = self.good()
        d["scenes"].append(copy.deepcopy(d["scenes"][0]))
        self.assertTrue(any("duplicate" in p for p in schema.check_results(d)))

    def test_malformed_documents_do_not_raise(self):
        for bad in (None, [], {}, {"schema": schema.SCHEMA, "scenes": "x"}, {"schema": schema.SCHEMA, "scenes": [1]}):
            self.assertIsInstance(schema.check_results(bad), list)
            self.assertTrue(schema.check_results(bad))


if __name__ == "__main__":
    unittest.main()
