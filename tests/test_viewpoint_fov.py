# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from viewpoint_fov import blender_camera_angle, x3d_field_of_view


class ViewpointFovTests(unittest.TestCase):
    def test_landscape_auto_fit_uses_the_vertical_angle(self):
        # 50 mm lens on a 36 mm sensor, 16:9: Blender's 39.6 deg is horizontal; X3D wants the vertical 22.9 deg.
        angle = 2 * math.atan(18 / 50)
        fov = x3d_field_of_view(angle, "AUTO", 1920, 1080)
        self.assertAlmostEqual(math.degrees(fov), 22.8952, places=3)

    def test_square_and_portrait(self):
        self.assertAlmostEqual(x3d_field_of_view(0.8, "AUTO", 512, 512), 0.8)
        # portrait AUTO fit: Blender's angle spans the taller side, X3D's the narrower width
        self.assertLess(x3d_field_of_view(0.8, "AUTO", 1080, 1920), 0.8)
        # vertical fit on a landscape render: the angle is already across the smaller side
        self.assertAlmostEqual(x3d_field_of_view(0.8, "VERTICAL", 1920, 1080), 0.8)

    def test_round_trip(self):
        for fit in ("AUTO", "HORIZONTAL", "VERTICAL"):
            for w, h in ((1920, 1080), (1080, 1920), (800, 800), (640, 360)):
                for angle in (0.3, 0.69, 1.2):
                    back = blender_camera_angle(x3d_field_of_view(angle, fit, w, h), fit, w, h)
                    self.assertAlmostEqual(back, angle, places=9, msg=(fit, w, h, angle))


if __name__ == "__main__":
    unittest.main()
