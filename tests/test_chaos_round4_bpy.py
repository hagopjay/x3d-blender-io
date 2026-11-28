# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Defects the receipt-to-rule weekly run (28 Nov 2026) found in add-on 2.9.0, kept fixed (chaos round 4, 2.9.1).

* a Sound whose source is an OscillatorSource, or an empty <Sound/>: AttributeError (the url was read before the
  None check);
* an Extrusion whose crossSection points are all equal (ZeroDivisionError) or a single point (TypeError);
* the animation export sampled every object at every frame and called float32 noise motion: a 67 KB level with
  five interpolators exported as 45.5 MB with 497;
* a bold or italic Text entered edit mode, and each mode switch evaluated every text in the scene (43 s for 646).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_chaos_round4_bpy
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))


def _x3d(body: str) -> str:
    return ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Full' version='4.0'><Scene>"
            f"{body}</Scene></X3D>\n")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class WeeklyReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_chaos4_")
        _register_extension(cls.tmpdir)

    def _import(self, name, body):
        import bpy
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_x3d(body))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        return bpy.ops.import_scene.x3d(filepath=path)

    def test_sound_without_a_clip_is_a_silent_speaker(self):
        import bpy
        for name, body in (("osc.x3d", "<Sound><OscillatorSource frequency='440'/></Sound>"),
                           ("empty.x3d", "<Sound/>")):
            with self.subTest(name=name):
                self.assertEqual(self._import(name, body), {"FINISHED"})
                speakers = [o for o in bpy.data.objects if o.type == "SPEAKER"]
                self.assertEqual(len(speakers), 1)
                self.assertIsNone(speakers[0].data.sound)

    def test_degenerate_extrusion_cross_section_is_skipped(self):
        for name, cross in (("equal.x3d", "0 0 0 0 0 0"), ("one.x3d", "1 1")):
            with self.subTest(name=name):
                body = f"<Shape><Extrusion crossSection='{cross}' spine='0 0 0 0 1 0'/></Shape>"
                self.assertEqual(self._import(name, body), {"FINISHED"})
        # a flat but not degenerate crossSection (all on one line) still imports, with a cap scale
        self.assertEqual(self._import("line.x3d", "<Shape><Extrusion crossSection='0 0 1 0 2 0' "
                                                  "spine='0 0 0 0 1 0'/></Shape>"), {"FINISHED"})

    def test_bold_text_is_bold_and_many_texts_import_fast(self):
        import bpy
        texts = "".join(f"<Transform translation='{i} 0 0'><Shape><Text string='\"t{i}\"'/></Shape></Transform>"
                        for i in range(150))
        bold = "<Shape><Text string='\"B\"'><FontStyle style='BOLD'/></Text></Shape>"
        t0 = time.time()
        self.assertEqual(self._import("texts.x3d", texts + bold + bold), {"FINISHED"})
        self.assertLess(time.time() - t0, 30.0)
        fonts = [o for o in bpy.data.objects if o.type == "FONT"]
        self.assertEqual(len(fonts), 152)
        bolds = [o for o in fonts if any(f.use_bold for f in o.data.body_format)]
        self.assertEqual(len(bolds), 2)
        self.assertFalse(any("bold" in o.data for o in fonts))

    def test_animation_export_writes_only_what_moves(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 241
        bpy.ops.object.empty_add()
        mover = bpy.context.object
        mover.name = "Mover"
        mover.location = (0, 0, 0)
        mover.keyframe_insert("location", frame=1)
        mover.location = (10, 0, 0)
        mover.keyframe_insert("location", frame=241)
        from extract import _action_fcurves
        for fcurve in _action_fcurves(mover.animation_data.action):
            for point in fcurve.keyframe_points:
                point.interpolation = "LINEAR"
        for i in range(20):
            bpy.ops.mesh.primitive_cube_add(location=(0, i, 0))
            child = bpy.context.object
            child.name = f"Rider{i}"
            child.parent = mover
        bpy.ops.mesh.primitive_cube_add(location=(5, 5, 5))
        bpy.context.object.name = "Still"
        out = os.path.join(self.tmpdir, "anim.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, use_animation=True, use_hierarchy=True),
                         {"FINISHED"})
        text = Path(out).read_text(encoding="utf-8")
        interpolators = re.findall(r'<PositionInterpolator DEF="([^"]+)" key="([^"]*)"', text)
        self.assertEqual(len(interpolators), 1, [name for name, _ in interpolators])
        self.assertIn("Mover", interpolators[0][0])     # 2.9.0 also sampled the 20 riders and the still cube


if __name__ == "__main__":
    unittest.main()
