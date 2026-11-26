# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Outside resources in the behaviour simulator: the ``Resources`` table, LoadSensor, AudioClip and MovieTexture.

Three kinds of test. The table and the rules of each node are small worlds run on the simulator, with the numbers of each
check worked out by hand from the rule it names. The judge tests replay the four traces X_ITE 16.8.1 recorded for these nodes
(tests/behaviour/x_ite_traces/probe-load, probe-loadlive, probe-audio and probe-movie, made by
tools/behaviour_resources_judge.py) through the simulator and demand that every stream agrees. The recording tests check
that a recording carries the table and that an old one without it still loads. ::

    python -m unittest tests.test_behaviour_resources
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_activity as ba                  # noqa: E402
import behaviour_graph as bg                     # noqa: E402
import behaviour_resources as br                 # noqa: E402
import behaviour_resources_judge as judge        # noqa: E402
import behaviour_sim as bs                       # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"


def world(body, routes=""):
    return f'<?xml version="1.0" encoding="UTF-8"?><X3D profile="Full" version="4.0"><head/><Scene>{body}{routes}</Scene></X3D>'


def route(a, fa, b, fb):
    return f'<ROUTE fromNode="{a}" fromField="{fa}" toNode="{b}" toField="{fb}"/>'


SINK = '<BooleanToggle DEF="SinkB"/><ScalarInterpolator DEF="SinkF" key="0 1" keyValue="0 1"/><TimeSensor DEF="SinkT" enabled="false"/>'


def watching(name, *fields):
    types = {"isActive": "SinkB.set_boolean", "isLoaded": "SinkB.set_boolean", "isPaused": "SinkB.set_boolean",
             "progress": "SinkF.set_fraction", "loadTime": "SinkT.set_startTime", "elapsedTime": "SinkT.set_stopTime",
             "duration_changed": "SinkT.set_stopTime"}
    return "".join(route(name, f, *types[f].split(".")) for f in fields)


def run(text, resources=None, until=3.0, step=0.1, calls=()):
    """The simulation after ``until`` seconds in steps of ``step``; ``calls``: [(time, node, field, value)] sent between
    steps as a ROUTE would. Returns (sim, log) where log is [(time, node, field, value)]."""
    graph = bg.Behaviour.from_x3d(text)
    sim = bs.Simulation(graph, log_size=100000, resources=resources)
    sim.start(0.0)
    pending = sorted(calls, key=lambda call: call[0])
    for index in range(1, int(round(until / step)) + 1):
        now = round(index * step, 6)
        while pending and pending[0][0] <= now:
            when, node, field_name, value = pending.pop(0)
            sim.send(node, field_name, value, when)
        sim.step(now)
    return sim, [(round(when, 6), node, field_name, value) for when, node, field_name, value in sim.log]


def events(log, node, field_name):
    return [(when, value) for when, name, field, value in log if name == node and field == field_name]


class TableTests(unittest.TestCase):

    def test_a_table_is_plain_data_and_round_trips(self):
        table = br.Resources({"a.wav": {"loads": 0.4, "duration": 1.0}, "b.png": {"fails": 0.2}})
        self.assertEqual(table.to_dict(), {"a.wav": {"loads": 0.4, "duration": 1.0}, "b.png": {"fails": 0.2}})
        self.assertEqual(br.Resources.from_dict(table.to_dict()), table)
        self.assertTrue(table)
        self.assertFalse(br.Resources())
        self.assertEqual(br.Resources.from_dict(None).to_dict(), {})

    def test_a_duration_alone_is_a_medium_that_is_ready_at_once(self):
        self.assertEqual(br.Resources({"a.wav": {"duration": 2.5}}).to_dict(), {"a.wav": {"loads": 0.0, "duration": 2.5}})

    def test_a_url_list_costs_every_failure_before_the_first_that_loads(self):
        table = br.Resources({"x": {"fails": 0.2}, "y": {"fails": 0.3}, "z": {"loads": 0.5, "duration": 4.0}})
        self.assertEqual(table.resolve(["x", "y", "z"]), (True, 1.0, 4.0, False))
        self.assertEqual(table.resolve(["z", "x"]), (True, 0.5, 4.0, False))
        self.assertEqual(table.resolve(["x", "y"]), (False, 0.5, -1.0, False))

    def test_a_url_the_table_does_not_name_loads_at_once_with_unknown_duration_and_says_so(self):
        loaded, seconds, duration, assumed = br.Resources().resolve(["nowhere.png"])
        self.assertEqual((loaded, seconds, duration, assumed), (True, 0.0, -1.0, True))
        table = br.Resources({"x": {"fails": 0.2}})
        self.assertEqual(table.resolve(["x", "unknown"]), (True, 0.2, -1.0, True))

    def test_a_hostile_table_never_raises_and_says_what_it_left_out(self):
        table = br.Resources({"ok": {"loads": 1.0}, 7: {"loads": 1}, "nan": {"loads": float("nan")}, "neg": {"fails": -1},
                              "inf": {"loads": float("inf")}, "str": {"loads": "soon"}, "map": "x", "both": {"loads": 1, "fails": 2},
                              "none": {}, "dur": {"loads": 1, "duration": -3}, "bool": {"loads": True}})
        self.assertEqual(sorted(table.table), ["both", "dur", "ok"])
        self.assertEqual(table.table["both"], {"fails": 2.0})              # the failure stands
        self.assertEqual(table.table["dur"], {"loads": 1.0})               # a bad duration is dropped, the load stands
        self.assertEqual(len(table.rejected), 10)
        for junk in (None, 3, "x", [], [("a", {})], {"a": None}):
            br.Resources(junk)                                             # never raises

    def test_a_table_is_cut_at_its_limit(self):
        big = br.Resources({str(i): {"loads": 0} for i in range(br.MAX_ENTRIES + 5)})
        self.assertEqual(len(big.table), br.MAX_ENTRIES)
        self.assertTrue(big.rejected)

    def test_the_simulation_counts_what_a_bad_table_dropped(self):
        sim = bs.Simulation(bg.Behaviour.from_x3d(world("")), resources={"a": {"loads": "x"}})
        self.assertEqual(sim.dropped["bad-resource"], 1)
        self.assertEqual(bs.Simulation(bg.Behaviour.from_x3d(world(""))).resources.to_dict(), {})


class LoadSensorTests(unittest.TestCase):

    def sensor(self, children, attributes="", extra=""):
        return world(f'{SINK}<LoadSensor DEF="L"{attributes}>{children}</LoadSensor>{extra}',
                     watching("L", "isActive", "isLoaded", "progress", "loadTime"))

    def test_two_children_report_progress_and_then_load(self):
        text = self.sensor('<ImageTexture containerField="children" url=\'"a.png"\'/><ImageTexture containerField="children" url=\'"b.png"\'/>')
        sim, log = run(text, {"a.png": {"loads": 0.35}, "b.png": {"loads": 0.75}}, until=1.2)
        self.assertEqual(events(log, "L", "isActive"), [(0.0, True), (0.8, False)])
        self.assertEqual(events(log, "L", "progress"), [(0.0, 0.0), (0.4, 0.5), (0.8, 1.0)])       # a step finishes what is due
        self.assertEqual(events(log, "L", "isLoaded"), [(0.8, True)])
        self.assertEqual(events(log, "L", "loadTime"), [(0.8, 0.8)])
        self.assertEqual(sim.noted, {})

    def test_a_failed_child_ends_it_unloaded_and_sends_no_load_time(self):
        text = self.sensor('<ImageTexture containerField="children" url=\'"gone.png"\'/>')
        _, log = run(text, {"gone.png": {"fails": 0.3}}, until=1.0)
        self.assertEqual(events(log, "L", "isActive"), [(0.0, True), (0.3, False)])
        self.assertEqual(events(log, "L", "isLoaded"), [(0.3, False)])
        self.assertEqual(events(log, "L", "progress"), [(0.0, 0.0), (0.3, 0.0)])
        self.assertEqual(events(log, "L", "loadTime"), [])

    def test_a_url_list_whose_first_url_fails_loads_from_the_second(self):
        text = self.sensor('<ImageTexture containerField="children" url=\'"gone.png" "pic.png"\'/>')
        _, log = run(text, {"gone.png": {"fails": 0.2}, "pic.png": {"loads": 0.3}}, until=1.0)
        self.assertEqual(events(log, "L", "isLoaded"), [(0.5, True)])

    def test_a_time_out_ends_it_and_a_late_child_still_reports(self):
        text = self.sensor('<ImageTexture containerField="children" url=\'"slow.png"\'/>', ' timeOut="0.5"')
        _, log = run(text, {"slow.png": {"loads": 1.0}}, until=1.5)
        self.assertEqual(events(log, "L", "isActive"), [(0.0, True), (0.5, False), (1.0, False)])    # X_ITE sends the second False too
        self.assertEqual(events(log, "L", "isLoaded"), [(0.5, False), (1.0, True)])
        self.assertEqual(events(log, "L", "loadTime"), [(1.0, 1.0)])

    def test_no_children_is_inactive_unloaded_and_progress_zero(self):
        _, log = run(self.sensor(""), until=0.3)
        self.assertEqual([events(log, "L", f) for f in ("isActive", "isLoaded", "progress")],
                         [[(0.0, False)], [(0.0, False)], [(0.0, 0.0)]])

    def test_a_url_nobody_declared_loads_at_once_and_is_counted(self):
        text = self.sensor('<ImageTexture containerField="children" url=\'"free.png"\'/>')
        sim, log = run(text, until=0.5)
        self.assertEqual(events(log, "L", "isLoaded"), [(0.1, True)])        # never in the call that asked: the next step
        self.assertEqual(sim.noted["assumed-loaded"], 1)

    def test_a_child_told_to_load_later_is_waited_for(self):
        text = self.sensor('<ImageTexture containerField="children" DEF="Late" load="false" url=\'"a.png"\'/>',
                           extra=route("Go", "inputNegate", "Late", "set_load")) \
            .replace("<LoadSensor", '<BooleanFilter DEF="Go"/><LoadSensor', 1)
        sim, log = run(text, {"a.png": {"loads": 0.5}}, until=2.0, calls=[(1.0, "Go", "set_boolean", False)])
        self.assertEqual(events(log, "L", "isActive"), [(0.0, True), (1.5, False)])
        self.assertEqual(events(log, "L", "progress"), [(0.0, 0.0), (1.0, 0.0), (1.5, 1.0)])     # the load starting is counted too
        self.assertEqual(sim.machines["Late"].state, 2)

    def test_a_sensor_that_is_enabled_after_its_child_loaded_reports_loaded_at_once(self):
        text = self.sensor('<ImageTexture containerField="children" url=\'"a.png"\'/>', ' enabled="false"')
        sim, log = run(text, {"a.png": {"loads": 0.2}}, until=1.0, calls=[(0.5, "L", "set_enabled", True)])
        loaded = events(log, "L", "isLoaded")
        self.assertEqual([value for when, value in loaded], [True])
        self.assertGreaterEqual(loaded[0][0], 0.5)                   # not before it was enabled

    def test_the_markup_is_kept_whole_and_written_back(self):
        text = self.sensor('<ImageTexture containerField="children" DEF="I" url=\'"a.png"\'/>')
        graph = bg.Behaviour.from_x3d(text)
        self.assertEqual(graph.diagnostics, [])
        self.assertIn("ImageTexture", graph.nodes["L"].content)
        again = bg.Behaviour.from_x3d(graph.weave(bg.strip(text)))
        self.assertEqual(again.nodes["L"].content, graph.nodes["L"].content)

    def test_it_runs_over_a_scene_node_the_graph_holds(self):
        text = world(f'{SINK}<LoadSensor DEF="L"><AudioClip containerField="children" DEF="Clip" url=\'"t.wav"\'/></LoadSensor>',
                     watching("L", "isLoaded") + watching("Clip", "duration_changed"))
        sim, log = run(text, {"t.wav": {"loads": 0.25, "duration": 1.5}}, until=1.0)
        self.assertEqual(events(log, "Clip", "duration_changed"), [(0.3, 1.5)])
        self.assertEqual(events(log, "L", "isLoaded"), [(0.3, True)])


class ClockTests(unittest.TestCase):
    """AudioClip and MovieTexture: X3DTimeDependentNode as X_ITE does it."""

    def clip(self, attributes="", kind="AudioClip", more=""):
        node = f'<{kind} DEF="C" url=\'"m"\'{attributes}/>'
        outputs = ("isActive", "isPaused", "elapsedTime", "duration_changed")
        return world(f'{SINK}<Transform><Sound>{node}</Sound></Transform>{more}', watching("C", *outputs)) if kind == "AudioClip" else \
            world(f'{SINK}<Shape><Appearance>{node}</Appearance></Shape>{more}', watching("C", *outputs))

    MEDIUM = {"m": {"loads": 0.0, "duration": 1.0}}

    def test_a_started_clip_sends_elapsed_time_each_step_and_ends_past_its_duration(self):
        sim, log = run(self.clip(), self.MEDIUM, until=2.0, calls=[(0.5, "C", "set_startTime", 0.5)])
        self.assertEqual(events(log, "C", "duration_changed"), [(0.1, 1.0)])
        self.assertEqual(events(log, "C", "isActive"), [(0.5, True), (1.6, False)])
        elapsed = events(log, "C", "elapsedTime")
        self.assertEqual(elapsed[0], (0.5, 0.0))
        self.assertAlmostEqual(elapsed[-1][1], 1.1, places=6)               # sent once more on the step that ends it
        self.assertEqual(len(elapsed), 13)             # 0 twice (the start and the step that follows), then each step to 1.6

    def test_a_clip_is_still_playing_at_exactly_its_duration(self):
        _, log = run(self.clip(), {"m": {"loads": 0.0, "duration": 1.0}}, until=1.0, calls=[(0.0, "C", "set_startTime", 0.0)])
        # started at 0.0 with the medium arriving on the step at 0.1: elapsed counts from the step before, so it is 1.0 at 1.0
        self.assertEqual(events(log, "C", "isActive"), [(0.0, True)])

    def test_a_loop_never_ends_and_a_stop_ends_it(self):
        _, log = run(self.clip(' loop="true"'), self.MEDIUM, until=3.0, calls=[(1.2, "C", "set_stopTime", 1.2)])
        self.assertEqual(events(log, "C", "isActive"), [(0.0, True), (1.2, False)])
        self.assertAlmostEqual(events(log, "C", "elapsedTime")[-1][1], 1.1, places=6)     # the step that stops it sends no time

    def test_pause_and_resume_leave_the_time_paused_out_of_the_elapsed_time(self):
        calls = [(0.5, "C", "set_startTime", 0.5), (0.8, "C", "set_pauseTime", 0.8), (1.4, "C", "set_resumeTime", 1.4)]
        _, log = run(self.clip(), self.MEDIUM, until=2.5, calls=calls)
        self.assertEqual(events(log, "C", "isPaused"), [(0.8, True), (1.4, False)])
        at = dict(events(log, "C", "elapsedTime"))
        self.assertNotIn(0.8, at)                                           # nothing from the pause on
        self.assertNotIn(1.0, at)
        self.assertAlmostEqual(at[1.4], 0.3, places=6)                      # the resume step: 0.5 to 1.4 less 0.6 paused
        self.assertAlmostEqual(at[1.5], 0.4, places=6)
        self.assertEqual(events(log, "C", "isActive")[-1][0], 2.1)          # 1 s of play and 0.6 s of pause after the start at 0.5

    def test_a_pause_time_that_is_not_after_the_resume_time_is_ignored(self):
        calls = [(0.5, "C", "set_startTime", 0.5), (0.6, "C", "set_resumeTime", 0.6), (0.7, "C", "set_pauseTime", 0.4)]
        _, log = run(self.clip(), self.MEDIUM, until=1.0, calls=calls)
        self.assertEqual(events(log, "C", "isPaused"), [])

    def test_a_start_time_while_it_plays_is_ignored_and_one_after_it_ended_restarts(self):
        calls = [(0.5, "C", "set_startTime", 0.5), (0.9, "C", "set_startTime", 0.9), (2.0, "C", "set_startTime", 2.0)]
        _, log = run(self.clip(), self.MEDIUM, until=3.5, calls=calls)
        self.assertEqual([when for when, value in events(log, "C", "isActive")], [0.5, 1.6, 2.0, 3.1])

    def test_a_stop_time_not_after_the_start_time_is_ignored_and_disabling_stops_it(self):
        calls = [(0.5, "C", "set_startTime", 0.5), (0.6, "C", "set_stopTime", 0.2), (0.9, "C", "set_enabled", False)]
        _, log = run(self.clip(), self.MEDIUM, until=1.5, calls=calls)
        self.assertEqual(events(log, "C", "isActive"), [(0.5, True), (0.9, False)])

    def test_a_start_time_in_the_future_starts_on_the_step_that_reaches_it(self):
        _, log = run(self.clip(), self.MEDIUM, until=1.5, calls=[(0.0, "C", "set_startTime", 0.75)])
        self.assertEqual(events(log, "C", "isActive")[0], (0.8, True))

    def test_started_before_the_medium_arrives_it_is_active_and_silent_until_it_does(self):
        calls = [(0.1, "C", "set_startTime", 0.1)]
        _, log = run(self.clip(), {"m": {"loads": 0.45, "duration": 1.0}}, until=2.0, calls=calls)
        self.assertEqual(events(log, "C", "isActive")[0], (0.1, True))
        elapsed = events(log, "C", "elapsedTime")
        self.assertEqual(elapsed[0], (0.5, 0.0))                            # nothing before the medium: then 0, then a frame's worth
        self.assertAlmostEqual(elapsed[1][1], 0.1, places=6)
        self.assertEqual(elapsed[1][0], 0.5)
        self.assertEqual(events(log, "C", "duration_changed"), [(0.5, 1.0)])

    def test_an_audio_clip_sends_its_duration_before_the_elapsed_time_and_a_movie_after(self):
        for kind, first in (("AudioClip", "duration_changed"), ("MovieTexture", "elapsedTime")):
            with self.subTest(kind=kind):
                _, log = run(self.clip(kind=kind), {"m": {"loads": 0.45, "duration": 1.0}}, until=1.0,
                             calls=[(0.1, "C", "set_startTime", 0.1)])
                at_arrival = [field for when, node, field, value in log if node == "C" and when == 0.5]
                self.assertEqual(at_arrival[0], first)

    def test_a_clip_that_fails_to_load_sends_minus_one(self):
        _, log = run(self.clip(), {"m": {"fails": 0.2}}, until=0.6)
        self.assertEqual(events(log, "C", "duration_changed"), [(0.2, -1.0)])

    def test_an_unknown_duration_never_ends_by_itself(self):
        _, log = run(self.clip(), {"m": {"loads": 0.0}}, until=3.0, calls=[(0.5, "C", "set_startTime", 0.5)])
        self.assertEqual(events(log, "C", "duration_changed"), [(0.1, -1.0)])
        self.assertEqual(events(log, "C", "isActive"), [(0.5, True)])

    def test_pitch_does_not_change_an_audio_clips_length_but_speed_and_pitch_change_a_movies(self):
        calls = [(0.5, "C", "set_startTime", 0.5)]
        _, audio = run(self.clip(' pitch="2"'), self.MEDIUM, until=2.5, calls=calls)
        self.assertEqual(events(audio, "C", "isActive")[-1][0], 1.6)
        for attributes, ends in ((' speed="2"', 1.1), (' pitch="2" speed="0.5"', 1.6), (' speed="0.5"', 2.6), (' speed="0"', None),
                                 (' speed="100"', 1.6)):          # 100 is outside what a media element plays at: X_ITE plays at 1
            with self.subTest(attributes=attributes):
                _, log = run(self.clip(attributes, "MovieTexture"), self.MEDIUM, until=3.0, calls=calls)
                active = events(log, "C", "isActive")
                self.assertEqual(active[-1][0] if len(active) > 1 else None, ends)

    def test_unloading_sends_minus_one_and_loading_again_brings_the_medium_back(self):
        calls = [(0.5, "C", "set_load", False), (1.0, "C", "set_load", True)]
        _, log = run(self.clip(), self.MEDIUM, until=1.5, calls=calls)
        self.assertEqual(events(log, "C", "duration_changed"), [(0.1, 1.0), (0.5, -1.0), (1.0, 1.0)])

    def test_what_reaches_the_clip_is_also_reported_as_a_change_and_its_echo_travels(self):
        graph = bg.Behaviour.from_x3d(self.clip())
        sim = bs.Simulation(graph, resources=self.MEDIUM)
        sim.start(0.0)
        sim.send("C", "set_startTime", 0.0, 0.0)
        sim.step(0.1)
        self.assertIn(("C", "startTime", 0.0), [(n, f, v) for _, n, f, v in sim.log])    # the input is on the record too
        self.assertEqual(sim.outputs[("C", "isActive")], True)

    def test_hostile_events_never_raise(self):
        graph = bg.Behaviour.from_x3d(self.clip())
        sim = bs.Simulation(graph, resources={"m": {"loads": 0.1, "duration": 0.5}})
        sim.start(0.0)
        for value in (float("nan"), float("inf"), -1e300, 1e300, 0.0, -5.0):
            for field_name in ("set_startTime", "set_stopTime", "set_pauseTime", "set_resumeTime"):
                try:
                    sim.send("C", field_name, value, 0.0)
                except bg.BehaviourError:
                    pass
        for now in (0.1, 0.2, float("nan"), 0.3, 10.0, 5.0, 11.0):
            sim.step(now)
        self.assertEqual(sim.faults, [])


class SceneNodeTests(unittest.TestCase):

    def test_the_fields_of_a_scene_node_are_read_from_the_file(self):
        graph = bg.Behaviour.from_x3d((WORLDS / "wired-media.x3d").read_text(encoding="utf-8"))
        self.assertEqual(graph.nodes["Film"].role, bg.TARGET)
        self.assertEqual(graph.nodes["Film"].fields, {"url": '"film.mp4"', "loop": "true"})
        self.assertEqual(graph.nodes["Tone"].fields["description"], "a tone")

    def test_the_three_are_simulated_and_the_other_scene_nodes_are_not_event_nodes(self):
        for name in ("LoadSensor", "AudioClip", "MovieTexture"):
            self.assertIn(name, bs.SIMULATED)
        self.assertNotIn("ImageTexture", bs.SIMULATED)
        self.assertNotIn("Inline", bs.SIMULATED)

    def test_the_wired_media_world_runs(self):
        graph = bg.Behaviour.from_x3d((WORLDS / "wired-media.x3d").read_text(encoding="utf-8"))
        sim = bs.Simulation(graph, resources={"film.mp4": {"loads": 0.3, "duration": 2.0}, "tone.wav": {"loads": 0.1, "duration": 1.0}})
        sim.start(0.0)
        for index in range(1, 40):
            sim.step(index * 0.1)
        self.assertEqual(sim.faults, [])
        self.assertEqual(sim.outputs[("Film", "duration_changed")], 2.0)
        self.assertEqual(sim.outputs[("Film", "isActive")], True)      # loop="true" in the file: it started with the world


class RecordingTests(unittest.TestCase):

    def test_a_recording_carries_the_table_and_replays_on_it(self):
        text = world(f'{SINK}<LoadSensor DEF="L"><ImageTexture containerField="children" url=\'"a.png"\'/></LoadSensor>',
                     watching("L", "isLoaded"))
        table = {"a.png": {"loads": 0.45}}
        graph = bg.Behaviour.from_x3d(text)
        sim = bs.Simulation(graph, log_size=10000, resources=table)
        activity = ba.Activity.from_simulation(sim, record=True)
        for call in ("start", "step", "step", "step", "step", "step", "step"):
            when = {"start": 0.0}.get(call, None)
            activity.note_call(call, None, 0.0 if when is not None else 0.1 * (len(activity.stimulus)))
        report = json.loads(json.dumps(activity.report()))
        self.assertEqual(report["resources"], table)
        self.assertEqual(ba.resources_of(report).to_dict(), table)
        fresh = bs.Simulation(bg.Behaviour.from_x3d(text), log_size=10000, resources=ba.resources_of(report))
        ba.replay(fresh, report["stimulus"])
        self.assertEqual(fresh.outputs[("L", "isLoaded")], True)

    def test_a_recording_made_without_the_block_loads_as_before(self):
        sim = bs.Simulation(bg.Behaviour.from_x3d(world("<TimeSensor DEF='T' loop='true'/>")))
        report = ba.Activity.from_simulation(sim, record=True).report()
        self.assertNotIn("resources", report)
        self.assertEqual(ba.resources_of(report).to_dict(), {})
        self.assertEqual(ba.resources_of({"schema": ba.SCHEMA}).to_dict(), {})
        self.assertEqual(ba.resources_of(None).to_dict(), {})
        self.assertEqual(ba.SCHEMA, "x3d.activity/1")                  # the schema did not change: the block is optional


TRACES = WORLDS / "x_ite_traces"
PROBES = ("probe-load", "probe-loadlive", "probe-audio", "probe-movie")


class XiteAgreementTests(unittest.TestCase):
    """The simulator, given what X_ITE 16.8.1 was given, does what X_ITE did, stream by stream (tools/behaviour_resources_judge.py)."""

    def verdict(self, name):
        trace = json.loads((TRACES / f"{name}.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["browser"], "X_ITE 16.8.1")
        self.assertEqual(trace["pageErrors"], 0)
        return judge.judge(WORLDS / f"{name}.x3d", trace)

    def test_every_stream_of_every_probe_agrees(self):
        for name in PROBES:
            with self.subTest(probe=name):
                result = self.verdict(name)
                self.assertEqual([s["source"] for s in result["streams"] if not s["agree"]], [])
                self.assertEqual(result["faults"], [])
                self.assertEqual(result["dropped"], {})
                self.assertEqual(result["noted"], {})                  # every URL was in the table the trace gave
                self.assertTrue(result["agree"])

    def test_the_probes_cover_what_they_claim(self):
        seen = set()
        for name in PROBES:
            result = self.verdict(name)
            for stream in result["streams"]:
                if stream["x_ite_events"]:
                    seen.add((stream["node"], stream["source"].split(".")[1]))
        for node, fields in (("LoadSensor", ("isActive", "isLoaded", "progress", "loadTime")),
                             ("AudioClip", ("isActive", "isPaused", "elapsedTime", "duration_changed")),
                             ("MovieTexture", ("isActive", "isPaused", "elapsedTime", "duration_changed"))):
            for field_name in fields:
                self.assertIn((node, field_name), seen)

    def test_a_clip_that_ends_may_differ_by_one_frame_and_nothing_else_may(self):
        for name in ("probe-audio", "probe-movie"):
            result = self.verdict(name)
            ends = sum(s["ends_within_a_frame"] for s in result["streams"] if s["source"].endswith(".isActive"))
            clips = sum(1 for s in result["streams"] if s["source"].endswith(".isActive") and s["node"] in judge.CLOCKS)
            self.assertLessEqual(ends, clips)
            for stream in result["streams"]:
                self.assertLessEqual(stream["worst_time_gap"], judge.EXACT, stream["source"])

    def test_a_wrong_simulator_is_caught(self):
        trace = json.loads((TRACES / "probe-load.json").read_text(encoding="utf-8"))
        broken = json.loads(json.dumps(trace))
        for event in broken["events"]:
            if event[2] == "Two" and event[3] == "progress" and event[4] == 0.5:
                event[4] = 0.25
        self.assertFalse(judge.judge(WORLDS / "probe-load.x3d", broken)["agree"])
        late = json.loads(json.dumps(trace))
        for event in late["events"]:
            if event[2] == "Sound" and event[3] == "isLoaded":
                event[0] += 0.5
        self.assertFalse(judge.judge(WORLDS / "probe-load.x3d", late)["agree"])

    def test_the_traces_are_x_ite_16_8_1_and_each_world_has_its_media_rules(self):
        for name in PROBES:
            self.assertTrue((WORLDS / f"{name}.media.json").is_file())
            self.assertTrue(judge.urls_of((WORLDS / f"{name}.x3d").read_text(encoding="utf-8")))

    def test_the_media_a_test_makes_are_tiny_and_made_without_a_network(self):
        import tempfile
        import wave
        with tempfile.TemporaryDirectory() as folder:
            judge.make_media(folder, ["a.wav", "b.png"])
            with wave.open(str(Path(folder) / "a.wav")) as clip:
                self.assertEqual(clip.getnframes() / clip.getframerate(), 1.0)
            self.assertEqual((Path(folder) / "b.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertLess((Path(folder) / "a.wav").stat().st_size, 20000)
            with self.assertRaises(ValueError):
                judge.make_media(folder, ["a.mp3"])


if __name__ == "__main__":
    unittest.main()
