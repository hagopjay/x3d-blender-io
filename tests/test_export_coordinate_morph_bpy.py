# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D 4.0 export: an animated shape key leaves as a CoordinateInterpolator routed into the Coordinate.

The importer turns a CoordinateInterpolator into shape keys (test_import_coordinate_morph_bpy). The export used
to write the pose at the current frame and drop the motion, so X3D to Blender to X3D lost the morph (the Shroud
fold went from 1.5 MB to 0.16 MB). With ``use_animation`` the export now writes the Basis plus one
CoordinateInterpolator whose keys are the shape-key keyframes, and meshes with identical morphs share it.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_coordinate_morph_bpy
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

import numpy as np

from test_roundtrip_bpy import _register_extension
from test_import_coordinate_morph_bpy import BASE, CYCLE, KEYS, STATES, _expected, _text


def _children(root, tag):
    return [e for e in root.iter() if e.tag.split("}")[-1] == tag]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class CoordinateMorphExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_morph_export_")
        _register_extension(cls.tmpdir)

    def _import(self, path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return [o for o in bpy.context.scene.objects if o.type == "MESH"][0]

    def _round_trip(self, coord_index, *, use_animation=True):
        src = os.path.join(self.tmpdir, "morph_src.x3d")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_text(coord_index))
        self._import(src)
        out = os.path.join(self.tmpdir, "morph_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False,
                                                  use_animation=use_animation), {"FINISHED"})
        with open(out, encoding="utf-8") as f:
            text = f.read()
        return out, text, ET.fromstring(text)

    def test_interpolator_and_routes_are_written(self):
        _, _, root = self._round_trip("0 1 2 3 4 5 6 7 -1")
        interpolators = _children(root, "CoordinateInterpolator")
        self.assertEqual(len(interpolators), 1)
        ci = interpolators[0]
        keys = [float(k) for k in ci.get("key").split()]
        self.assertEqual(len(keys), len(KEYS))
        for got, want in zip(keys, KEYS):
            self.assertAlmostEqual(got, want, places=5)
        values = [float(v) for v in ci.get("keyValue").split()]
        self.assertEqual(len(values), len(KEYS) * len(BASE) * 3)
        coords = [c for c in _children(root, "Coordinate") if c.get("DEF")]
        self.assertEqual(len(coords), 1)
        routes = {(r.get("fromNode"), r.get("fromField"), r.get("toNode"), r.get("toField")) for r in _children(root, "ROUTE")}
        timer = _children(root, "TimeSensor")[0]
        self.assertAlmostEqual(float(timer.get("cycleInterval")), CYCLE, places=4)
        self.assertIn((timer.get("DEF"), "fraction_changed", ci.get("DEF"), "set_fraction"), routes)
        self.assertIn((ci.get("DEF"), "value_changed", coords[0].get("DEF"), "set_point"), routes)

    def test_coordinate_holds_the_first_state(self):
        _, _, root = self._round_trip("0 1 2 3 4 5 6 7 -1")
        coord = [c for c in _children(root, "Coordinate") if c.get("DEF")][0]
        values = [float(v) for v in coord.get("point").split()]
        self.assertEqual(len(values), len(BASE) * 3)
        for got, want in zip(values, (c for p in STATES[0] for c in p)):
            self.assertAlmostEqual(got, want, places=5)

    def test_re_import_plays_the_same_motion(self):
        for coord_index, points in (("0 1 2 3 4 5 6 7 -1", range(8)), ("5 2 0 -1", [5, 2, 0])):
            out, _, _ = self._round_trip(coord_index)
            obj = self._import(out)
            scene = bpy.context.scene
            fps = scene.render.fps / scene.render.fps_base
            self.assertGreater(len(obj.data.shape_keys.key_blocks), 1)
            for fraction in (0.0, 0.125, 0.25, 0.5, 0.75):
                frame = scene.frame_start + fraction * CYCLE * fps
                scene.frame_set(int(frame // 1), subframe=frame % 1)
                mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
                got = {tuple(round(c, 4) for c in v.co) for v in mesh.vertices}
                want = {tuple(round(c, 4) for c in _expected(fraction, p)) for p in points}
                self.assertEqual(got, want, msg="%s at %g" % (coord_index, fraction))

    def test_without_animation_nothing_moves(self):
        _, text, _ = self._round_trip("0 1 2 3 4 5 6 7 -1", use_animation=False)
        self.assertNotIn("CoordinateInterpolator", text)
        self.assertNotIn("<ROUTE", text)

    def test_two_meshes_with_one_morph_share_the_interpolator(self):
        src = os.path.join(self.tmpdir, "morph_two.x3d")
        text = _text("0 1 2 3 4 5 6 7 -1")
        text = text.replace("<TimeSensor", ("<Shape><IndexedFaceSet coordIndex='0 1 2 3 4 5 6 7 -1'><Coordinate DEF='C2' point='%s'/></IndexedFaceSet></Shape>\n"
                                           % " ".join("%g %g %g" % p for p in BASE)) + "<TimeSensor", 1)
        text = text.replace("</Scene>", "<ROUTE fromNode='I' fromField='value_changed' toNode='C2' toField='set_point'/>\n</Scene>")
        with open(src, "w", encoding="utf-8") as f:
            f.write(text)
        self._import(src)
        out = os.path.join(self.tmpdir, "morph_two_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False,
                                                  use_animation=True), {"FINISHED"})
        root = ET.parse(out).getroot()
        self.assertEqual(len(_children(root, "CoordinateInterpolator")), 1)
        into_coords = [r for r in _children(root, "ROUTE") if r.get("toField") == "set_point"]
        self.assertEqual(len(into_coords), 2)
        self.assertEqual(len({r.get("fromNode") for r in into_coords}), 1)


if __name__ == "__main__":
    unittest.main()
