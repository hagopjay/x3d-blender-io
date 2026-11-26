# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""tools/behaviour_pair_judge.py: the pure parts on synthetic series, and (when Node, Playwright, Chromium and an X_ITE
dist are on the machine) two files against X_ITE."""

from __future__ import annotations

import json
import math
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


NODE_WORLD = """<X3D profile="Immersive" version="4.0"><Scene>
<Group DEF="Src"/><Group DEF="Dst"/><Transform DEF="T"><Shape><Box/></Shape></Transform>
<TimeSensor DEF="C" cycleInterval="2" loop="true"/><PositionInterpolator DEF="P" key="0 1" keyValue="0 0 0 1 1 1"/>
<ROUTE fromNode="Src" fromField="children_changed" toNode="Dst" toField="addChildren"/>
<ROUTE fromNode="C" fromField="fraction_changed" toNode="P" toField="set_fraction"/>
<ROUTE fromNode="P" fromField="value_changed" toNode="T" toField="translation"/>
</Scene></X3D>"""


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

    def test_a_blind_floor_never_gives_same(self):
        # runs that disagree with themselves on every sample, the same way for A and for B: whatever A against B reads
        shifted = [ramp(), ramp(0.3), ramp(0.6)]
        for other in (shifted, [ramp(0.9), ramp(0.1), ramp(0.4)], shifted[:]):
            r = self.stream(shifted, other)
            self.assertGreaterEqual(r["floor_typical"], 0.5)
            self.assertEqual((r["verdict"], r["reason"]), ("unclear", "blind"))
        # a blind judge also refuses "differs": the planted offset below cannot be told from the noise
        r = self.stream([ramp(), ramp(0.3), ramp(0.6)], [ramp(5.0), ramp(5.3), ramp(5.6)])
        self.assertEqual((r["verdict"], r["reason"]), ("unclear", "blind"))
        self.assertIn("0.5", r["detail"])

    def test_the_blind_limit_is_a_median_floor_of_half_the_samples(self):
        half = [ramp(), ramp(bad=0.5)]            # odd samples 0.5 apart: exactly half outside
        self.assertEqual(self.stream(half, half)["reason"], "blind")
        self.assertEqual(self.stream(half, half, blind=0.51)["reason"], None)
        self.assertEqual(self.stream([ramp()] * 3, [ramp()] * 3)["reason"], None)

    def test_overall_reason_is_blind_when_any_stream_is(self):
        blind = {"verdict": "unclear", "reason": "blind"}
        self.assertEqual(pj.overall_reason([{"verdict": "same", "reason": None}, blind]), "blind")
        self.assertIsNone(pj.overall_reason([{"verdict": "same", "reason": None}]))
        self.assertIsNone(pj.overall_reason([{"verdict": "differs", "reason": None}, blind]))
        self.assertEqual(pj.EXIT["unclear"], 2)

    def test_one_rotation_spelled_two_ways_is_the_same_rotation(self):
        self.assertAlmostEqual(pj.rotation_distance((0, 1, 0, 6.17), (0, -1, 0, 0.11)), 0.003185, places=5)
        self.assertAlmostEqual(pj.rotation_distance((0, 1, 0, 0.5), (0, -1, 0, -0.5)), 0.0, places=6)
        self.assertAlmostEqual(pj.rotation_distance((0, 0, 0, 1.0), (0, 1, 0, 0.0)), 0.0, places=6)
        self.assertAlmostEqual(pj.rotation_distance((0, 1, 0, 0.0), (0, 1, 0, 0.5)), 0.5, places=9)
        import behaviour_sim as bs
        for a, b in (((0, 1, 0, 6.17), (0, -1, 0, 0.11)), ((1, 0, 0, 1.0), (0, 0, 1, 2.0)), ((0, 1, 0, 3.0), (0, 1, 0, -3.0))):
            self.assertAlmostEqual(pj.rotation_distance(a, b), bs._rotation_distance(a, b), places=12)

    def test_rotation_streams_are_compared_as_rotations(self):
        n = 60
        turn = [pj.flat(f"0 1 0 {0.1 * (i % 20) + 6.0}") for i in range(n)]
        again = [pj.flat(f"0 -1 0 {2 * math.pi - 0.1 * (i % 20) - 6.0}") for i in range(n)]   # the same rotations, spelled the other way
        raw = self.stream([turn] * 3, [again] * 3)
        self.assertEqual(raw["verdict"], "differs")                       # as raw numbers they are 12 apart
        rot = self.stream([turn] * 3, [again] * 3, rotation=True)
        self.assertEqual((rot["verdict"], rot["tolerance_unit"]), ("same", "rad"))
        self.assertLess(max(rot["a_vs_b"]["max_abs"]), 1e-6)
        moved = [pj.flat(f"0 1 0 {0.1 * (i % 20) + 6.5}") for i in range(n)]
        self.assertEqual(self.stream([turn] * 3, [moved] * 3, rotation=True)["verdict"], "differs")

    def test_a_rotation_span_is_the_widest_angle_swept(self):
        run = [pj.flat("0 1 0 0"), pj.flat("0 1 0 1.0"), pj.flat("0 1 0 2.5")]
        self.assertAlmostEqual(pj.span_of([run], rotation=True), 2.5, places=9)

    def test_node_values_are_recognised_by_their_text_and_by_the_catalogue(self):
        for text in ("Shape { }", "[ Box { }, Sphere { } ]", "NULL", "[\nTransform {\n}\n]"):
            self.assertTrue(pj.looks_like_node(text), text)
        for text in ("0 1 0 3.14", "true", "hello world", ""):
            self.assertFalse(pj.looks_like_node(text), text)
        import behaviour_graph as bg
        graph = bg.Behaviour.from_x3d(NODE_WORLD)
        self.assertEqual(pj.field_types(graph), {("Dst", "addChildren"): "MFNode", ("T", "translation"): "SFVec3f"})
        self.assertEqual(pj.field_types(graph)[("T", "translation")], "SFVec3f")

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

    # -- what a 42-pair run on real scenes asked for ---------------------------------------------------------------------

    def test_no_events_in_any_run_is_nothing_moved_and_one_silent_side_is_not(self):
        self.assertEqual(pj.activity([0, 0, 0], [0, 0, 0]), "nothing-moved")
        self.assertEqual(pj.activity([0, 0, 0], [5, 4, 6]), "one-side-silent")
        self.assertEqual(pj.activity([5, 4, 6], [0, 0, 0]), "one-side-silent")
        self.assertIsNone(pj.activity([0, 3, 3], [5, 4, 6]))          # silent in only some pairings: left to the floor
        self.assertIsNone(pj.activity([5, 5], [5, 5]))

    def test_overall_reason_is_nothing_moved_only_when_every_stream_is(self):
        still = {"verdict": "unclear", "reason": "nothing-moved"}
        self.assertEqual(pj.overall_reason([still, dict(still)]), "nothing-moved")
        self.assertEqual(pj.overall_reason([still, {"verdict": "unclear", "reason": "blind"}]), "blind")
        self.assertEqual(pj.overall([still["verdict"]]), "unclear")

    def test_a_recording_that_drew_nothing_still_has_a_window_from_its_start_and_wait(self):
        trace = {"began": 100.0, "frames": [100.0] * 150}            # X_ITE's clock never moved: every stamp is the start
        self.assertEqual(pj._stop(trace, 6.0), 106.0)
        self.assertEqual(pj._stop({"began": 100.0, "frames": [100.0, 107.5]}, 6.0), 107.5)
        self.assertEqual(pj._stop({"began": 100.0, "frames": []}, 6.0), 106.0)

    def test_a_practically_still_stream_carries_a_span_note_and_keeps_its_verdict(self):
        n = 60
        a = [pj.flat(f"0 1 0 {5e-6 * i / n}") for i in range(n)]
        b = [pj.flat(f"0 1 0 {5e-6 * i / n + 4e-6}") for i in range(n)]
        r = self.stream([a] * 3, [b] * 3, rotation=True)
        self.assertEqual(r["verdict"], "differs")                      # the rule is unchanged: the tolerance scales with the span
        self.assertLess(r["span"], pj.SPAN_LIMIT_ROTATION)
        self.assertEqual(pj.stream_notes(r["span"], True, 10, False, 30.0), ["span below 0.001 rad"])
        self.assertEqual(pj.stream_notes(5e-5, False, 10, False, 30.0), ["span below 0.0001 in the field unit"])
        self.assertEqual(pj.stream_notes(0.5, True, 10, False, 30.0), [])
        self.assertEqual(pj.stream_notes(0.0, False, 0, False, 30.0), [])    # never moved: that is "nothing-moved", not a span note

    def test_low_frame_rate_is_noted_only_for_a_blind_stream_under_the_limit(self):
        self.assertEqual(pj.MIN_FPS, 15.0)
        self.assertEqual(pj.stream_notes(2.0, False, 10, True, 9.0), ["low frame rate"])
        self.assertEqual(pj.stream_notes(2.0, False, 10, True, 15.0), [])
        self.assertEqual(pj.stream_notes(2.0, False, 10, False, 3.0), [])
        self.assertEqual(pj.stream_notes(2.0, False, 10, True, 3.0, min_fps=2.0), [])

    def test_the_drawn_frame_rate_counts_distinct_stamps_in_the_window(self):
        frames = [10.0] * 30 + [10.1, 10.1, 10.2, 10.3, 10.3, 10.4, 11.5]
        self.assertEqual(pj.frame_stats(frames, 10.0, 11.0), {"frames": 5, "seconds": 1.0, "fps": 5.0})
        self.assertEqual(pj.frame_stats(frames, 10.0, 10.0)["fps"], 0.0)


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
        r = pj.judge_pair(WORLDS / "timer-only.x3d", WORLDS / "timer-only.x3d", None, repeats=3, x_ite=_x_ite(), mode="sequential")
        print("\ntimer-only vs itself:", r["verdict"], "load", r["load"]["max_1min"], r["time_zero"]["a"],
              [(s["stream"], s["a_vs_b"]["fraction"], s["floor"]) for s in r["streams"]])
        self.assertEqual(r["verdict"], "same")
        self.assertEqual({z["from"] for n in r["time_zero"].values() for z in n}, {"first cycle start"})

    # -- free-running loops, several timers, rotations, node streams (simultaneous mode) ----------------------------------

    def table(self, r):
        return [(s["stream"], s["verdict"], s["reason"], s["a_vs_b"]["fraction"], s["floor_typical"], s["floor"]) for s in r["streams"]]

    def changed(self, name, old, new):
        text = (WORLDS / name).read_text(encoding="utf-8")
        self.assertIn(old, text)
        copy = pathlib.Path(self.tmp.name) / ("changed-" + name)
        copy.write_text(text.replace(old, new), encoding="utf-8")
        return copy

    def test_a_free_running_20_s_loop_watched_for_4_s_is_not_blind_when_run_together(self):
        world = WORLDS / "loop-20s.x3d"
        r = pj.judge_pair(world, world, {"seconds": 4}, repeats=3, x_ite=_x_ite())
        print("\n20 s loop vs itself, simultaneous:", r["verdict"], r["reason"], "load", r["load"]["max_1min"],
              "horizon", r["tolerance"]["horizon_s"], self.table(r))
        self.assertEqual(r["mode"], "simultaneous")
        self.assertEqual((r["verdict"], r["reason"]), ("same", None))
        self.assertTrue(all(s["floor_typical"] < 0.5 for s in r["streams"]))
        self.assertTrue(all({z["from"] for z in zs} == {"shared clock"} for zs in r["time_zero"].values()))

    def test_the_same_loop_against_a_changed_keyvalue_differs_when_run_together(self):
        world = WORLDS / "loop-20s.x3d"
        copy = self.changed("loop-20s.x3d", 'keyValue="-5 0 0 5 0 0 -5 0 0"', 'keyValue="-5 0 0 9 0 0 -5 0 0"')
        r = pj.judge_pair(world, copy, {"seconds": 4}, repeats=3, x_ite=_x_ite())
        print("\n20 s loop vs changed keyValue, simultaneous:", r["verdict"], r["reason"], "load", r["load"]["max_1min"], self.table(r))
        self.assertEqual(r["verdict"], "differs")

    def test_the_old_sequential_alignment_is_blind_on_the_same_loop_and_says_so(self):
        world = WORLDS / "loop-20s.x3d"
        r = pj.judge_pair(world, world, {"seconds": 4}, repeats=3, x_ite=_x_ite(), mode="sequential")
        print("\n20 s loop vs itself, sequential:", r["verdict"], r["reason"], "load", r["load"]["max_1min"], self.table(r),
              r["time_zero"]["a"])
        self.assertEqual(r["mode"], "sequential")
        for s in r["streams"]:
            if s["floor_typical"] >= 0.5:
                self.assertEqual((s["verdict"], s["reason"]), ("unclear", "blind"))
            self.assertNotEqual(s["verdict"], "differs")
        if r["verdict"] == "same":                    # only when the runs happened to fall in step: then the floor says so
            self.assertTrue(all(s["floor_typical"] < 0.5 for s in r["streams"]))

    def test_three_loops_of_3_5_and_7_s_against_themselves_are_the_same_on_every_stream(self):
        world = WORLDS / "loops-3-5-7.x3d"
        r = pj.judge_pair(world, world, {"seconds": 6}, repeats=3, x_ite=_x_ite())
        print("\n3, 5, 7 s loops vs themselves:", r["verdict"], "load", r["load"]["max_1min"], self.table(r))
        self.assertEqual(sorted(s["stream"] for s in r["streams"]), ["Grower7.scale", "Mover3.translation", "Turner5.rotation"])
        self.assertEqual([s["verdict"] for s in r["streams"]], ["same"] * 3)
        self.assertEqual({s["type"] for s in r["streams"]}, {"SFVec3f", "SFRotation"})
        self.assertEqual(r["verdict"], "same")

    def test_a_turntable_with_key_3_14159265_against_3_141593_differs(self):
        world = WORLDS / "turntable.x3d"
        copy = self.changed("turntable.x3d", "0 1 0 3.14159265,", "0 1 0 3.141593,")
        r = pj.judge_pair(world, copy, {"seconds": 5}, repeats=3, x_ite=_x_ite())
        print("\nturntable 3.14159265 vs 3.141593:", r["verdict"], "load", r["load"]["max_1min"], self.table(r),
              [s["a_vs_b"]["max_abs"] for s in r["streams"]], r["streams"][0]["tolerance_unit"])
        self.assertEqual(r["verdict"], "differs")
        self.assertEqual(r["streams"][0]["tolerance_unit"], "rad")
        self.assertGreater(max(r["streams"][0]["a_vs_b"]["max_abs"]), 1.0)        # radians apart, not a hair

    def test_a_turntable_against_itself_is_the_same_as_rotations(self):
        world = WORLDS / "turntable.x3d"
        r = pj.judge_pair(world, world, {"seconds": 5}, repeats=3, x_ite=_x_ite())
        print("\nturntable vs itself:", r["verdict"], "load", r["load"]["max_1min"], self.table(r))
        self.assertEqual(r["verdict"], "same")

    def test_a_node_valued_stream_is_skipped_and_listed(self):
        world = pathlib.Path(self.tmp.name) / "node-stream.x3d"
        world.write_text(NODE_WORLD, encoding="utf-8")
        r = pj.judge_pair(world, world, {"seconds": 3}, repeats=2, x_ite=_x_ite())
        print("\nnode stream world:", r["verdict"], r["skipped"], self.table(r))
        self.assertEqual([row["stream"] for row in r["skipped"]], ["Dst.addChildren"])
        self.assertIn("MFNode", r["skipped"][0]["why"])
        self.assertEqual([s["stream"] for s in r["streams"]], ["T.translation"])
        self.assertEqual(r["verdict"], "same")

    def test_a_pointer_stimulus_cannot_be_forced_into_simultaneous_mode(self):
        with self.assertRaises(pj.PairJudgeError):
            pj.judge_pair(WORLDS / "door.x3d", WORLDS / "door.x3d", {"clicks": 1}, repeats=2, x_ite=_x_ite(), mode="simultaneous")

    # -- nothing moved, frame rate, span note, shared runs ------------------------------------------------------------------

    def test_a_touch_sensor_and_a_still_box_read_unclear_nothing_moved_with_no_stimulus(self):
        world = WORLDS / "touch-still.x3d"
        r = pj.judge_pair(world, world, None, repeats=2, x_ite=_x_ite())
        print("\ntouch-still vs itself:", r["verdict"], r["reason"], "load", r["load"]["max_1min"], r["wall_time_s"]["total"], self.table(r))
        self.assertEqual(r["mode"], "simultaneous")
        self.assertEqual((r["verdict"], r["reason"]), ("unclear", "nothing-moved"))
        self.assertEqual([(s["verdict"], s["reason"]) for s in r["streams"]], [("unclear", "nothing-moved")])
        self.assertEqual(pj.EXIT[r["verdict"]], 2)

    def test_the_turntable_reports_a_frame_rate_samples_and_the_wall_time(self):
        world = WORLDS / "turntable.x3d"
        r = pj.judge_pair(world, world, {"seconds": 3}, repeats=2, x_ite=_x_ite())
        print("\nturntable frame rate:", r["frame_rate"]["median"], r["frame_rate"]["per_run"]["a"][:2], r["wall_time_s"],
              [s["samples"] for s in r["streams"]])
        rows = r["frame_rate"]["per_run"]
        self.assertEqual({n: len(rows[n]) for n in rows}, {"a": 6, "b": 6})           # every run of both files: three a repeat
        self.assertTrue(all(row["frames"] > 0 and row["fps"] > 0 for n in rows for row in rows[n]))
        self.assertGreater(r["frame_rate"]["median"], 0)
        self.assertEqual(r["frame_rate"]["low_limit"], 15.0)
        self.assertEqual({n: len(v) for n, v in r["streams"][0]["samples"].items()}, {"a": 6, "b": 6})
        self.assertTrue(all(n > 0 for v in r["streams"][0]["samples"].values() for n in v))
        self.assertEqual(len(r["wall_time_s"]["per_pair"]), 6)                         # 3 pairs a repeat, 2 repeats
        self.assertGreater(r["wall_time_s"]["total"], 0)

    def test_a_near_still_stream_carries_the_span_note(self):
        world = WORLDS / "near-still.x3d"
        r = pj.judge_pair(world, world, {"seconds": 3}, repeats=2, x_ite=_x_ite())
        s = r["streams"][0]
        print("\nnear-still vs itself:", r["verdict"], s["verdict"], s["reason"], s["span"], s["span_unit"], s["note"], self.table(r))
        self.assertEqual(s["span_unit"], "rad")
        self.assertLess(s["span"], 1e-3)
        self.assertIn("span below 0.001 rad", s["notes"])
        self.assertEqual(s["note"].split(";")[0], "span below 0.001 rad")

    def test_shared_runs_form_the_same_floor_pairs_from_four_pages(self):
        world = WORLDS / "loop-20s.x3d"
        r = pj.judge_pair(world, world, {"seconds": 4}, repeats=2, x_ite=_x_ite(), share_runs=True)
        print("\n20 s loop vs itself, shared runs:", r["verdict"], r["wall_time_s"], self.table(r))
        s = r["streams"][0]
        self.assertTrue(r["wall_time_s"]["shared_runs"])
        self.assertEqual(len(r["wall_time_s"]["per_pair"]), 2)                         # one batch of four pages a repeat
        self.assertEqual((len(s["a_vs_a"]["fraction"]), len(s["b_vs_b"]["fraction"]), len(s["a_vs_b"]["fraction"])), (2, 2, 8))
        self.assertEqual(r["verdict"], "same")
        with self.assertRaises(pj.PairJudgeError):
            pj.judge_pair(world, world, {"seconds": 4}, repeats=2, x_ite=_x_ite(), mode="sequential", share_runs=True)


if __name__ == "__main__":
    unittest.main()
