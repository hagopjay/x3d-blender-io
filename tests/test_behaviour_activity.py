# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The activity model (source/behaviour_activity.py): plain Python, no Blender. Counts come only from events the
simulation delivered; the numbers are checked against the simulation's own log and against the changes it returned::

    cd tests && python -m unittest test_behaviour_activity
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_activity as ba   # noqa: E402
import behaviour_bench as bench   # noqa: E402
import behaviour_graph as bg      # noqa: E402
import behaviour_sim as bs        # noqa: E402
import behaviour_record as record_tool   # noqa: E402
import behaviour_sim_judge as judge   # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"


def play(shape, n, steps, **options):
    """A benchmark world run for ``steps`` frames with an Activity fed after every simulation call. Returns
    (sim, activity, every change handed back)."""
    sim = bs.Simulation(bench.build(shape, n), log_size=options.pop("log_size", 400))
    activity = ba.Activity.from_simulation(sim, **options)
    changes = []
    when = bench.clicks(shape, n, steps)

    def fed(got):
        activity.feed_log(sim.log, sim.now)
        changes.extend(got)
    fed(sim.start(0.0))
    for k in range(1, steps + 1):
        now = k * bench.DT
        for i in when.get(k, ()):
            fed(sim.click(f"Click{i}", now))
        fed(sim.step(now))
    return sim, activity, changes


class CountsEqualTheSimulation(unittest.TestCase):

    def test_events_equal_the_log(self):
        for shape, n in (("fan", 20), ("chains", 10), ("mixed", 10)):
            with self.subTest(shape=shape):
                sim, activity, _ = play(shape, n, 120, log_size=10_000_000)
                self.assertEqual(activity.events, len(sim.log))
                self.assertEqual(activity.events, sim.log.appended)
                self.assertEqual(sum(r["out"] for r in activity.report()["nodes"]), len(sim.log))

    def test_deliveries_equal_what_the_routes_carried(self):
        # independent of the model: every delivery into a Transform is also a change the simulation handed back
        sim, activity, changes = play("fan", 30, 90, log_size=10_000_000)
        into_targets = sum(r.total for r in activity._routes.values()
                           if sim.graph.nodes[r.key[2]].role == bg.TARGET)
        self.assertEqual(into_targets, len(changes))
        self.assertEqual(sum(r["events"] for r in activity.report()["routes"]), activity.deliveries)
        self.assertEqual(sum(r["in"] for r in activity.report()["nodes"]), activity.deliveries)

    def test_a_bounded_log_loses_nothing_from_the_totals(self):
        sim, activity, _ = play("fan", 30, 60, log_size=8)      # the log holds 8 lines; the fan sends far more
        full, full_activity, _c = play("fan", 30, 60, log_size=10_000_000)
        self.assertEqual(activity.events, full.log.appended)
        self.assertLess(activity.deliveries, full_activity.deliveries)     # what the log dropped is not attributed
        self.assertGreater(activity.unseen, 0)

    def test_the_simulation_is_not_changed(self):
        a = bs.Simulation(bench.build("mixed", 10), log_size=10_000_000)
        b = bs.Simulation(bench.build("mixed", 10), log_size=10_000_000)
        activity = ba.Activity.from_simulation(b)
        outs = [[], []]
        for sim, out in ((a, outs[0]), (b, outs[1])):
            out.extend(sim.start(0.0))
            for k in range(1, 100):
                if k == 5:
                    out.extend(sim.click("Click0", k * bench.DT))
                out.extend(sim.step(k * bench.DT))
                if sim is b:
                    activity.feed_log(b.log, b.now)
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(list(a.log), list(b.log))
        self.assertEqual(a.values, b.values)

    def test_a_route_carries_one_event_per_call_and_only_a_fitting_value(self):
        activity = ba.Activity({("A", "out"): [("B", "in", None), ("C", "in", lambda v: isinstance(v, float))]})
        activity.feed([(1.0, "A", "out", 5)], 1.0)             # an int: B takes it, C's fit says no
        self.assertEqual((activity.deliveries, activity.events), (1, 1))
        activity.feed([(2.0, "A", "out", 1.5), (2.0, "A", "out", 2.5)], 2.0)   # two events in one call: one per ROUTE
        self.assertEqual(activity.route_total(("A", "out", "B", "in")), 2)
        self.assertEqual(activity.route_total(("A", "out", "C", "in")), 1)
        self.assertEqual(activity.events, 3)

    def test_the_door_world(self):
        graph = bg.Behaviour.from_x3d((WORLDS / "door.x3d").read_text(encoding="utf-8"))
        sim = bs.Simulation(graph, log_size=10_000)
        activity = ba.Activity.from_simulation(sim)
        sensor = next(n.id for n in graph.nodes.values() if n.node_type == "TouchSensor")
        for now, call in ((0.0, lambda: sim.start(0.0)), (0.1, lambda: sim.click(sensor, 0.1)),
                          *((0.1 + k / 30, (lambda t: lambda: sim.step(t))(0.1 + k / 30)) for k in range(1, 90))):
            call()
            activity.feed_log(sim.log, sim.now)
        self.assertEqual(activity.events, len(sim.log))
        self.assertGreater(activity.deliveries, 0)
        self.assertEqual(activity.route_count(), len(graph.routes))


class Windows(unittest.TestCase):

    def setUp(self):
        self.activity = ba.Activity({("A", "x"): [("B", "y", None)]}, {("A", "x", "B", "y"): "SFFloat"})
        self.key = ("A", "x", "B", "y")

    def stream(self, times):
        for t in times:
            self.activity.feed([(t, "A", "x", t)], t)

    def test_events_per_second_slides(self):
        self.stream([0.1 * k for k in range(1, 21)])           # 10 a second for two seconds
        self.assertEqual(self.activity.events_per_second(2.0), 10.0)
        self.assertEqual(self.activity.events_per_second(3.5), 0.0)
        self.assertEqual(self.activity.route_rate(self.key, 2.0), 10.0)

    def test_routes_active_in_the_last_second(self):
        self.stream([1.0])
        self.assertEqual((self.activity.routes_active(1.5), self.activity.route_count()), (1, 1))
        self.assertEqual(self.activity.routes_active(2.5), 0)

    def test_widest_cascade_is_the_most_events_sharing_a_timestamp(self):
        self.activity.feed([(1.0, "A", "x", 1.0)] * 1, 1.0)
        self.activity.feed([(2.0, "A", "x", 1.0), (2.0, "Z", "q", 0), (2.0, "Y", "q", 0)], 2.0)
        self.activity.feed([(3.0, "A", "x", 1.0), (3.0, "Z", "q", 0)], 3.0)
        self.assertEqual(self.activity.widest, 3)

    def test_glow_decays(self):
        self.stream([1.0])
        values = [self.activity.glow(self.key, 1.0 + d) for d in (0, 0.25, 0.5, 1.0, 2.0)]
        self.assertEqual(values[0], 1.0)
        self.assertEqual(values[-1], 0.0)
        self.assertEqual(values, sorted(values, reverse=True))


class Packets(unittest.TestCase):

    def test_no_events_no_packets(self):
        sim = bs.Simulation(bench.build("fan", 5))
        activity = ba.Activity.from_simulation(sim)
        self.assertEqual(activity.packets(0.0), [])
        self.assertEqual(activity.packets(10.0), [])
        self.assertEqual(activity.report()["events"], 0)

    def test_a_packet_is_a_delivered_event_and_ages_to_the_end(self):
        activity = ba.Activity({("A", "x"): [("B", "y", None)]})
        activity.feed([(1.0, "A", "x", 0.5)], 1.0)
        key = ("A", "x", "B", "y")
        self.assertEqual(activity.packets(1.0), [(key, 0.0, 1)])
        (_k, age, count), = activity.packets(1.0 + ba.TRAVEL / 2)
        self.assertAlmostEqual(age, 0.5)
        self.assertEqual(count, 1)
        self.assertEqual(activity.packets(1.0 + ba.TRAVEL + 0.01), [])

    def test_a_stream_is_a_steady_flow_capped_per_route(self):
        activity = ba.Activity({("A", "x"): [("B", "y", None)]})
        for k in range(1, 121):
            activity.feed([(k / 60, "A", "x", k / 60)], k / 60)      # 60 a second
        packets = activity.packets(2.0)
        self.assertEqual(len(packets), ba.PER_ROUTE)
        self.assertEqual(sum(c for _k, _a, c in packets), 36)        # the events in the last 0.6 s, none invented
        self.assertTrue(all(0 <= a <= 1 for _k, a, _c in packets))

    def test_the_total_cap(self):
        routes = {("A", f"f{i}"): [("B", f"g{i}", None)] for i in range(600)}
        activity = ba.Activity(routes)
        activity.feed([(1.0, "A", f"f{i}", 1.0) for i in range(600)], 1.0)
        self.assertEqual(len(activity.packets(1.0)), ba.MAX_PACKETS)

    def test_deterministic(self):
        runs = []
        for _ in range(2):
            _sim, activity, _c = play("mixed", 10, 90)
            runs.append((activity.packets(1.0), activity.to_json(1.0)))
        self.assertEqual(runs[0], runs[1])


class Ring(unittest.TestCase):

    def test_a_stream_updates_one_line_and_its_rate(self):
        activity = ba.Activity({("A", "x"): [("B", "y", None)]}, {("A", "x", "B", "y"): "SFFloat"})
        for k in range(30):
            activity.feed([(k / 60, "A", "x", k / 60)], k / 60)      # 0.5 s of a 60/s stream
        lines = list(activity.ring)
        self.assertLessEqual(len(lines), 3)                            # coalesced every 0.25 s, not 30 lines
        self.assertEqual(sum(e.count for e in lines), 30)
        self.assertAlmostEqual(lines[0].rate, 60.0, delta=1.0)
        self.assertEqual(len(lines[0].as_tuple()), 7)

    def test_events_apart_are_separate_lines_and_the_ring_is_bounded(self):
        activity = ba.Activity({("A", "x"): [("B", "y", None)]})
        for k in range(500):
            activity.feed([(k * 1.0, "A", "x", k)], k * 1.0)
        self.assertEqual(len(activity.ring), ba.RING)
        self.assertEqual(activity.ring[-1].value, 499)

    def test_memory_is_bounded(self):
        activity = ba.Activity({("A", "x"): [("B", "y", None)]})
        for k in range(20000):
            activity.feed([(k * 0.0001, "A", "x", k)], k * 0.0001)
        self.assertLessEqual(len(activity._routes[("A", "x", "B", "y")].recent), ba.RECENT)
        self.assertLessEqual(len(activity.ring), ba.RING)


class Report(unittest.TestCase):

    def test_report_is_plain_data_and_json_round_trips(self):
        _sim, activity, _c = play("mixed", 10, 120)
        report = activity.report()
        self.assertEqual(json.loads(activity.to_json()), json.loads(json.dumps(report)))
        self.assertEqual(report["schema"], ba.SCHEMA)
        self.assertEqual(report["events"], activity.events)
        self.assertEqual(report["routes_total"], len(report["routes"]))
        self.assertIn("ring", report)
        self.assertIn("TouchSensor", json.dumps(report) + "TouchSensor")
        text = ba.report_text(report)
        self.assertIn("ROUTE", text)
        self.assertIn(str(report["events"]), text)

    def test_value_text(self):
        self.assertEqual(ba.value_text(True), "TRUE")
        self.assertEqual(ba.value_text(0.5), "0.5")
        self.assertEqual(ba.value_text((1.0, 0.0, 0.25)), "(1, 0, 0.25)")
        self.assertLessEqual(len(ba.value_text(tuple(range(100)))), 32)


class Geometry(unittest.TestCase):

    def test_the_curve_passes_through_both_sockets(self):
        for start, end in (((0, 0), (300, 120)), ((300, 0), (0, 80)), ((10, 10), (10, 10))):
            points = ba.link_curve(start, end)
            self.assertEqual(points[0], start)
            self.assertEqual(points[-1], end)
            self.assertEqual(len(points), 25)

    def test_the_handles_are_horizontal_and_proportional(self):
        start, end = (0.0, 0.0), (200.0, 100.0)
        points = ba.link_curve(start, end, curving=5.0, segments=1000)
        # leaves horizontally: the first segment has (almost) no slope
        self.assertLess(abs(points[1][1] - points[0][1]), 1e-3 * abs(points[1][0] - points[0][0]) + 1e-6)
        mid = ba.bezier(start, (100.0, 0.0), (100.0, 100.0), end, 0.5)       # handle 0.5 * 200 = 100
        self.assertAlmostEqual(ba.point_along(points, ba.arc_lengths(points), 0.5)[0], mid[0], delta=0.5)

    def test_packets_sit_on_the_curve_at_two_zoom_levels(self):
        for scale in (1.0, 0.35, 2.5):
            view = ba.LinearView(scale, (40.0, 25.0))
            curve = ba.link_curve((0, 0), (260, -90))
            points = ba.to_region(view, curve)
            lengths = ba.arc_lengths(points)
            for f in (0.0, 0.2, 0.5, 0.97, 1.0):
                x, y = ba.point_along(points, lengths, f)
                nearest = min(math.hypot(x - px, y - py) for px, py in points)
                self.assertLess(nearest, lengths[-1] / 24)              # on the polyline, within one segment
            self.assertEqual(ba.point_along(points, lengths, 0.0), points[0])
            end = ba.point_along(points, lengths, 1.0)
            self.assertAlmostEqual(end[0], points[-1][0])
            self.assertAlmostEqual(end[1], points[-1][1])
            self.assertAlmostEqual(points[0][0], 40.0)                  # the view's offset and scale are applied
            self.assertAlmostEqual(points[-1][0], 260 * scale + 40.0)

    def test_steady_speed(self):
        points = ba.link_curve((0, 0), (200, 100))
        lengths = ba.arc_lengths(points)
        a, b, c = (ba.point_along(points, lengths, f) for f in (0.2, 0.3, 0.4))
        self.assertAlmostEqual(math.dist(a, b), math.dist(b, c), delta=0.02 * math.dist(a, b))

    def test_sockets_follow_the_measured_layout(self):
        # a node with 14 outputs and 8 inputs, 577.6 units tall (measured on a screenshot of Blender 5.2.2)
        left, top, width, height = 100.0, 500.0, 240.0, 577.6
        first = ba.socket_position(left, top, width, height, 0, 14, True)
        last = ba.socket_position(left, top, width, height, 13, 14, True)
        self.assertAlmostEqual(first[0], 340.0)
        self.assertAlmostEqual(top - first[1], 34.1, places=1)                  # header 23.3 and half a row
        self.assertAlmostEqual((first[1] - last[1]) / 13, 21.6)                 # one row apart
        inputs = [ba.socket_position(left, top, width, height, j, 8, False) for j in range(8)]
        self.assertTrue(all(p[0] == left for p in inputs))
        self.assertAlmostEqual(inputs[-1][1] - (top - height), 13.7, places=1)  # a row's half and the foot's margin
        self.assertAlmostEqual((inputs[0][1] - inputs[-1][1]) / 7, 21.6)
        self.assertGreater(inputs[0][1], inputs[-1][1])                         # the first input is the upper one
        scaled = ba.socket_position(left, top, width, height, 0, 14, True, unit=2.0)   # the UI scale multiplies the constants
        self.assertAlmostEqual(top - scaled[1], 68.2, places=1)
        collapsed = ba.socket_position(left, top, width, 40.0, 3, 8, False, collapsed=True)
        self.assertEqual(collapsed[0], left)
        self.assertAlmostEqual(top - collapsed[1], 11.65)

    def test_the_hud_sits_bottom_left_inside_what_the_sidebar_leaves(self):
        visible = ba.visible_rect(653, 878, left=0, right=250, top=40, bottom=0)
        self.assertEqual(visible, (0, 0, 403, 838))
        x, y, w, h = ba.hud_rect(visible, 400, 300, margin=12, max_fraction=0.6)
        self.assertEqual((x, y), (12, 12))
        self.assertLessEqual(w, 0.6 * 403 + 1e-9)
        self.assertTrue(x + w <= visible[0] + visible[2] and y + h <= visible[1] + visible[3])
        x, y, w, h = ba.hud_rect(ba.visible_rect(200, 100), 400, 300)        # smaller than the block: still inside
        self.assertTrue(x >= 0 and y >= 0 and x + w <= 200 and y + h <= 100)

    def test_counter_labels_skip_what_would_touch(self):
        width = lambda t: 10.0 * len(t)                                      # noqa: E731
        far = [("a", (0, 0, 100, 80), "in 1  out 2"), ("b", (400, 0, 100, 80), "in 3  out 4")]
        placed = ba.counter_labels(far, width, 10)
        self.assertEqual(len(placed), 2)
        text, (x, y, w, h) = placed[0]
        self.assertEqual((x + w, y), (100, 83))                              # right-aligned to the node, just above it
        near = [("a", (0, 0, 100, 80), "in 1  out 2"), ("b", (60, 0, 100, 80), "in 3  out 4")]
        self.assertLess(len(ba.counter_labels(near, width, 10)), 2)          # closer than the label is wide
        over = [("a", (0, 0, 100, 80), "in 1"), ("b", (0, 85, 100, 80), "in 2")]   # b sits where a's label would go
        self.assertEqual([t for t, _r in ba.counter_labels(over, width, 10)], ["in 2"])

    def test_a_badge_finds_a_spot_off_the_nodes(self):
        points = [(float(x), 0.0) for x in range(0, 101, 10)]
        lengths = ba.arc_lengths(points)
        self.assertEqual(ba.badge_spot(points, lengths, 20, 10, []), (50.0, 0.0))
        moved = ba.badge_spot(points, lengths, 20, 10, [(40, -20, 20, 40)])    # a node on the middle
        self.assertNotEqual(moved, (50.0, 0.0))
        self.assertIsNotNone(moved)
        self.assertIsNone(ba.badge_spot(points, lengths, 20, 10, [(-50, -50, 300, 100)]))

    def test_panel_rectangles(self):
        bx, by, bw, bh = ba.badge_rect(50, 50, 20, 10, 4)
        self.assertEqual((bx + bw / 2, by + bh / 2), (50, 50))
        points = ba.rounded_rect(0, 0, 100, 40, 8)
        self.assertTrue(all(-1e-9 <= px <= 100 + 1e-9 and -1e-9 <= py <= 40 + 1e-9 for px, py in points))

    def test_trim_text(self):
        measure = lambda s: 7 * len(s)                                    # noqa: E731
        self.assertEqual(ba.trim_text(measure, "abc", 100), "abc")
        self.assertLessEqual(measure(ba.trim_text(measure, "abcdefghijklmnop", 50)), 50)
        self.assertTrue(ba.trim_text(measure, "abcdefghijklmnop", 50).endswith("…"))

    def test_trail_fades(self):
        points = ba.link_curve((0, 0), (100, 0))
        trail = ba.packet_trail(points, ba.arc_lengths(points), 0.5)
        strengths = [s for _p, s in trail]
        self.assertEqual(strengths[0], 1.0)
        self.assertEqual(strengths, sorted(strengths, reverse=True))
        self.assertEqual(len(ba.packet_trail(points, ba.arc_lengths(points), 0.0)), 1)
        self.assertEqual(ba.TRAVEL, 0.6)


def world_graph(name):
    return bg.Behaviour.from_x3d((WORLDS / f"{name}.x3d").read_text(encoding="utf-8"))


def stimulus_of(name):
    """(graph, [(call, node, time, args)]) for a world: the door and the counter are clicked, then stepped for 4 s."""
    graph = world_graph(name)
    touch = [n.id for n in graph.nodes.values() if n.node_type == "TouchSensor"]
    calls = [("start", None, 0.0, {})]
    for k, sensor in enumerate(touch):
        calls.append(("click", sensor, 0.3 + 0.9 * k, {"held": 0.0}))
        calls.append(("press", sensor, 3.0 + k, {}))
        calls.append(("release", sensor, 3.2 + k, {}))
    calls += [("step", None, i / 30, {}) for i in range(1, 121)]
    calls.sort(key=lambda c: c[2])
    return graph, calls


def drag_stimulus():
    """One CylinderSensor drag with the arguments the X_ITE drag tests give the simulator (probe-drag, sensor Spin)."""
    text = (WORLDS / "probe-drag.x3d").read_text(encoding="utf-8")
    trace = json.loads((WORLDS / "x_ite_traces" / "probe-drag.json").read_text(encoding="utf-8"))
    graph = bg.Behaviour.from_x3d(text)
    actions = judge._drag_actions(graph, text, trace)
    mine = []
    for when, sensor, action, args in actions:
        if sensor != "Spin":
            continue
        mine.append((when, action, args))
        if action == "release":
            break
    calls = [("start", None, mine[0][0] - 1.0, {})]
    for when, action, args in mine:
        if action == "press":
            point, ray, eye, screen = args
            calls.append(("press", "Spin", when, {"point": point, "ray": ray, "eye": eye, "screen": screen}))
        elif action == "drag":
            calls.append(("drag", "Spin", when, {"ray": args[0]}))
        else:
            calls.append(("release", "Spin", when, {}))
    return graph, calls


class Recording(unittest.TestCase):

    def record(self, graph, calls, **options):
        sim = bs.Simulation(graph, log_size=10_000_000)
        activity = ba.Activity.from_simulation(sim, record=True, **options)
        changes = []
        for call, node, when, args in calls:
            changes += activity.drive(sim, call, node, when, **args)
        return sim, activity, changes

    def worlds(self):
        yield "door", stimulus_of("door")
        yield "counter", stimulus_of("counter")
        yield "drag", drag_stimulus()

    def test_the_trace_is_every_delivery_in_the_simulations_order(self):
        for name, (graph, calls) in self.worlds():
            with self.subTest(world=name):
                sim, activity, changes = self.record(graph, calls)
                self.assertGreater(activity.deliveries, 0)
                self.assertEqual(len(activity.trace), activity.deliveries)
                self.assertEqual(len(activity.stimulus), len(calls))
                # independent of the model's own loop: what reached a target is exactly the changes the simulation
                # handed back, in the order it handed them
                into_targets = [(t[3], t[4], t[6]) for t in activity.trace if graph.nodes[t[3]].role == bg.TARGET]
                self.assertEqual(into_targets, [(n, f, ba.plain(v)) for n, f, v in changes])
                times = [t[0] for t in activity.trace]
                self.assertEqual(times, sorted(times))
                self.assertFalse(activity.trace_truncated)
                self.assertEqual(activity.report()["trace"], activity.trace)

    def test_replaying_the_recorded_stimulus_reproduces_the_trace(self):
        for name, (graph, calls) in self.worlds():
            with self.subTest(world=name):
                _sim, first, _c = self.record(graph, calls)
                saved = json.loads(first.to_json())                  # through JSON, as a file would carry it
                fresh = bs.Simulation(world_graph("probe-drag" if name == "drag" else name), log_size=10_000_000)
                again = ba.Activity.from_simulation(fresh, record=True)
                ba.replay(fresh, saved["stimulus"], again)
                self.assertEqual(again.trace, saved["trace"])
                self.assertEqual(again.deliveries, saved["deliveries"])
                self.assertEqual(json.loads(again.to_json())["trace"], saved["trace"])

    def test_the_drag_world_really_turns_the_cylinder(self):
        graph, calls = drag_stimulus()
        _sim, activity, _c = self.record(graph, calls)
        self.assertTrue(any(t[2] in ("rotation_changed", "trackPoint_changed") for t in activity.trace) or
                        activity.events > 0)
        self.assertGreater(len(activity.trace), 3)

    def test_off_by_default_and_null_in_the_report(self):
        sim, activity, _c = play("fan", 5, 10)
        report = activity.report()
        self.assertIsNone(report["trace"])
        self.assertIsNone(report["stimulus"])
        self.assertFalse(report["trace_truncated"])
        activity.note_call("click", "X", 1.0)                      # nothing happens without record=True
        self.assertIsNone(activity.stimulus)

    def test_the_cap_and_the_flag(self):
        old = ba.TRACE_CAP
        ba.TRACE_CAP = 50
        try:
            _sim, activity, _c = self.record(*stimulus_of("door"))
        finally:
            ba.TRACE_CAP = old
        self.assertEqual(len(activity.trace), 50)
        self.assertTrue(activity.trace_truncated)
        self.assertGreater(activity.deliveries, 50)                # the counts are never capped

    def test_values_are_plain_json(self):
        graph, calls = stimulus_of("door")
        _sim, activity, _c = self.record(graph, calls)
        self.assertEqual(json.loads(json.dumps(activity.trace)), activity.trace)
        self.assertTrue(any(isinstance(t[6], list) for t in activity.trace))     # a position is a list of numbers
        self.assertEqual(activity.report()["world"], None)


class ObjectsInTheStimulus(unittest.TestCase):

    def test_a_pointer_call_names_the_object_as_well_as_the_sensor(self):
        for name, sensor, owner in (("door", "Click", "Button"), ("counter", "Press", "Button")):
            with self.subTest(world=name):
                graph, calls = stimulus_of(name)
                _sim, activity, _c = Recording().record(graph, calls)
                pointer = [e for e in activity.stimulus if e["call"] in ba.POINTER_CALLS]
                self.assertTrue(pointer)
                self.assertTrue(all(e["node"] == sensor and e["object"] == owner and "note" not in e for e in pointer))
                self.assertTrue(all("object" not in e for e in activity.stimulus if e["call"] in ("start", "step")))

    def test_replay_from_the_object_alone_gives_the_same_trace(self):
        for name in ("door", "counter"):
            with self.subTest(world=name):
                graph, calls = stimulus_of(name)
                _sim, first, _c = Recording().record(graph, calls)
                only_objects = [{k: v for k, v in e.items() if not (k == "node" and "object" in e)} for e in first.stimulus]
                self.assertTrue(any("node" not in e for e in only_objects))
                fresh = bs.Simulation(world_graph(name), log_size=10_000_000)
                again = ba.Activity.from_simulation(fresh, record=True)
                ba.replay(fresh, only_objects, again)
                self.assertEqual(again.trace, first.trace)

    def test_sensors_on_an_object_climbs_to_the_nearest_object_with_sensors(self):
        graph = world_graph("door")
        self.assertEqual(ba.sensors_on(graph, "Button"), ["Click"])
        self.assertEqual(ba.sensors_on(graph, "ButtonCap", {"ButtonCap": "Button"}.get), ["Click"])
        self.assertEqual(ba.sensors_on(graph, "Door"), [])           # no sensor above it, none at the root


ROOT_SENSOR = """<X3D profile="Immersive" version="4.0"><Scene>
  <TouchSensor DEF="Poke" />
  <Transform DEF="A"><Shape><Box/></Shape></Transform>
  <Transform DEF="B" translation="2 0 0"><Shape><Box/></Shape></Transform>
  <TimeSensor DEF="Clock" cycleInterval="1" />
  <ROUTE fromNode="Poke" fromField="touchTime" toNode="Clock" toField="startTime" />
</Scene></X3D>"""


class SensorWithNoObject(unittest.TestCase):

    def test_a_sensor_at_the_scene_root_has_no_parent_and_can_still_be_poked_by_id(self):
        graph = bg.Behaviour.from_x3d(ROOT_SENSOR)
        self.assertIsNone(graph.nodes["Poke"].parent)
        sim = bs.Simulation(graph, log_size=1000)
        activity = ba.Activity.from_simulation(sim, record=True)
        sim.start(0.0)
        activity.drive(sim, "hover", "Poke", 0.1, over=True)
        activity.drive(sim, "press", "Poke", 0.2)
        activity.drive(sim, "release", "Poke", 0.3)
        self.assertEqual(sim.outputs[("Poke", "touchTime")], 0.3)
        pointer = [e for e in activity.stimulus if e["call"] in ba.POINTER_CALLS]
        self.assertEqual([e["object"] for e in pointer], [None, None, None])
        self.assertTrue(all(e["note"] == ba.NOTE_NO_OBJECT for e in pointer))
        self.assertGreater(activity.deliveries, 0)

    def test_by_object_a_root_sensor_answers_for_every_object(self):
        graph = bg.Behaviour.from_x3d(ROOT_SENSOR)
        self.assertEqual(ba.sensors_on(graph, "A"), ["Poke"])
        self.assertEqual(ba.sensors_on(graph, "B"), ["Poke"])

    def test_a_sensor_in_an_unnamed_group_is_a_root_sensor_to_the_graph(self):
        # pinned limit: the graph keeps only the DEF of the enclosing Transform, so a sensor in an unnamed group at the
        # root has parent None and answers for every object, not only its siblings (docs/BEHAVIOUR_GRAPH.md)
        text = ROOT_SENSOR.replace('<TouchSensor DEF="Poke" />', '<Transform><TouchSensor DEF="Poke" /></Transform>')
        self.assertIsNone(bg.Behaviour.from_x3d(text).nodes["Poke"].parent)


RECORDINGS = WORLDS / "activity"


class CommittedRecordings(unittest.TestCase):
    """tests/behaviour/activity/*.activity.json: made by tools/behaviour_record.py from the .stimulus.json beside them."""

    CASES = (("door", "door"), ("counter", "counter"), ("drag", "probe-drag"))

    def test_the_files_are_what_the_tool_makes_and_small(self):
        for name, world in self.CASES:
            with self.subTest(recording=name):
                path = RECORDINGS / f"{name}.activity.json"
                self.assertLess(path.stat().st_size, 300_000)
                script = json.loads((RECORDINGS / f"{name}.stimulus.json").read_text(encoding="utf-8"))
                made = record_tool.record((WORLDS / f"{world}.x3d").read_text(encoding="utf-8"), script,
                                          world=f"{world}.x3d").report()
                self.assertEqual(json.dumps(made, sort_keys=True, separators=(",", ":")) + "\n",
                                 path.read_text(encoding="utf-8"))

    def test_each_recording_replays_to_itself(self):
        for name, world in self.CASES:
            with self.subTest(recording=name):
                saved = json.loads((RECORDINGS / f"{name}.activity.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["schema"], ba.SCHEMA)
                self.assertEqual(len(saved["trace"]), saved["deliveries"])
                self.assertFalse(saved["trace_truncated"])
                fresh = bs.Simulation(world_graph(world), log_size=10_000_000)
                again = ba.Activity.from_simulation(fresh, record=True)
                ba.replay(fresh, saved["stimulus"], again)
                self.assertEqual(again.trace, saved["trace"])
                self.assertGreater(len(saved["trace"]), 5)


if __name__ == "__main__":
    unittest.main()
