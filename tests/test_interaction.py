# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The custom-property reader and the tour timeline of source/interaction.py (no bpy)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

from interaction import read_interaction, read_tour, tour_timeline  # noqa: E402
from ir import IRTransform  # noqa: E402


class Obj(dict):
    def __init__(self, name, **props):
        super().__init__(props)
        self.name = name


class ReadInteractionTests(unittest.TestCase):
    def test_no_trigger_no_interaction(self):
        self.assertIsNone(read_interaction(Obj("A")))

    def test_click_animate_targets_itself_by_default(self):
        it = read_interaction(Obj("Door", x3d_trigger="click"))
        self.assertEqual((it.trigger, it.action, it.target), ("click", "animate", "Door"))

    def test_proximity_radius(self):
        it = read_interaction(Obj("Pad", x3d_trigger="Proximity", x3d_action="tour", x3d_radius=4))
        self.assertEqual((it.trigger, it.action, it.radius), ("proximity", "tour", 4.0))

    def test_bad_values_are_reported_not_guessed(self):
        notes = []
        self.assertIsNone(read_interaction(Obj("A", x3d_trigger="hover"), notes))
        self.assertIsNone(read_interaction(Obj("B", x3d_trigger="click", x3d_action="explode"), notes))
        self.assertIsNone(read_interaction(Obj("C", x3d_trigger="click", x3d_action="viewpoint"), notes))
        self.assertEqual(len(notes), 3)


class TourTests(unittest.TestCase):
    def _tour(self, **scene):
        cams = [Obj("B", x3d_tour_order=2, x3d_tour_dwell=1), Obj("A", x3d_tour_order=1), Obj("Plain")]
        return read_tour(cams, Obj("Scene", **scene), lambda cam: IRTransform())

    def test_order_and_defaults(self):
        tour = self._tour()
        self.assertEqual([stop.name for stop in tour.stops], ["A", "B"])
        self.assertEqual([stop.dwell for stop in tour.stops], [2.0, 1.0])
        self.assertEqual(tour.travel, 3.0)
        self.assertFalse(tour.loop or tour.autostart)

    def test_no_stops_no_tour(self):
        self.assertIsNone(read_tour([Obj("Plain")], Obj("Scene"), lambda cam: IRTransform()))

    def test_timeline_keys_hold_then_fly(self):
        keys, total = tour_timeline(self._tour(x3d_tour_travel=2))
        self.assertAlmostEqual(total, 2 + 2 + 1)          # dwell A, travel, dwell B
        self.assertEqual([round(k * total, 6) for k in keys], [0, 2, 4, 5])
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
