# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from ir import IRGaussianSplats
from splat_io import (
    read_antimatter_splat, read_ply, read_splats, rgb_to_sh0, sh0_to_rgb, write_antimatter_splat, write_ply,
)


def _sample(count=5, degree=2):
    splats = IRGaussianSplats(name="sample")
    for i in range(count):
        splats.positions.append((i * 0.5, -i, 2.0))
        splats.scales.append((0.01 * (i + 1), 0.02, 0.5))
        splats.orientations.append((0.0, 0.6, 0.0, 0.8))
        splats.opacities.append(0.1 + 0.2 * i)
        splats.sh[(0, 0)] = splats.sh.get((0, 0), []) + [rgb_to_sh0((0.2 * i, 0.5, 1.0 - 0.1 * i))]
        for d in range(1, degree + 1):
            for c in range(2 * d + 1):
                splats.sh.setdefault((d, c), []).append((0.01 * d, 0.001 * c, -0.02 * i))
    return splats


class SplatIOTests(unittest.TestCase):
    def test_sh0_rgb_round_trip(self):
        rgb = (0.1, 0.5, 0.9)
        back = sh0_to_rgb(rgb_to_sh0(rgb))
        for a, b in zip(rgb, back):
            self.assertAlmostEqual(a, b, places=6)

    def test_ply_round_trip_keeps_values(self):
        splats = _sample()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s.ply")
            write_ply(path, splats)
            header = Path(path).read_bytes().split(b"end_header")[0].decode()
            self.assertIn("property float f_rest_23", header)  # 3 channels x 8 coefficients for degree 2
            back = read_ply(path)
        self.assertEqual(len(back), 5)
        self.assertEqual(back.sh_degree(), 2)
        for i in range(5):
            for a, b in zip(back.positions[i], splats.positions[i]):
                self.assertAlmostEqual(a, b, places=5)
            for a, b in zip(back.scales[i], splats.scales[i]):
                self.assertAlmostEqual(a, b, places=5)
            for a, b in zip(back.orientations[i], splats.orientations[i]):
                self.assertAlmostEqual(a, b, places=5)
            self.assertAlmostEqual(back.opacities[i], splats.opacities[i], places=4)
            for a, b in zip(back.sh[(2, 4)][i], splats.sh[(2, 4)][i]):
                self.assertAlmostEqual(a, b, places=5)

    def test_antimatter_splat_round_trip(self):
        splats = _sample(degree=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s.splat")
            write_antimatter_splat(path, splats)
            self.assertEqual(os.path.getsize(path), 32 * 5)
            back = read_antimatter_splat(path)
            again = read_splats(path)
        self.assertEqual(len(back), 5)
        self.assertEqual(len(again), 5)
        for i in range(5):
            for a, b in zip(back.positions[i], splats.positions[i]):
                self.assertAlmostEqual(a, b, places=5)
            self.assertAlmostEqual(back.opacities[i], splats.opacities[i], places=2)
            for a, b in zip(sh0_to_rgb(back.sh[(0, 0)][i]), sh0_to_rgb(splats.sh[(0, 0)][i])):
                self.assertAlmostEqual(a, b, places=2)
            for a, b in zip(back.orientations[i], splats.orientations[i]):
                self.assertAlmostEqual(a, b, places=1)

    def test_rgb_ply_without_sh_columns(self):
        text = "ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\n" \
               "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n0 0 0 255 0 0\n1 1 1 0 0 255\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "rgb.ply")
            Path(path).write_text(text)
            back = read_ply(path)
        self.assertEqual(len(back), 2)
        self.assertEqual(back.opacities, [1.0, 1.0])
        r, g, b = sh0_to_rgb(back.sh[(0, 0)][0])
        self.assertAlmostEqual(r, 1.0, places=5)
        self.assertAlmostEqual(b, 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
