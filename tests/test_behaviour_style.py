# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Editor style (source/behaviour_style.py): node families, event colours, and Classic giving every node its own
colour back. The colour and family helpers are plain Python; the paint test needs bpy (skipped without it)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
import behaviour_style as st  # noqa: E402

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False


class _Style:
    def __init__(self, theme="CLASSIC", rainbow=False, sparkle=False, packet_size=1.0, glow=1.0, trail=1.0):
        self.theme, self.rainbow, self.sparkle = theme, rainbow, sparkle
        self.packet_size, self.glow, self.trail = packet_size, glow, trail


class StyleHelpers(unittest.TestCase):
    def test_families(self):
        cases = {"TimeSensor": "timer", "TouchSensor": "sensor", "PositionInterpolator": "interpolator",
                 "EaseInEaseOut": "interpolator", "ColorChaser": "follower", "PositionDamper2D": "follower",
                 "BooleanToggle": "logic", "TimeTrigger": "logic", "Script": "script", "Transform": "scene",
                 "HAnimJoint": "scene", "PhysicalMaterial": "look", "TextureTransform": "look",
                 "PointLight": "light", "OrthoViewpoint": "camera", "Shape": "other"}
        for x3d_type, family in cases.items():
            with self.subTest(x3d_type=x3d_type):
                self.assertEqual(st.family(x3d_type), family)

    def test_classic_leaves_an_events_colour_alone(self):
        base = (0.95, 0.70, 0.20)
        self.assertEqual(st.field_colour(base, "SFTime", 3.0, _Style()), base)
        self.assertEqual(st.scales(_Style()), (1.0, 1.0, 1.0))

    def test_themes_change_colours_and_stay_in_range(self):
        base = (0.95, 0.70, 0.20)
        for theme in ("NEON", "SYNTHWAVE", "PASTEL", "CANDY", "MONO"):
            with self.subTest(theme=theme):
                colour = st.field_colour(base, "SFTime", 3.0, _Style(theme))
                self.assertNotEqual(tuple(round(c, 3) for c in colour), base)
                self.assertTrue(all(0.0 <= c <= 1.0 for c in colour), colour)

    def test_rainbow_moves_with_time(self):
        style = _Style("NEON", rainbow=True)
        self.assertNotEqual(st.field_colour((1, 0, 0), "SFBool", 0.0, style), st.field_colour((1, 0, 0), "SFBool", 1.0, style))

    def test_every_theme_colours_every_family_readably(self):
        for theme, palette in st.NODE_COLOURS.items():
            for family in st.FAMILIES:
                with self.subTest(theme=theme, family=family):
                    self.assertTrue(max(palette[family]) <= 0.5, "dark enough for the node's text to read")

    def test_sparkles_sit_on_the_link(self):
        points = [(0.0, 0.0), (10.0, 0.0)]
        for (x, y), bright in st.sparkle_points(points, 2.0):
            self.assertTrue(0.0 <= x <= 10.0 and y == 0.0 and 0.0 <= bright <= 1.0)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class StylePaint(unittest.TestCase):
    def test_classic_gives_every_node_its_own_colour_back(self):
        import bpy
        from test_roundtrip_bpy import _register_extension
        _register_extension(tempfile.mkdtemp(prefix="x3d_style_"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(tempfile.mkdtemp(prefix="x3d_style_"))
        world = Path(__file__).resolve().parent / "behaviour" / "door.x3d"
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(world), use_behaviour_graph=True), {"FINISHED"})
        tree = bpy.context.scene.x3d_behaviour_tree
        before = {n.name: (n.use_custom_color, tuple(round(c, 4) for c in n.color)) for n in tree.nodes}
        for preset in ("PARTY", "CALM", "SURPRISE"):
            bpy.ops.x3d.style_preset(preset=preset)
            self.assertTrue(all(n.use_custom_color for n in tree.nodes if getattr(n, "x3d_type", None)))
        bpy.ops.x3d.style_preset(preset="CLASSIC")
        after = {n.name: (n.use_custom_color, tuple(round(c, 4) for c in n.color)) for n in tree.nodes}
        self.assertEqual(after, before)
        self.assertFalse(any(st.ORIGINAL in n for n in tree.nodes))


if __name__ == "__main__":
    unittest.main()
