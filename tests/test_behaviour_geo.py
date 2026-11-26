# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""source/behaviour_geo.py against X_ITE 16.8.1's own numbers (tests/behaviour/geo_conversions.json, recorded by
tools/behaviour_geo_probe.py): geoSystem parsing, geodetic, UTM and geocentric conversion in both directions on several
ellipsoids and both hemispheres, a Geo node's local frame with and without a GeoOrigin (with and without rotateYUp) and the
interpolator's slerp. No Blender.

    python -m unittest tests.test_behaviour_geo
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

import behaviour_geo as geo   # noqa: E402

RECORD = json.loads((ROOT / "tests" / "behaviour" / "geo_conversions.json").read_text(encoding="utf-8"))
TOLERANCE = 1e-6      # metres or degrees: X_ITE's and Python's hypot and trigonometry differ in the last digits (worst seen 4e-9)


def ask(case):
    op = case["op"]
    if op in ("convert", "apply"):
        gs = geo.parse_geo_system(case["geoSystem"])
        return (geo.to_geocentric if op == "convert" else geo.from_geocentric)(gs, case["in"])
    if op in ("local", "geo"):
        o = case["origin"]
        origin = None if o is None else geo.GeoOrigin(tuple(o["geoSystem"]), tuple(o["geoCoords"]), o["rotateYUp"])
        frame = geo.GeoFrame(case["geoSystem"], origin)
        return (frame.local if op == "local" else frame.geo)(case["in"])
    return geo.slerp(case["a"], case["b"], case["t"])


class AgainstXite(unittest.TestCase):

    def test_the_record_is_what_the_tool_says_it_is(self):
        self.assertIn("X_ITE 16.8.1", RECORD["instrument"])
        self.assertEqual(len(RECORD["cases"]), len(RECORD["answers"]))
        ops = {}
        for case in RECORD["cases"]:
            ops[case["op"]] = ops.get(case["op"], 0) + 1
        self.assertEqual(sorted(ops), ["apply", "convert", "geo", "local", "slerp"])
        self.assertGreaterEqual(min(ops.values()), 10)

    def test_every_recorded_case_agrees(self):
        worst = {}
        for case, answer in zip(RECORD["cases"], RECORD["answers"]):
            with self.subTest(case=json.dumps(case)[:160]):
                mine = ask(case)
                if any(v is None for v in answer):          # X_ITE's NaN or infinity (JSON has none)
                    self.assertTrue(any(not math.isfinite(v) for v in mine))
                    continue
                gap = max(abs(m - x) for m, x in zip(mine, answer))
                worst[case["op"]] = max(worst.get(case["op"], 0.0), gap)
                self.assertLess(gap, TOLERANCE)
        self.assertEqual(set(worst), {"apply", "convert", "geo", "local", "slerp"})

    def test_the_cases_cover_the_ellipsoids_hemispheres_and_zones_the_spec_asks_for(self):
        systems = {tuple(c["geoSystem"]) for c in RECORD["cases"] if "geoSystem" in c}
        flat = {t for s in systems for t in s}
        self.assertTrue({"WE", "BR", "IN", "MARS", "RF"} <= flat)                    # WGS 84 and four other ellipsoids
        self.assertTrue({"Z31", "Z17", "Z56", "Z1", "Z60"} <= flat and "S" in flat)  # zones, north and south of the equator
        latitudes = [c["in"][0] for c in RECORD["cases"] if c["op"] == "convert" and c["geoSystem"][:1] == ["GD"]]
        self.assertTrue(min(latitudes) < 0 < max(latitudes))
        longitudes = [c["in"][1] for c in RECORD["cases"] if c["op"] == "convert" and c["geoSystem"] == ["GD", "WE"]]
        self.assertTrue(min(longitudes) < 0 < max(longitudes))


class Parsing(unittest.TestCase):

    def test_the_defaults_are_geodetic_wgs84_latitude_first(self):
        gs = geo.parse_geo_system([])
        self.assertEqual((gs.kind, gs.standard, gs.zone, gs.northern), ("GD", True, 1, True))
        self.assertEqual((gs.a, gs.c), geo.ELLIPSOIDS["WE"])

    def test_tokens_in_any_order_and_unknown_ones_are_ignored(self):
        gs = geo.parse_geo_system(["longitude_first", "BR", "bogus", "GD"])
        self.assertEqual((gs.kind, gs.standard, gs.a), ("GD", False, geo.ELLIPSOIDS["BR"][0]))
        gs = geo.parse_geo_system(["UTM", "Z33", "S", "easting_first", "IN"])
        self.assertEqual((gs.kind, gs.zone, gs.northern, gs.standard), ("UTM", 33, False, False))

    def test_web_mercator_is_unknown_to_x_ite_and_reads_as_geodetic(self):
        self.assertEqual(geo.parse_geo_system(["WM"]).kind, "GD")

    def test_a_zone_token_must_be_the_whole_token(self):
        self.assertEqual(geo.parse_geo_system(["UTM", "Z31N"]).zone, 1)
        self.assertEqual(geo.parse_geo_system(["UTM", "z31"]).zone, 1)

    def test_mfstring_text(self):
        self.assertEqual(geo.strings('"GD" "WE"'), ["GD", "WE"])
        self.assertEqual(geo.strings('"UTM", "Z31"'), ["UTM", "Z31"])
        self.assertEqual(geo.strings("GD WE"), ["GD", "WE"])
        self.assertEqual(geo.strings(""), [])
        self.assertEqual(geo.strings('""'), [""])
        self.assertEqual(geo.strings(None), [])

    def test_a_geoorigin_from_attributes(self):
        o = geo.origin_from_attributes({"geoSystem": '"GD" "BR"', "geoCoords": "1 2 3", "rotateYUp": "TRUE"})
        self.assertEqual((o.system, o.coords, o.rotate_y_up), (("GD", "BR"), (1.0, 2.0, 3.0), True))
        o = geo.origin_from_attributes({"geoCoords": "1 2"})
        self.assertEqual((o.system, o.coords, o.rotate_y_up), (("GD", "WE"), (0.0, 0.0, 0.0), False))


class Properties(unittest.TestCase):

    def test_geodetic_round_trip_on_every_ellipsoid_of_the_table(self):
        for code in geo.ELLIPSOIDS:
            gs = geo.parse_geo_system(["GD", code])
            for point in ((48.8, 2.3, 35.0), (-33.9, 151.2, 58.0), (0.0, 0.0, 0.0), (-80.0, -170.0, 100.0)):
                with self.subTest(ellipsoid=code, point=point):
                    back = geo.from_geocentric(gs, geo.to_geocentric(gs, point))
                    if code == "URANUS":        # X_ITE's table has a smaller than c: not an ellipsoid of revolution, no round trip
                        continue
                    # X_ITE's iteration stops when the height moves by under 1 mm: so does the round trip
                    self.assertLess(abs(back[0] - point[0]), 1e-4)
                    self.assertLess(abs(back[1] - point[1]), 1e-4)
                    self.assertLess(abs(back[2] - point[2]), 2e-3)

    def test_utm_round_trip_to_a_metre(self):
        # X_ITE's UTM series is only good to a metre or so (tan ** 8): the round trip says so
        for system in (["UTM", "Z31"], ["UTM", "Z31", "S"], ["UTM", "Z56", "S"], ["UTM", "Z17"]):
            gs = geo.parse_geo_system(system)
            for point in ((5411000.0, 452000.0, 35.0), (100000.0, 500000.0, 0.0), (6000000.0, 380000.0, 10.0)):
                back = geo.from_geocentric(gs, geo.to_geocentric(gs, point))
                self.assertLess(abs(back[2] - point[2]), 1.0)

    def test_the_equator_prime_meridian_is_the_x_axis(self):
        x, y, z = geo.to_geocentric(geo.parse_geo_system(["GD", "WE"]), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(x, 6378137.0, places=6)
        self.assertEqual((y, z), (0.0, 0.0))

    def test_the_pole_comes_back_with_x_ites_latitude_of_pi(self):
        gs = geo.parse_geo_system(["GD", "WE"])
        latitude, longitude, height = geo.from_geocentric(gs, (0.0, 0.0, geo.ELLIPSOIDS["WE"][1] + 10.0))
        self.assertEqual((latitude, longitude), (180.0, 0.0))        # pi radians: X_ITE's pole case, followed
        self.assertAlmostEqual(height, 10.0, places=6)

    def test_a_rotate_y_up_frame_puts_up_on_y_and_the_origin_at_zero(self):
        origin = geo.GeoOrigin(("GD", "WE"), (48.8, 2.3, 0.0), True)
        frame = geo.GeoFrame(["GD", "WE"], origin)
        self.assertTrue(frame.rotated)
        for mine in frame.local((48.8, 2.3, 0.0)):
            self.assertAlmostEqual(mine, 0.0, places=6)
        x, y, z = frame.local((48.8, 2.3, 100.0))
        self.assertAlmostEqual(y, 100.0, places=6)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)
        back = frame.geo((x, y, z))
        for mine, want in zip(back, (48.8, 2.3, 100.0)):
            self.assertAlmostEqual(mine, want, places=6)

    def test_a_frame_without_a_geoorigin_is_geocentric_metres(self):
        frame = geo.GeoFrame(["GD", "WE"], None)
        self.assertEqual(frame.local((0.0, 0.0, 0.0)), (6378137.0, 0.0, 0.0))

    def test_slerp_keeps_the_length_a_lerp_gives(self):
        a, b = (3.0, 4.0, 0.0), (0.0, 0.0, 10.0)
        point = geo.slerp(a, b, 0.5)
        self.assertAlmostEqual(math.hypot(*point), 7.5, places=9)


class HostileInput(unittest.TestCase):
    """Never raises: a number X_ITE's JavaScript turns into NaN is a NaN here, and the simulation drops those."""

    NUMBERS = (0.0, -0.0, 1e300, -1e300, 1e-300, math.inf, -math.inf, math.nan, 90.0, -90.0, 180.0, 1e7, -1e7)
    SYSTEMS = (["GD"], ["UTM", "Z31"], ["UTM", "Z31", "S"], ["GC"], ["UTM", "Z99999999999999999999999"], ["GD", "MOON"],
               ["UTM", "easting_first", "Z60", "S"], ["GD", "URANUS"], [])

    def test_no_number_raises(self):
        for system in self.SYSTEMS:
            gs = geo.parse_geo_system(system)
            for a in self.NUMBERS:
                for b in self.NUMBERS[::3]:
                    for c in self.NUMBERS[::4]:
                        with self.subTest(system=system, point=(a, b, c)):
                            point = geo.to_geocentric(gs, (a, b, c))
                            self.assertEqual(len(point), 3)
                            self.assertEqual(len(geo.from_geocentric(gs, (a, b, c))), 3)
                            self.assertEqual(len(geo.up_vector(gs, (a, b, c))), 3)

    def test_frames_and_slerp_never_raise(self):
        for rotate in (False, True):
            for coords in ((math.nan, 0.0, 0.0), (90.0, 0.0, 0.0), (1e300, 1e300, 1e300), (-90.0, 12.0, 0.0)):
                frame = geo.GeoFrame(["GD", "WE"], geo.GeoOrigin(("GD", "WE"), coords, rotate))
                for p in ((0.0, 0.0, 0.0), (math.nan, 1.0, 1.0), (1e300, 0.0, 0.0), (math.inf, 0.0, 0.0)):
                    self.assertEqual(len(frame.local(p)), 3)
                    self.assertEqual(len(frame.geo(p)), 3)
        for a in ((0.0, 0.0, 0.0), (math.nan, 0.0, 0.0), (1e300, 1e300, 0.0), (math.inf, 0.0, 0.0), (1.0, 0.0, 0.0)):
            for b in ((0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (1e-320, 0.0, 0.0), (math.inf, 0.0, 0.0)):
                self.assertEqual(len(geo.slerp(a, b, 0.5)), 3)

    def test_origins_from_markup_survive_nonsense(self):
        o = geo.origin_from_attributes({"geoSystem": "((", "geoCoords": "a b c", "rotateYUp": "maybe"})
        self.assertEqual((o.coords, o.rotate_y_up), ((0.0, 0.0, 0.0), False))
        o = geo.origin_from_attributes({"geoCoords": "nan 0 0"})
        self.assertEqual(o.coords, (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
