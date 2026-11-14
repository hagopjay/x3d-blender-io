# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The render side of the export gate (tools/fidelity_rig/gate.py and render.mjs) without a browser or Blender: the image
measurements on synthetic renders (what the gate measures, what makes a render vacuous, what Babylon.js failed to draw), the
render retry (run_renders with a stand-in for the render.mjs process) and the failure exit of render.mjs. numpy and Pillow are
needed for the image tests; they are skipped where the unit job does not install them.

    cd tests && python -m unittest test_gate_render
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RIG = ROOT / "tools" / "fidelity_rig"
sys.path.insert(0, str(RIG))
import gate  # noqa: E402

try:
    import numpy as np
    from PIL import Image
    HAVE_IMAGES = True
except ImportError:   # the unit job installs neither
    HAVE_IMAGES = False

N = 32   # synthetic renders are N x N


def png(path, arr):
    Image.fromarray(np.asarray(arr, dtype=np.uint8)).save(path)


def frame(bg=(10, 20, 30), box=None, colour=(200, 50, 50)):
    a = np.zeros((N, N, 3), dtype=np.uint8)
    a[:] = bg
    if box:
        y0, y1, x0, x1 = box
        a[y0:y1, x0:x1] = colour
    return a


def mask_pair(box=None):
    """Babylon.js's two mask renders: cleared to magenta, then to green; a pixel is background only when it shows the clear."""
    mk = frame((255, 0, 255), box, (90, 90, 90))
    mg = frame((0, 255, 0), box, (90, 90, 90))
    return mk, mg


@unittest.skipUnless(HAVE_IMAGES, "numpy and Pillow are not installed")
class ImageMeasurements(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.out = Path(self.td.name)
        (self.out / "reexp").mkdir()

    def tearDown(self):
        self.td.cleanup()

    def scene(self, xite, babylon, babylon_box, reexp=None):
        png(self.out / "xite.png", xite)
        png(self.out / "babylon.png", babylon)
        mk, mg = mask_pair(babylon_box)
        png(self.out / "babylon_mask.png", mk)
        png(self.out / "babylon_mask_green.png", mg)
        if reexp is not None:
            png(self.out / "reexp" / "xite.png", reexp)
        m = dict(glb_leg=dict(ok=True), reexport=dict(leg_ok=reexp is not None))
        return gate.finish_scene(m, str(self.out))

    def test_foreground_mask_is_what_differs_from_the_border(self):
        a = frame(box=(8, 16, 8, 16))
        self.assertEqual(int(gate.foreground_mask(a).sum()), 64)
        self.assertEqual(gate.foreground_share(frame()), 0.0)
        faint = frame(box=(8, 16, 8, 16), colour=(20, 20, 30))   # 10 off the background: a pixel, but not foreground at 16
        self.assertEqual(int(gate.foreground_mask(faint).sum()), 64)
        self.assertEqual(int(gate.foreground_mask(faint, gate.FOREGROUND_DELTA).sum()), 0)

    def test_blank_reference_is_recorded_as_zero_share(self):   # F2
        m = self.scene(frame(), frame(), None, reexp=frame())
        self.assertEqual(m["xite_foreground_share"], 0.0)
        self.assertIsNone(m["geometry_delta"])
        self.assertEqual(m["geometry_share"], 0.0)
        self.assertEqual(m["geometry_missing_share"], 0.0)
        self.assertEqual((m["roundtrip"]["mean_abs_delta"], m["roundtrip"]["flip"] or 0.0), (0.0, 0.0))
        # ... and the gate calls both render checks vacuous
        vac = gate.vacuous_renders(dict(m, glb={"class": "points", "triangles": 0}))
        self.assertEqual(set(vac), {"geometry_delta", "roundtrip_delta"})
        res = {r["check"]: r for r in gate.evaluate_scene(
            dict(m, glb={"class": "points", "triangles": 0, "points": 1, "lines": 0}, validator=dict(ok_ran=True, errors=0, warnings=0),
                 x3d=dict(surface=False, lines=False, points=True, splats=True), reexport=dict(m["reexport"], well_formed=True, x3d_py="ok",
                                                                                              x3d_py_errors=0, nodes_lost=0)),
            dict(validator=dict(warnings=0), glb={"class": "points", "triangles": 0, "points": 1, "lines": 0}, geometry_delta=None,
                 reexport=dict(nodes_lost=0), roundtrip=dict(mean_abs_delta=0.0, flip=0.0)), gate.DEFAULT_TOLERANCE)}
        self.assertEqual(res["geometry_delta"]["status"], "FAIL")
        self.assertEqual(res["roundtrip_delta"]["status"], "FAIL")

    def test_one_pixel_of_foreground_is_not_blank(self):
        one = frame()
        one[3, 3] = (255, 255, 255)
        m = self.scene(one, one, None, reexp=one)
        self.assertGreater(m["xite_foreground_share"], 0.0)   # 1 / 1024 px, kept at 6 decimals

    def test_what_babylon_did_not_draw_is_measured_although_the_delta_cannot_see_it(self):   # F3
        xite = frame(box=(4, 28, 4, 28))                                # X_ITE draws a big object
        full = frame(box=(4, 28, 4, 28), colour=(200, 50, 50))          # Babylon.js draws all of it
        half = frame(box=(4, 28, 4, 16), colour=(200, 50, 50))          # ... or only its left half
        a = self.scene(xite, full, (4, 28, 4, 28))
        b = self.scene(xite, half, (4, 28, 4, 16))
        self.assertEqual(a["geometry_delta"], 0.0)
        self.assertEqual(b["geometry_delta"], 0.0)                      # the delta over the pixels Babylon.js drew is the same
        self.assertEqual(a["geometry_missing_share"], 0.0)
        self.assertAlmostEqual(b["geometry_missing_share"], 24 * 12 / (N * N), places=3)   # but X_ITE shows 12 columns it left empty
        self.assertLess(b["geometry_share"], a["geometry_share"])
        # the gate fails the half-drawn glb against the baseline of the full one
        base = dict(validator=dict(warnings=0), glb={"class": "triangles", "triangles": 100, "points": 0, "lines": 0}, geometry_delta=0.0,
                    geometry_share=a["geometry_share"], geometry_missing_share=a["geometry_missing_share"],
                    reexport=dict(nodes_lost=0), roundtrip=dict(mean_abs_delta=0.0, flip=0.0))

        def verdict(m):
            m = dict(m, glb={"class": "triangles", "triangles": 100, "points": 0, "lines": 0}, validator=dict(ok_ran=True, errors=0, warnings=0),
                     x3d=dict(surface=True, lines=False, points=False, splats=False),
                     reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=0, nodes_lost=0), roundtrip=dict(render_ok=True, mean_abs_delta=0.0, flip=0.0))
            return {r["check"]: r for r in gate.evaluate_scene(m, base, gate.DEFAULT_TOLERANCE)}["geometry_delta"]
        self.assertEqual(verdict(a)["status"], "PASS")
        self.assertEqual(verdict(b)["status"], "FAIL")

    def test_flip_failure_is_recorded_and_the_gate_notices(self):   # F5
        import roundtrip_audit as ra
        xite = frame(box=(4, 28, 4, 28))
        with mock.patch.object(ra, "flip_mean", side_effect=RuntimeError("flip exploded")):
            m = self.scene(xite, xite, (4, 28, 4, 28), reexp=xite)
        self.assertIsNone(m["roundtrip"]["flip"])
        self.assertIn("flip exploded", m["roundtrip"]["flip_error"])
        self.assertTrue(m["roundtrip"]["render_ok"])
        full = dict(m, glb={"class": "triangles", "triangles": 100, "points": 0, "lines": 0}, validator=dict(ok_ran=True, errors=0, warnings=0),
                    x3d=dict(surface=True, lines=False, points=False, splats=False),
                    reexport=dict(leg_ok=True, well_formed=True, x3d_py="ok", x3d_py_errors=0, nodes_lost=0))
        entry = dict(validator=dict(warnings=0), glb={"class": "triangles", "triangles": 100}, geometry_delta=0.0,
                     reexport=dict(nodes_lost=0), roundtrip=dict(mean_abs_delta=0.0, flip=0.04))
        res = {r["check"]: r for r in gate.evaluate_scene(full, entry, gate.DEFAULT_TOLERANCE)}
        self.assertEqual(res["roundtrip_delta"]["status"], "FAIL")
        self.assertIn("flip exploded", res["roundtrip_delta"]["detail"])

    def test_a_missing_render_leaves_no_share(self):
        m = gate.finish_scene(dict(glb_leg=dict(ok=True), reexport=dict(leg_ok=False)), str(self.out))
        self.assertFalse(m["glb_render_ok"])
        self.assertNotIn("xite_foreground_share", m)
        self.assertFalse(m["roundtrip"]["render_ok"])


class FakeRender:
    """Stands in for `node render.mjs jobs.json --strict`: records every call, answers from a script of (returncode, stdout)."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, cmd, **kw):
        jobs = json.loads(Path(cmd[2]).read_text())
        self.calls.append(dict(names=[j["name"] for j in jobs], strict="--strict" in cmd, timeout=kw.get("timeout")))
        item = self.script.pop(0) if self.script else (0, "")
        if isinstance(item, Exception):
            raise item
        code, out = item
        return subprocess.CompletedProcess(cmd, code, stdout="BROWSER Chrome/153.0.1.2\n" + out, stderr="")


class RenderRetry(unittest.TestCase):
    """F7: a job that fails inside render.mjs's own try/catch (the process exits normally) is rerun; a hang is bounded."""

    def setUp(self):
        self.label = "gate-render-test-" + str(os.getpid())
        os.makedirs(RIG / "out" / self.label, exist_ok=True)
        self.jobs = [dict(name=n) for n in "abcd"]

    def tearDown(self):
        import shutil
        shutil.rmtree(RIG / "out" / self.label, ignore_errors=True)

    def run_with(self, script, chunk=8):
        fake = FakeRender(script)
        with mock.patch.object(gate.subprocess, "run", fake), mock.patch.object(gate, "log", lambda *a: None):
            chromium = gate.run_renders(self.jobs, self.label, chunk)
        return fake, chromium

    def test_all_rendered_is_one_process(self):
        fake, chromium = self.run_with([(0, "")])
        self.assertEqual([c["names"] for c in fake.calls], [["a", "b", "c", "d"]])
        self.assertTrue(fake.calls[0]["strict"])
        self.assertEqual(chromium, "153.0.1.2")

    def test_only_the_jobs_that_failed_are_rerun_each_alone(self):
        fake, _ = self.run_with([(1, 'xite fail b load timeout\nFAILED ["b", "d"]\n'), (0, ""), (0, "")])
        self.assertEqual([c["names"] for c in fake.calls], [["a", "b", "c", "d"], ["b"], ["d"]])

    def test_a_rerun_that_fails_again_is_not_retried_forever(self):
        fake, _ = self.run_with([(1, 'FAILED ["b"]\n'), (1, 'FAILED ["b"]\n')])
        self.assertEqual([c["names"] for c in fake.calls], [["a", "b", "c", "d"], ["b"]])

    def test_a_process_that_died_without_the_failed_line_reruns_every_job(self):
        fake, _ = self.run_with([(1, ""), (0, ""), (0, ""), (0, ""), (0, "")])
        self.assertEqual([c["names"] for c in fake.calls], [["a", "b", "c", "d"], ["a"], ["b"], ["c"], ["d"]])

    def test_a_timeout_reruns_the_jobs_and_every_process_is_bounded(self):
        fake, _ = self.run_with([subprocess.TimeoutExpired("node", 1), (0, ""), (0, ""), (0, ""), (0, "")])
        self.assertEqual(len(fake.calls), 5)
        self.assertEqual(fake.calls[0]["timeout"], 60 + gate.RENDER_JOB_BUDGET_S * 4)
        self.assertEqual(fake.calls[1]["timeout"], 60 + gate.RENDER_JOB_BUDGET_S)

    def test_chunks_are_independent(self):
        fake, _ = self.run_with([(0, ""), (1, 'FAILED ["d"]\n'), (0, "")], chunk=2)
        self.assertEqual([c["names"] for c in fake.calls], [["a", "b"], ["c", "d"], ["d"]])

    def test_a_default_chunk_fits_inside_the_ci_job_limit(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        job = ci[ci.index("  fidelity-gate:"):]
        minutes = int(re.search(r"timeout-minutes:\s*(\d+)", job).group(1))
        self.assertLess(60 + gate.RENDER_JOB_BUDGET_S * 8, minutes * 60)   # one hung chunk of the default size cannot exceed the job
        self.assertLess(60 + gate.RENDER_JOB_BUDGET_S * 8, 3600)           # the old fixed 3,600 s per process is gone


class RenderMjsExit(unittest.TestCase):
    """render.mjs itself needs a browser, so the failure exit is pinned in its source (and was run once by hand, see the commit)."""

    def setUp(self):
        self.src = (RIG / "render.mjs").read_text()

    def test_strict_mode_reports_failed_jobs_and_exits_nonzero(self):
        self.assertIn("process.argv.includes('--strict')", self.src)
        self.assertEqual(len(re.findall(r"failedJobs\.add\(job\.name\)", self.src)), 2)   # X_ITE catch and Babylon.js catch
        self.assertRegex(self.src, r"if \(strict && failedJobs\.size\)[^\n]*FAILED[^\n]*process\.exitCode = 1")
        self.assertLess(self.src.index("await browser.close()"), self.src.index("process.exitCode = 1"))   # the browser still closes

    def test_loads_are_bounded_and_the_scorecard_contract_is_intact(self):
        self.assertIn("LOAD_TIMEOUT_MS", self.src)
        self.assertEqual(len(re.findall(r"new Error\('load timeout'\)", self.src)), 2)   # X_ITE loadURL and Babylon.js AppendAsync
        for needle in ("console.log('TIME xite'", "console.log('TIME babylon'", "job.legs", "xiteOnly"):
            self.assertIn(needle, self.src)
        # without --strict a failed job still exits 0: compare.py, roundtrip.py and the scorecard read the images that exist
        self.assertNotIn("process.exit(1)", self.src)

    def test_the_gate_asks_for_strict(self):
        self.assertIn('"--strict"', (RIG / "gate.py").read_text())


if __name__ == "__main__":
    unittest.main()
