# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fibonacci-sphere camera maths of tools/splat_capture.py (no bpy)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from splat_capture import camera_poses, fibonacci_directions, look_at, transforms_json  # noqa: E402


class FibonacciTests(unittest.TestCase):
    def test_unit_vectors_and_even_height(self):
        directions = fibonacci_directions(100)
        for d in directions:
            self.assertAlmostEqual(math.sqrt(sum(c * c for c in d)), 1.0, places=9)
        zs = [d[2] for d in directions]
        self.assertAlmostEqual(sum(zs) / len(zs), 0.0, places=9)          # even in height: mean z is 0
        self.assertAlmostEqual(zs[0] - zs[1], 0.02, places=9)               # equal z steps = equal area bands

    def test_hemisphere_stays_up(self):
        self.assertTrue(all(d[2] > 0 for d in fibonacci_directions(40, hemisphere=True)))

    def test_nearest_neighbour_spread(self):
        directions = fibonacci_directions(200)
        nearest = [min(math.dist(a, b) for j, b in enumerate(directions) if j != i) for i, a in enumerate(directions)]
        self.assertLess(max(nearest) / min(nearest), 1.6)                   # no clumps, no holes


class LookAtTests(unittest.TestCase):
    def test_camera_looks_at_the_target_with_up_upright(self):
        for eye in ((3, 0, 1), (0, -4, 2), (-1, -1, 5), (0, 0, 6)):
            m = look_at(eye, (0, 0, 0))
            forward = [-m[row][2] for row in range(3)]
            to_target = [-e for e in eye]
            length = math.sqrt(sum(c * c for c in to_target))
            for f, t in zip(forward, to_target):
                self.assertAlmostEqual(f, t / length, places=9)
            right, up = [m[row][0] for row in range(3)], [m[row][1] for row in range(3)]
            self.assertAlmostEqual(sum(r * u for r, u in zip(right, up)), 0.0, places=9)   # orthogonal frame
            self.assertGreaterEqual(up[2], 0.0)                                              # upright

    def test_transforms_json_shape(self):
        poses = camera_poses(3, radius=2.0, target=(1, 1, 1))
        document = transforms_json(poses, angle_x=0.7, prefix="train", size=64)
        self.assertEqual([f["file_path"] for f in document["frames"]], ["./train/r_000", "./train/r_001", "./train/r_002"])
        self.assertEqual(len(document["frames"][0]["transform_matrix"]), 4)


if __name__ == "__main__":
    unittest.main()
