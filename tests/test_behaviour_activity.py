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
        (_k, age, count), = activity.packets(1.0 + 0.35 / 2)
        self.assertAlmostEqual(age, 0.5)
        self.assertEqual(count, 1)
        self.assertEqual(activity.packets(1.36), [])

    def test_a_stream_is_a_steady_flow_capped_per_route(self):
        activity = ba.Activity({("A", "x"): [("B", "y", None)]})
        for k in range(1, 121):
            activity.feed([(k / 60, "A", "x", k / 60)], k / 60)      # 60 a second
        packets = activity.packets(2.0)
        self.assertEqual(len(packets), ba.PER_ROUTE)
        self.assertEqual(sum(c for _k, _a, c in packets), 21)        # the events in the last 0.35 s, none invented
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

    def test_sockets(self):
        out = ba.socket_position((100, 200), (240, 150), 1, 3, True)
        inp = ba.socket_position((100, 200), (240, 150), 2, 3, False)
        self.assertEqual(out[0], 340)
        self.assertEqual(inp[0], 100)
        self.assertLess(out[1], 200)
        self.assertGreater(inp[1], 200 - 150)

    def test_panel_rectangles_stay_inside_the_region(self):
        x, y, w, h = ba.hud_rect(800, 600, 390, 250, 12)
        self.assertTrue(x >= 0 and y >= 0 and x + w <= 800 and y + h <= 600)
        x, y, w, h = ba.hud_rect(200, 100, 390, 250, 12)                  # a region smaller than the panel
        self.assertTrue(x >= 0 and y >= 0 and x + w <= 200 and y + h <= 100)
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


if __name__ == "__main__":
    unittest.main()
