# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""tools/behaviour_pair_judge.py: the pure parts on synthetic series, and (when Node, Playwright, Chromium and an X_ITE
dist are on the machine) two files against X_ITE."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import behaviour_pair_judge as pj   # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"
X_ITE_CANDIDATES = [os.environ.get("X_ITE_DIST"),
                    "/tmp/claude-0/-home-user/465e5b3a-c939-56aa-82dc-e0268d1c3b26/scratchpad/xite1681/package/dist",
                    "/home/user/x3d.demo/docs/demos/blenderizer-nexus/v1/observatory/vendor/x_ite"]


def ramp(offset=0.0, bad=0.0, n=100):
    return [(i / n + offset + (bad if i % 2 else 0.0),) for i in range(n)]


class PureTests(unittest.TestCase):

    def stream(self, a, b, **kw):
        return pj.judge_streams(a, b, **kw)

    def test_identical_runs_are_the_same(self):
        r = self.stream([ramp()] * 3, [ramp()] * 3)
        self.assertEqual((r["verdict"], r["floor"]), ("same", 0.0))

    def test_an_offset_above_the_floor_in_every_pairing_differs(self):
        r = self.stream([ramp()] * 3, [ramp(0.2)] * 3)
        self.assertEqual(r["verdict"], "differs")
        self.assertEqual(len(r["a_vs_b"]["fraction"]), 9)
        self.assertTrue(all(f > r["threshold"] for f in r["a_vs_b"]["fraction"]))

    def test_an_offset_inside_a_noisy_floor_is_unclear(self):
        noisy = [ramp(bad=0.5), ramp(), ramp(bad=0.5, n=100)]          # runs that disagree with each other on half the samples
        r = self.stream(noisy, [ramp(0.2, bad=0.5), ramp(0.2), ramp(0.2, bad=0.5)])
        self.assertGreater(r["floor"], 0.3)
        self.assertEqual(r["verdict"], "unclear")

    def test_one_bad_repeat_does_not_flip_equal_files_to_differs(self):
        r = self.stream([ramp(), ramp(), ramp(0.3)], [ramp()] * 3)
        self.assertEqual(r["verdict"], "same")
        self.assertGreater(r["floor"], 0.9)

    def test_one_bad_repeat_does_not_hide_a_real_difference(self):
        r = self.stream([ramp(0.2), ramp(0.2), ramp(0.9)], [ramp()] * 3)
        self.assertEqual(r["verdict"], "differs")

    def test_the_margin_is_three_times_the_floor_and_at_least_one_percent(self):
        self.assertEqual(pj.verdict_of([0.30] * 4, [0.10]), ("unclear", 0.30000000000000004))
        self.assertEqual(pj.verdict_of([0.31] * 4, [0.10])[0], "differs")
        self.assertEqual(pj.verdict_of([0.011] * 4, [0.0])[0], "differs")
        self.assertEqual(pj.verdict_of([0.01] * 4, [0.0])[0], "unclear")

    def test_overall(self):
        self.assertEqual(pj.overall(["same", "same"]), "same")
        self.assertEqual(pj.overall(["same", "unclear"]), "unclear")
        self.assertEqual(pj.overall(["unclear", "differs", "same"]), "differs")

    def test_values_are_read_as_x_ite_writes_them(self):
        self.assertEqual(pj.flat("0 1.5 -2"), (0.0, 1.5, -2.0))
        self.assertEqual(pj.flat("[\n 0 0 0,\n 1 2 3\n]"), (0.0, 0.0, 0.0, 1.0, 2.0, 3.0))
        self.assertEqual(pj.flat(True), (1.0,))
        self.assertEqual(pj.flat("false"), (0.0,))
        self.assertEqual(pj.flat("hello"), ("s", "hello"))

    def test_sampling_holds_the_last_value_and_starts_from_the_initial(self):
        out = pj.sample("0", [(1.0, "5"), (2.0, "7")], [0.0, 0.5, 1.0, 1.5, 2.5])
        self.assertEqual(out, [(0.0,), (0.0,), (5.0,), (5.0,), (7.0,)])
        self.assertEqual(pj.sample(None, [], [0.0]), [None])

    def test_a_missing_value_or_a_length_change_counts_as_outside(self):
        self.assertEqual(pj.compare([None, (1.0,)], [(0.0,), (1.0, 2.0)], 0.1)[0], 1.0)

    def test_stimulus_none_and_seconds_are_a_timer_only_run(self):
        self.assertEqual(pj.normalise_stimulus(None), {"seconds": 4.0})
        self.assertEqual(pj.normalise_stimulus({"seconds": 2}), {"seconds": 2.0})

    def test_recorded_stimulus_maps_clicks_and_holds(self):
        out = pj.normalise_stimulus([{"time": 0, "call": "start"}, {"time": 1.0, "call": "click", "node": "Click", "args": []},
                                     {"time": 3.0, "call": "press", "node": "Click"},
                                     {"time": 7.5, "call": "release", "node": "Click"}])
        self.assertEqual((out["clicks"], out["hold"]), (2, [140, 4500]))
        self.assertEqual(out["only_sensor"], "Click")

    def test_calls_that_cannot_be_replayed_are_errors_not_skipped(self):
        for call in ("hover", "drag", "send", "post", "step", "key"):
            with self.assertRaises(pj.PairJudgeError, msg=call):
                pj.normalise_stimulus([{"time": 1, "call": call, "node": "N"}])
        with self.assertRaises(pj.PairJudgeError):
            pj.normalise_stimulus([{"time": 1, "call": "press", "node": "N"}])        # never released
        with self.assertRaises(pj.PairJudgeError):
            pj.normalise_stimulus([{"time": 1, "call": "click", "node": "A"}, {"time": 2, "call": "click", "node": "B"}])

    def test_watched_streams_are_the_scene_fields_routes_end_at(self):
        import behaviour_graph as bg
        graph = bg.Behaviour.from_x3d((WORLDS / "door.x3d").read_text(encoding="utf-8"))
        self.assertEqual(list(pj.watched(graph)), [("Door", "translation")])

    def test_import_starts_nothing_and_the_cli_reports_a_tool_error_as_exit_3(self):
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "behaviour_pair_judge.py"), "nope-a.x3d", "nope-b.x3d",
                               "--x-ite", "/nonexistent"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 3)
        self.assertEqual(json.loads(done.stdout)["verdict"], "error")


def _x_ite():
    for path in X_ITE_CANDIDATES:
        if path and (pathlib.Path(path) / "x_ite.min.js").is_file():
            return path
    return None


def _browser_missing():
    if not _x_ite():
        return "no X_ITE dist directory (set X_ITE_DIST)"
    if shutil.which("node") is None:
        return "node is not installed"
    if pj.browser_version() is None:
        return "Playwright or its Chromium is not available to node"
    return None


@unittest.skipIf(_browser_missing(), _browser_missing() or "")
class BrowserTests(unittest.TestCase):
    """Real runs in X_ITE (headless Chromium): minutes, and sensitive to machine load, which is why the verdict carries its
    own noise floor."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_door_against_itself_is_the_same(self):
        r = pj.judge_pair(WORLDS / "door.x3d", WORLDS / "door.x3d", {"clicks": 1, "seconds": 4}, repeats=3, x_ite=_x_ite())
        print("\ndoor vs door:", r["verdict"], "load", r["load"]["max_1min"],
              [(s["stream"], s["a_vs_b"]["fraction"], s["floor"]) for s in r["streams"]])
        self.assertEqual(r["verdict"], "same")
        self.assertTrue(all(n > 0 for s in r["streams"] for n in s["events"]["a"]))

    def test_door_against_a_changed_keyvalue_differs(self):
        text = (WORLDS / "door.x3d").read_text(encoding="utf-8")
        changed = text.replace('keyValue="0 1.2 0 0 3.7 0 0 3.7 0 0 1.2 0"', 'keyValue="0 1.2 0 0 2.2 0 0 2.2 0 0 1.2 0"')
        self.assertNotEqual(text, changed)
        copy = pathlib.Path(self.tmp.name) / "door-changed.x3d"
        copy.write_text(changed, encoding="utf-8")
        r = pj.judge_pair(WORLDS / "door.x3d", copy, {"clicks": 1, "seconds": 4}, repeats=3, x_ite=_x_ite())
        print("\ndoor vs changed:", r["verdict"], "load", r["load"]["max_1min"],
              [(s["stream"], s["a_vs_b"]["fraction"], s["floor"]) for s in r["streams"]])
        self.assertEqual(r["verdict"], "differs")

    def test_a_timer_only_world_needs_no_stimulus(self):
        r = pj.judge_pair(WORLDS / "timer-only.x3d", WORLDS / "timer-only.x3d", None, repeats=3, x_ite=_x_ite())
        print("\ntimer-only vs itself:", r["verdict"], "load", r["load"]["max_1min"], r["time_zero"]["a"],
              [(s["stream"], s["a_vs_b"]["fraction"], s["floor"]) for s in r["streams"]])
        self.assertEqual(r["verdict"], "same")
        self.assertEqual({z["from"] for n in r["time_zero"].values() for z in n}, {"first cycle start"})


if __name__ == "__main__":
    unittest.main()
