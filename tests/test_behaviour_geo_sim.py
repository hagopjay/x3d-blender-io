# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GeoPositionInterpolator, GeoProximitySensor and GeoTouchSensor (source/behaviour_geo_machines.py) against X_ITE 16.8.1's
own recordings of tests/behaviour/probe-geo.x3d and tests/behaviour/probe-geo-touch.x3d, and what each does on its own. No
Blender.

    python -m unittest tests.test_behaviour_geo_sim
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

import behaviour_graph as bg              # noqa: E402
import behaviour_sim as bs                # noqa: E402     (before behaviour_geo_machines: it registers them)
import behaviour_geo as geo               # noqa: E402
import behaviour_geo_machines as machines  # noqa: E402
import behaviour_sim_judge as judge       # noqa: E402
import behaviour_world as bw              # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"
TRACES = WORLDS / "x_ite_traces"


def x3d(body):
    return f'<X3D profile="Full" version="4.0"><head/><Scene>{body}</Scene></X3D>'


PARIS = '<GeoOrigin DEF="Paris" geoCoords="48.7 2.2 0" rotateYUp="true"/>'


def make(body, world=True):
    text = x3d(body)
    graph = bg.Behaviour.from_x3d(text)
    sim = bs.Simulation(graph, log_size=10 ** 6, world=bw.World.from_x3d(text) if world else None)
    sim.start(0.0)
    return sim


def sent(sim, node, field):
    return [value for _when, n, f, value in sim.log if n == node and f == field]


class JudgedAgainstXite(unittest.TestCase):
    """Every stream the Geo nodes send in the two probe worlds agrees with what X_ITE 16.8.1 sent."""

    @classmethod
    def setUpClass(cls):
        cls.flight_trace = json.loads((TRACES / "probe-geo.json").read_text(encoding="utf-8"))
        cls.flight = judge.judge(WORLDS / "probe-geo.x3d", cls.flight_trace, world_viewer=True)
        cls.touch_trace = json.loads((TRACES / "probe-geo-touch.json").read_text(encoding="utf-8"))
        cls.touch = judge.judge(WORLDS / "probe-geo-touch.x3d", cls.touch_trace)

    def test_recorded_on_x_ite_16_8_1_without_errors(self):
        for trace in (self.flight_trace, self.touch_trace):
            self.assertEqual(trace["browser"], "X_ITE 16.8.1")
            self.assertEqual(trace["pageErrors"], [])
            self.assertEqual(trace["missing"], [])

    def test_the_flight_world_agrees_stream_for_stream(self):
        self.assertEqual([s["source"] for s in self.flight["streams"] if not s["agree"]], [])
        self.assertEqual(self.flight["not_simulated"], [])
        self.assertEqual(len(self.flight["streams"]), 96)

    def test_the_touch_world_agrees_stream_for_stream(self):
        self.assertEqual([s["source"] for s in self.touch["streams"] if not s["agree"]], [])
        self.assertEqual(self.touch["not_simulated"], [])
        self.assertEqual([s["source"] for s in self.touch["streams"]],
                         [f"{d}.hitGeoCoord_changed" for d in ("TouchParis", "TouchFlat", "TouchUtm", "TouchBare", "TouchGc", "TouchMoved")])

    def test_every_geo_stream_is_one_x_ite_really_sent(self):
        geo_streams = [s for result in (self.flight, self.touch) for s in result["streams"] if s["node"].startswith("Geo")]
        self.assertEqual(len(geo_streams), 16 * 2 + 8 * 7 + 2 + 6)      # interpolators, proximity sensors, geoCenter and center, touch sensors
        for stream in geo_streams:
            with self.subTest(stream=stream["source"]):
                self.assertGreater(stream["x_ite_events"], 0, "a stream X_ITE never sent proves nothing")
                self.assertEqual(stream["x_ite_only"], 0)
                self.assertLess(stream["worst_gap"], 1e-3)

    def test_every_node_type_is_judged(self):
        nodes = {s["node"] for result in (self.flight, self.touch) for s in result["streams"]}
        self.assertLessEqual({"GeoPositionInterpolator", "GeoProximitySensor", "GeoTouchSensor"}, nodes)

    def test_the_geoorigins_the_probe_points_at_are_all_in_play(self):
        text = (WORLDS / "probe-geo.x3d").read_text(encoding="utf-8")
        for origin in ("Paris", "ParisFlat", "Sydney", "UtmOrigin", "UtmOrigin2", "MarsOrigin", "Pole"):
            self.assertIn(f'USE="{origin}"', text)
        for system in ('"GD" "WE"', '"GD" "BR" "longitude_first"', '"UTM" "Z31"', '"UTM" "Z56" "S"', '"UTM" "Z33" "easting_first"',
                       '"GC"', '"GD" "MARS"', '"GD" "RF"'):
            self.assertIn(f"geoSystem='{system}'", text)

    def test_a_changed_machine_is_caught(self):
        # the judge can fail: interpolate in geodetic space instead of X_ITE's geocentric slerp and GpiFar disagrees
        real = geo.slerp
        try:
            geo.slerp = lambda a, b, t: tuple(x + t * (y - x) for x, y in zip(a, b))
            result = judge.judge(WORLDS / "probe-geo.x3d", self.flight_trace, world_viewer=True)
        finally:
            geo.slerp = real
        self.assertIn("GpiFar.geovalue_changed", [s["source"] for s in result["streams"] if not s["agree"]])

    def test_the_text_resolution_rule_is_what_the_comment_says(self):
        # X_ITE writes an SFVec3f with seven significant digits: 4773938.5 is 4773938 or 4773939 there
        self.assertEqual(judge._gap_to_text_resolution("4773938 1 1", "4773938.5 1 1"), 0.0)
        self.assertEqual(judge._gap_to_text_resolution("4773938 1 1", "4773939.5 1 1"), 0.5)
        self.assertAlmostEqual(judge._gap_to_text_resolution("0.5 1 1", "0.52 1 1"), 0.02 - 1e-7, places=12)


class Interpolator(unittest.TestCase):

    def one(self, key, key_value, system='"GD" "WE"', origin='<GeoOrigin USE="Paris" containerField="geoOrigin"/>'):
        sim = make(f'{PARIS}<GeoPositionInterpolator DEF="G" geoSystem=\'{system}\' key="{key}" keyValue="{key_value}">{origin}'
                   f'</GeoPositionInterpolator>')
        return sim

    def test_it_interpolates_in_geocentric_space_not_in_geodetic(self):
        sim = make('<GeoPositionInterpolator DEF="G" key="0 1" keyValue="0 0 0 0 120 0"/>')
        sim.send("G", "set_fraction", 0.5, 1.0)
        latitude, longitude, height = sent(sim, "G", "geovalue_changed")[-1]
        self.assertAlmostEqual(latitude, 0.0, places=6)
        self.assertAlmostEqual(longitude, 60.0, places=6)
        # the straight-line midpoint of the two points would be nearer the Earth than the arc: the arc's length is the
        # lerp of the two lengths, so the height of the middle of an equatorial arc is the same as the ends'
        self.assertAlmostEqual(height, 0.0, places=3)

    def test_value_changed_is_single_precision_and_geovalue_changed_is_double(self):
        sim = self.one("0 1", "48.8 2.3 0  48.9 2.4 100")
        sim.send("G", "set_fraction", 0.37, 1.0)
        value = sent(sim, "G", "value_changed")[-1]
        self.assertEqual(value, machines.float32(value))                        # already a float32
        local = geo.GeoFrame(["GD", "WE"], geo.GeoOrigin(("GD", "WE"), (48.7, 2.2, 0.0), True))
        want = geo.slerp(local.local((48.8, 2.3, 0.0)), local.local((48.9, 2.4, 100.0)), 0.37)
        self.assertNotEqual(value, want)
        for mine, theirs in zip(value, want):
            self.assertAlmostEqual(mine, theirs, delta=abs(theirs) * 1e-6 + 1e-6)
        self.assertEqual(sent(sim, "G", "geovalue_changed")[-1], local.geo(want))   # the double: the unrounded point converted back

    def test_the_ends_are_the_keys(self):
        sim = self.one("0 1", "48.8 2.3 0  48.9 2.4 100")
        sim.send("G", "set_fraction", -1.0, 1.0)
        sim.send("G", "set_fraction", 2.0, 2.0)
        first, last = sent(sim, "G", "geovalue_changed")
        for mine, want in zip(first, (48.8, 2.3, 0.0)):
            self.assertAlmostEqual(mine, want, places=5)
        for mine, want in zip(last, (48.9, 2.4, 100.0)):
            self.assertAlmostEqual(mine, want, places=5)

    def test_no_key_no_event_one_key_one_value_a_short_keyvalue_is_padded(self):
        sim = self.one("", "")
        sim.send("G", "set_fraction", 0.5, 1.0)
        self.assertEqual(sent(sim, "G", "value_changed"), [])
        sim = self.one("0.5", "48.8 2.3 10")
        sim.send("G", "set_fraction", 0.1, 1.0)
        self.assertEqual(len(sent(sim, "G", "geovalue_changed")), 1)
        sim = self.one("0 0.5 1", "48.8 2.3 0  48.9 2.4 0")
        sim.send("G", "set_fraction", 0.9, 1.0)            # between key 1 and 2: both are the last value, padded
        latitude, longitude, _ = sent(sim, "G", "geovalue_changed")[0]
        self.assertAlmostEqual(latitude, 48.9, places=5)
        sim = self.one("0 1", "")                          # no values: the zero coordinate
        sim.send("G", "set_fraction", 0.5, 1.0)
        for mine in sent(sim, "G", "geovalue_changed")[0][:2]:
            self.assertAlmostEqual(mine, 0.0, places=6)

    def test_keys_and_values_can_be_replaced_while_it_runs(self):
        sim = self.one("0 1", "48.8 2.3 0  48.9 2.4 100")
        sim.send("G", "set_fraction", 0.5, 1.0)
        sim.send("G", "keyValue", [(48.8, 2.3, 0.0), (49.5, 3.0, 100.0)], 2.0)
        sim.send("G", "set_fraction", 1.0, 3.0)
        self.assertAlmostEqual(sent(sim, "G", "geovalue_changed")[-1][0], 49.5, places=5)

    def test_utm_and_gc_nodes_send_their_own_geosystem(self):
        sim = self.one("0 1", "5411000 452000 0  5413000 455000 100", system='"UTM" "Z31"', origin="")
        sim.send("G", "set_fraction", 1.0, 1.0)
        northing, easting, height = sent(sim, "G", "geovalue_changed")[-1]
        self.assertAlmostEqual(northing, 5413000.0, delta=1.0)
        self.assertAlmostEqual(easting, 455000.0, delta=1.0)
        sim = self.one("0 1", "4205000 170000 4776000  4205200 170200 4776300", system='"GC"')
        sim.send("G", "set_fraction", 1.0, 1.0)
        for mine, want in zip(sent(sim, "G", "geovalue_changed")[-1], (4205200.0, 170200.0, 4776300.0)):
            self.assertAlmostEqual(mine, want, places=6)

    def test_hostile_numbers_are_dropped_and_counted_never_raised(self):
        for key_value in ("nan 0 0  1 1 1", "1e308 1e308 1e308  -1e308 5 5", "inf 0 0  0 0 inf", "91 0 0  0 400 1e30"):
            for system in ('"GD" "WE"', '"UTM" "Z99999999999999999999"', '"GC"'):
                with self.subTest(key_value=key_value, system=system):
                    sim = self.one("0 1", key_value, system=system)
                    for fraction in (0.0, 0.3, 1.0):
                        sim.send("G", "set_fraction", fraction, 1.0)
                    self.assertEqual(sim.faults, [])


class Origins(unittest.TestCase):

    def test_an_inline_geoorigin(self):
        sim = make('<GeoPositionInterpolator DEF="G" key="0 1" keyValue="48.8 2.3 0  48.9 2.4 0">'
                   '<GeoOrigin geoCoords="48.7 2.2 0" rotateYUp="true"/></GeoPositionInterpolator>', world=False)
        sim.send("G", "set_fraction", 0.0, 1.0)
        east, up, south = sent(sim, "G", "value_changed")[-1]
        self.assertGreater(east, 5000.0)            # 0.1 degree of longitude at 49 degrees
        self.assertLess(abs(south), 12000.0)

    def test_a_use_of_a_geoorigin_the_world_read(self):
        sim = make(f'{PARIS}<GeoPositionInterpolator DEF="G" key="0 1" keyValue="48.8 2.3 0  48.9 2.4 0">'
                   '<GeoOrigin USE="Paris" containerField="geoOrigin"/></GeoPositionInterpolator>')
        sim.send("G", "set_fraction", 0.0, 1.0)
        self.assertEqual(len(sent(sim, "G", "value_changed")), 1)
        self.assertEqual(sim.noted.get("geo-origin-unresolved"), None)

    def test_a_use_defined_in_another_nodes_content_is_found_without_a_world(self):
        sim = make('<GeoPositionInterpolator DEF="A" key="0 1" keyValue="48.8 2.3 0  48.9 2.4 0">'
                   '<GeoOrigin DEF="Here" geoCoords="48.7 2.2 0" rotateYUp="true"/></GeoPositionInterpolator>'
                   '<GeoPositionInterpolator DEF="B" key="0 1" keyValue="48.8 2.3 0  48.9 2.4 0">'
                   '<GeoOrigin USE="Here" containerField="geoOrigin"/></GeoPositionInterpolator>', world=False)
        sim.send("A", "set_fraction", 0.5, 1.0)
        sim.send("B", "set_fraction", 0.5, 1.0)
        self.assertEqual(sent(sim, "A", "value_changed"), sent(sim, "B", "value_changed"))
        self.assertEqual(sim.noted.get("geo-origin-unresolved"), None)

    def test_a_use_that_names_nothing_is_refused_by_name(self):
        sim = make('<GeoPositionInterpolator DEF="G" key="0 1" keyValue="48.8 2.3 0  48.9 2.4 0">'
                   '<GeoOrigin USE="Gone" containerField="geoOrigin"/></GeoPositionInterpolator>')
        sim.send("G", "set_fraction", 0.5, 1.0)
        self.assertEqual(sent(sim, "G", "value_changed"), [])
        self.assertEqual(sim.noted["geo-origin-unresolved"], 1)
        self.assertEqual(sim.faults, [])

    def test_no_origin_is_geocentric_metres(self):
        sim = make('<GeoPositionInterpolator DEF="G" key="0 1" keyValue="0 0 0  0 0 0"/>')
        sim.send("G", "set_fraction", 0.5, 1.0)
        self.assertEqual(sent(sim, "G", "value_changed")[-1], machines.float32((6378137.0, 0.0, 0.0)))

    def test_the_world_reads_every_geoorigin_by_def(self):
        world = bw.World.from_x3d(x3d(PARIS + '<GeoOrigin DEF="Other" geoSystem=\'"UTM" "Z31"\' geoCoords="5410000 450000 0"/>'))
        self.assertEqual(sorted(world.geo_origins), ["Other", "Paris"])
        self.assertEqual(world.geo_origins["Paris"].rotate_y_up, True)
        self.assertEqual(world.geo_origins["Other"].system, ("UTM", "Z31"))


class Proximity(unittest.TestCase):

    BODY = (PARIS + '<Transform translation="0 0 0"><GeoProximitySensor DEF="P" size="10 10 10" center="0 0 0">'
            '<GeoOrigin USE="Paris" containerField="geoOrigin"/></GeoProximitySensor></Transform>')

    def test_it_is_a_proximity_sensor_with_geocoord_changed(self):
        sim = make(self.BODY)
        sim.view((0.0, 1.6, 3.0), (0.0, 0.0, 1.0, 0.0), 1.0)
        self.assertEqual(sent(sim, "P", "isActive"), [True])
        self.assertEqual(sent(sim, "P", "position_changed"), [(0.0, 1.6, 3.0)])
        latitude, longitude, height = sent(sim, "P", "geoCoord_changed")[0]
        self.assertAlmostEqual(latitude, 48.7, places=4)
        self.assertAlmostEqual(longitude, 2.2, places=4)
        self.assertAlmostEqual(height, 1.6, delta=1e-3)
        sim.view((0.0, 1.6, 4.0), (0.0, 0.0, 1.0, 0.0), 2.0)
        self.assertEqual(len(sent(sim, "P", "geoCoord_changed")), 2)
        sim.view((0.0, 1.6, 40.0), (0.0, 0.0, 1.0, 0.0), 3.0)
        self.assertEqual(sent(sim, "P", "isActive"), [True, False])
        self.assertEqual(len(sent(sim, "P", "geoCoord_changed")), 2)      # nothing when it is outside

    def test_the_geocenter_in_the_file_is_not_read_but_one_that_arrives_is_copied_as_it_is(self):
        sim = make('<GeoProximitySensor DEF="P" size="2 2 2" center="1 2 3" geoCenter="40 50 60"/>')
        self.assertEqual(sim.machines["P"].f["center"], (1.0, 2.0, 3.0))
        sim.send("P", "geoCenter", (5.0, 6.0, 7.0), 1.0)
        self.assertEqual(sim.machines["P"].f["center"], (5.0, 6.0, 7.0))
        self.assertEqual(sent(sim, "P", "geoCenter"), [(5.0, 6.0, 7.0)])
        self.assertEqual(sent(sim, "P", "center"), [(5.0, 6.0, 7.0)])

    def test_disabled_it_leaves_at_once_and_enabled_it_enters_with_this_frames_viewer(self):
        sim = make(self.BODY)
        sim.view((0.0, 1.6, 3.0), (0.0, 0.0, 1.0, 0.0), 1.0)
        sim.send("P", "enabled", False, 2.0)
        self.assertEqual(sent(sim, "P", "isActive"), [True, False])
        self.assertEqual(sent(sim, "P", "exitTime"), [2.0])
        sim.send("P", "enabled", True, 3.0)
        self.assertEqual(sent(sim, "P", "isActive"), [True, False, True])
        self.assertEqual(sent(sim, "P", "enterTime"), [1.0, 3.0])

    def test_through_viewer_it_takes_the_sensors_own_coordinates(self):
        text = x3d(PARIS + '<Transform DEF="T" translation="100 0 0"><GeoProximitySensor DEF="P" size="10 10 10">'
                   '<GeoOrigin USE="Paris" containerField="geoOrigin"/></GeoProximitySensor></Transform>')
        sim = bs.Simulation(bg.Behaviour.from_x3d(text), world=bw.World.from_x3d(text))
        sim.start(0.0)
        sim.viewer("P", (1.0, 1.0, 1.0), (0.0, 0.0, 1.0, 0.0), 1.0)
        self.assertEqual(sent(sim, "P", "position_changed"), [(1.0, 1.0, 1.0)])

    def test_it_is_listed_with_the_proximity_sensors(self):
        self.assertEqual(bs.PROXIMITY, ("ProximitySensor", "GeoProximitySensor"))
        with self.assertRaises(bg.BehaviourError):
            make(self.BODY).viewer("Nope", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), 1.0)


class Touch(unittest.TestCase):

    BODY = (PARIS + '<Transform><Shape><Box/></Shape><GeoTouchSensor DEF="T"><GeoOrigin USE="Paris" containerField="geoOrigin"/>'
            '</GeoTouchSensor></Transform>')

    def test_a_hit_while_over_is_also_a_geocoordinate(self):
        sim = make(self.BODY)
        sim.hover("T", True, 1.0)
        sim.hit("T", (0.0, 5.0, 0.0), 1.0)
        self.assertEqual(sent(sim, "T", "hitPoint_changed"), [(0.0, 5.0, 0.0)])
        latitude, longitude, height = sent(sim, "T", "hitGeoCoord_changed")[0]
        self.assertAlmostEqual(latitude, 48.7, places=6)
        self.assertAlmostEqual(longitude, 2.2, places=6)
        self.assertAlmostEqual(height, 5.0, delta=1e-3)

    def test_not_over_or_disabled_it_sends_no_hit(self):
        sim = make(self.BODY)
        self.assertEqual(sim.hit("T", (0.0, 5.0, 0.0), 1.0), [])
        sim.hover("T", True, 1.0)
        sim.send("T", "enabled", False, 1.5)
        self.assertEqual(sim.hit("T", (0.0, 5.0, 0.0), 2.0), [])
        self.assertEqual(sent(sim, "T", "hitGeoCoord_changed"), [])

    def test_the_pointer_events_a_recording_gives_make_the_same_geocoordinate(self):
        sim = make(self.BODY)
        sim.machines["T"].over = True
        sim.post("T", "hitPoint_changed", (1.0, 2.0, 3.0), 1.0)
        self.assertEqual(len(sent(sim, "T", "hitGeoCoord_changed")), 1)
        sim.machines["T"].over = False
        sim.post("T", "hitPoint_changed", (1.0, 2.0, 3.0), 2.0)       # X_ITE: nothing while the pointer is off the shape
        self.assertEqual(len(sent(sim, "T", "hitGeoCoord_changed")), 1)

    def test_it_is_a_touch_sensor_for_press_and_release(self):
        sim = make(self.BODY)
        sim.press("T", 1.0)
        sim.release("T", 1.5)
        self.assertEqual(sent(sim, "T", "isOver"), [True])
        self.assertEqual(sent(sim, "T", "isActive"), [True, False])
        self.assertEqual(sent(sim, "T", "touchTime"), [1.5])
        self.assertNotIn("GeoTouchSensor", bs.POINTING)       # the Player and the fuzzer feed POINTING; GEO_POINTING is the rest
        self.assertEqual(bs.GEO_POINTING, ("GeoTouchSensor",))

    def test_a_hit_that_is_not_a_point_is_dropped_and_counted(self):
        sim = make(self.BODY)
        sim.hover("T", True, 1.0)
        self.assertEqual(sim.hit("T", (math.nan, 0.0, 0.0), 1.0), [])
        self.assertEqual(sim.hit("T", (1.0, 2.0), 1.0), [])
        self.assertEqual(sim.dropped["non-finite"], 1)
        self.assertEqual(sim.dropped["mismatch"], 1)

    def test_a_use_that_names_nothing_sends_no_geocoordinate(self):
        sim = make('<Transform><Shape><Box/></Shape><GeoTouchSensor DEF="T"><GeoOrigin USE="Gone" containerField="geoOrigin"/>'
                   '</GeoTouchSensor></Transform>')
        sim.hover("T", True, 1.0)
        sim.hit("T", (0.0, 5.0, 0.0), 1.0)
        self.assertEqual(len(sent(sim, "T", "hitPoint_changed")), 1)
        self.assertEqual(sent(sim, "T", "hitGeoCoord_changed"), [])
        self.assertEqual(sim.noted["geo-origin-unresolved"], 1)


class Wired(unittest.TestCase):

    def test_the_wired_geo_file_runs(self):
        text = (WORLDS / "wired-geo.x3d").read_text(encoding="utf-8")
        graph = bg.Behaviour.from_x3d(text)
        sim = bs.Simulation(graph, world=bw.World.from_x3d(text))
        sim.start(0.0)
        sim.click("Ground", 1.0)
        for step in range(1, 40):
            sim.step(1.0 + step / 10)
        self.assertEqual(sim.faults, [])
        self.assertIn(("Route", "geovalue_changed"), sim.outputs)
        self.assertNotIn("GeoPositionInterpolator Route", sim.not_simulated)
        self.assertEqual(sim.noted.get("geo-origin-unresolved"), None)

    def test_they_are_simulated(self):
        for name in ("GeoPositionInterpolator", "GeoProximitySensor", "GeoTouchSensor"):
            self.assertIn(name, bs.SIMULATED)


if __name__ == "__main__":
    unittest.main()
