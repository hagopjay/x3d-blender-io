# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorecard driver: --resume logic, leg selection, not-run recording and scoring, with fake legs (no browser, no Blender)."""
import json
import tempfile
import unittest
from pathlib import Path

import scorecard_fixtures as fx  # noqa: F401  (puts tools/ on sys.path)
from scorecard import legs as legs_pkg, run as run_mod, schema

try:
    import flip_evaluator  # noqa: F401
    import numpy  # noqa: F401
    from PIL import Image
    HAVE_STACK = True
except ImportError:
    HAVE_STACK = False

X3D = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="4.0"><Scene><Viewpoint position="0 0 6"/><Shape><Box/></Shape></Scene></X3D>
"""


class FakeLeg:
    """A leg module stand-in: writes a flat grey PNG per scene, counts calls, can fail chosen scenes or be unavailable."""
    def __init__(self, leg, grey, fail=(), unavailable=None):
        self.ID, self.grey, self.fail, self.unavailable, self.calls = leg, grey, set(fail), unavailable, []

    def available(self, ctx):
        return (False, self.unavailable) if self.unavailable else (True, "ok")

    def run(self, ctx, scenes):
        out = {}
        for s in scenes:
            self.calls.append(s.name)
            if s.name in self.fail:
                out[s.name] = legs_pkg.failed(f"{self.ID} fake failure")
                continue
            work = s.work / "fake"
            work.mkdir(parents=True, exist_ok=True)
            p = work / f"{self.ID}.png"
            Image.new("RGB", (64, 64), (self.grey,) * 3).save(p)
            kind = schema.LEGS[self.ID]["input_kind"]
            out[s.name] = legs_pkg.ok(
                engine_version=f"fake {self.ID}", image_src=str(p), seconds=dict(render=1.5), config=dict(size=ctx.size),
                input=dict(kind=kind, path=s.rel if kind == "x3d" else "work/x.glb", sha256=s.sha256, producer="fake"),
                validator=(schema.x3d_verdict(s.wellformed) if kind == "x3d" else schema.gltf_verdict(dict(errors=0, warnings=0, triangles=3), None, True)),
                tool="fake")
        return out


@unittest.skipUnless(HAVE_STACK, "numpy, Pillow and flip-evaluator are needed to score")
class DriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for n in ("one", "two"):
            (self.root / f"{n}.x3d").write_text(X3D)
        self.scenes = self.root / "scenes.json"
        self.scenes.write_text(json.dumps([dict(name="one", x3d="one.x3d"), dict(name="two", x3d="two.x3d")]))
        self.out = self.root / "out"
        self.fakes = {}
        self._load = legs_pkg.load
        legs_pkg.load = lambda leg: self.fakes[leg]

    def tearDown(self):
        legs_pkg.load = self._load
        self.tmp.cleanup()

    def go(self, *extra, legs="blender_cycles,xite,babylon_addon_glb,castle_native"):
        args = run_mod.parse_args(["--scenes", str(self.scenes), "--out", str(self.out), "--base", str(self.root), "--legs", legs,
                                   "--no-report", "--quiet", "--addon", str(self.root)] + list(extra))
        code = run_mod.run(args)
        with open(self.out / "results.json") as f:
            return code, json.load(f)

    def make(self, **kw):
        self.fakes = {"blender_cycles": FakeLeg("blender_cycles", 100), "xite": FakeLeg("xite", 110),
                      "babylon_addon_glb": FakeLeg("babylon_addon_glb", 105, **kw.get("babylon", {})),
                      "castle_native": FakeLeg("castle_native", 90, unavailable="CASTLE_RENDER is not set")}

    def rec(self, doc, scene, leg):
        return next(s for s in doc["scenes"] if s["name"] == scene)["legs"][leg]

    def test_first_run_records_every_leg_and_scores(self):
        self.make(babylon=dict(fail=["two"]))
        code, doc = self.go()
        self.assertEqual(code, 0)
        self.assertEqual(schema.check_results(doc), [])
        self.assertEqual(self.rec(doc, "one", "xite")["status"], "ok")
        self.assertEqual(self.rec(doc, "two", "babylon_addon_glb")["status"], "failed")
        self.assertIn("fake failure", self.rec(doc, "two", "babylon_addon_glb")["reason"])
        for leg, why in (("castle_native", "CASTLE_RENDER is not set"), ("blender_eevee", "not selected"), ("babylon_castle_glb", "not selected")):
            r = self.rec(doc, "one", leg)
            self.assertEqual(r["status"], "not-run")
            self.assertIn(why, r["reason"])
        m = self.rec(doc, "one", "xite")["metrics"]
        self.assertGreater(m["flip_vs_reference"]["mean"], 0)
        self.assertNotIn("flip_vs_xite", m)
        self.assertGreater(self.rec(doc, "one", "babylon_addon_glb")["metrics"]["mean_abs_vs_xite"]["mean_abs"], 0)
        ref = self.rec(doc, "one", "blender_cycles")["metrics"]
        self.assertNotIn("flip_vs_reference", ref)
        self.assertTrue((self.out / "scenes/one/xite.png").exists())
        self.assertTrue((self.out / "scenes/one/flip_xite.png").exists())

    def test_strict_exit_code(self):
        self.make(babylon=dict(fail=["two"]))
        self.assertEqual(self.go("--strict")[0], 1)

    def test_resume_reuses_ok_and_retries_failed(self):
        self.make(babylon=dict(fail=["two"]))
        self.go()
        first = {k: list(v.calls) for k, v in self.fakes.items()}
        self.assertEqual(first["blender_cycles"], ["one", "two"])
        self.make()                                  # new fakes, babylon no longer fails
        _, doc = self.go("--resume")
        self.assertEqual(self.fakes["blender_cycles"].calls, [])
        self.assertEqual(self.fakes["xite"].calls, [])
        self.assertEqual(self.fakes["babylon_addon_glb"].calls, ["two"])
        self.assertEqual(self.rec(doc, "two", "babylon_addon_glb")["status"], "ok")
        self.assertTrue(doc["params"]["resumed"])

    def test_without_resume_everything_runs_again(self):
        self.make()
        self.go()
        self.make()
        self.go()
        self.assertEqual(self.fakes["xite"].calls, ["one", "two"])

    def test_changed_scene_bytes_rerun_only_that_scene(self):
        self.make()
        self.go()
        (self.root / "two.x3d").write_text(X3D.replace("0 0 6", "0 0 7"))
        self.make()
        self.go("--resume")
        self.assertEqual(self.fakes["xite"].calls, ["two"])
        self.assertEqual(self.fakes["blender_cycles"].calls, ["two"])

    def test_changed_settings_rerun_that_leg_only(self):
        self.make()
        self.go()
        self.make()
        self.go("--resume", "--spp", "64")
        self.assertEqual(self.fakes["blender_cycles"].calls, ["one", "two"])
        self.assertEqual(self.fakes["xite"].calls, [])

    def test_missing_image_invalidates_a_record(self):
        self.make()
        self.go()
        (self.out / "scenes/one/xite.png").unlink()
        self.make()
        self.go("--resume")
        self.assertEqual(self.fakes["xite"].calls, ["one"])

    def test_unavailable_leg_is_retried_when_it_becomes_available(self):
        self.make()
        self.go()
        self.make()
        self.fakes["castle_native"] = FakeLeg("castle_native", 90)
        _, doc = self.go("--resume")
        self.assertEqual(self.fakes["castle_native"].calls, ["one", "two"])
        self.assertEqual(self.rec(doc, "one", "castle_native")["status"], "ok")

    def test_not_selected_legs_keep_earlier_results(self):
        self.make()
        self.go()
        self.make()
        _, doc = self.go("--resume", legs="xite")
        self.assertEqual(self.rec(doc, "one", "blender_cycles")["status"], "ok")
        self.assertEqual(self.rec(doc, "one", "babylon_addon_glb")["status"], "ok")

    def test_only_filter(self):
        self.make()
        _, doc = self.go("--only", "two")
        self.assertEqual([s["name"] for s in doc["scenes"]], ["two"])


class PureResumeTests(unittest.TestCase):
    def rec(self, **kw):
        r = schema.new_leg_record("xite", schema.OK)
        r.update(image="a.png", scene_sha256="h", config_key=dict(size=512))
        r.update(kw)
        return r

    def test_reusable_rules(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.png").write_bytes(b"x")
            ok = run_mod.reusable
            self.assertTrue(ok(self.rec(), "h", dict(size=512), td))
            self.assertFalse(ok(self.rec(), "other", dict(size=512), td))
            self.assertFalse(ok(self.rec(), "h", dict(size=256), td))
            self.assertFalse(ok(self.rec(image="gone.png"), "h", dict(size=512), td))
            self.assertFalse(ok(self.rec(status=schema.FAILED), "h", dict(size=512), td))
            self.assertFalse(ok(self.rec(status=schema.NOT_RUN), "h", dict(size=512), td))
            self.assertTrue(ok(self.rec(status=schema.NOT_APPLICABLE, image=None), "h", dict(size=512), td))
            self.assertFalse(ok(None, "h", dict(size=512), td))

    def test_parse_legs(self):
        self.assertEqual(run_mod.parse_legs("all"), list(legs_pkg.ORDER))
        self.assertEqual(run_mod.parse_legs("xite,blender_cycles"), ["blender_cycles", "xite"])   # the reference always runs first
        with self.assertRaises(ValueError):
            run_mod.parse_legs("xite,nope")

    def test_blank_record_has_every_leg_not_run(self):
        class S:
            name, rel, x3d, sha256, view, view_error, clear, headlight_on = "s", "s.x3d", "/x/s.x3d", "h", None, None, [0, 0, 0], True
            wellformed, has_geometry = dict(verdict="pass"), True

            def record_header(self, base):
                return dict(name=self.name, x3d=dict(path=self.rel, sha256=self.sha256))
        r = run_mod.blank_scene_record(S(), "/x")
        self.assertEqual(set(r["legs"]), set(schema.LEG_IDS))
        self.assertTrue(all(l["status"] == schema.NOT_RUN and l["reason"] for l in r["legs"].values()))

    def test_metrics_signature_tracks_image_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a", Path(td) / "b"
            a.write_bytes(b"1")
            b.write_bytes(b"2")
            s1 = run_mod.metrics_sig(str(a), str(b), None)
            b.write_bytes(b"3")
            self.assertNotEqual(s1, run_mod.metrics_sig(str(a), str(b), None))


if __name__ == "__main__":
    unittest.main()
