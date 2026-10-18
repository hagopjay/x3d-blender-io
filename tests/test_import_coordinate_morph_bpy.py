# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: a CoordinateInterpolator routed to a Coordinate becomes shape keys with keyframed values.

The importer used to ignore ROUTEs into ``Coordinate.point``, so a deforming mesh (the Shroud fold morph: one
interpolator of 63 keys over two 1,105-point cloths) came in frozen at its rest points and the glTF export had no
morph targets. Now every distinct state of the interpolator is one relative shape key whose value is a triangular
pulse (1 at its keys, 0 at the neighbouring keys), so the blend equals the interpolator's linear interpolation.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_coordinate_morph_bpy
"""

from __future__ import annotations

import os
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

CYCLE = 12.0  # seconds; 24 fps puts key 0, 0.25 and 1 at frames 1, 73 and 289 (past Blender's default end frame, 250)
KEYS = [0.0, 0.25, 1.0]

# Eight points on a line, state k lifts point p by LIFT[k][p] along y.
BASE = [(float(p), 0.0, 0.0) for p in range(8)]
LIFT = [[0.0] * 8, [0.5 * (p + 1) for p in range(8)], [0.0] * 8]
LIFT[2][3] = 4.0
STATES = [[(x, y + LIFT[k][p], z) for p, (x, y, z) in enumerate(BASE)] for k in range(3)]


def _text(points_used_index: str) -> str:
    fmt = lambda pts: " ".join("%g %g %g" % q for q in pts)
    return ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>\n"
            "<Shape><IndexedFaceSet coordIndex='%s'><Coordinate DEF='C' point='%s'/></IndexedFaceSet></Shape>\n"
            "<TimeSensor DEF='T' cycleInterval='%g' loop='true'/>\n"
            "<CoordinateInterpolator DEF='I' key='%s' keyValue='%s'/>\n"
            "<ROUTE fromNode='T' fromField='fraction_changed' toNode='I' toField='set_fraction'/>\n"
            "<ROUTE fromNode='I' fromField='value_changed' toNode='C' toField='set_point'/>\n"
            "</Scene></X3D>\n"
            % (points_used_index, fmt(BASE), CYCLE, " ".join(str(k) for k in KEYS),
               ", ".join(fmt(s) for s in STATES)))


def _expected(fraction: float, point: int):
    j = max(i for i, k in enumerate(KEYS[:-1]) if k <= fraction)
    f = (fraction - KEYS[j]) / (KEYS[j + 1] - KEYS[j])
    a, b = STATES[j][point], STATES[j + 1][point]
    return tuple((1 - f) * a[i] + f * b[i] for i in range(3))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class CoordinateMorphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_morph_")
        _register_extension(cls.tmpdir)

    def _import(self, coord_index: str):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, "morph.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_text(coord_index))
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
        return obj

    def _evaluated(self, obj, frame: float):
        scene = bpy.context.scene
        scene.frame_set(int(frame // 1), subframe=frame % 1)
        return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data

    def _check(self, obj, points):
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        start = bpy.context.scene.frame_start
        for fraction in (0.0, 0.125, 0.25, 0.5, 0.75, 1.0):
            mesh = self._evaluated(obj, start + fraction * CYCLE * fps)
            for vertex, point in zip(mesh.vertices, points):
                want = _expected(min(fraction, 0.999999), point) if fraction < 1.0 else STATES[2][point]
                for got, exp in zip(vertex.co, want):
                    self.assertAlmostEqual(got, exp, places=4,
                                           msg="fraction %g point %d" % (fraction, point))

    def test_every_vertex_follows_the_interpolator(self):
        obj = self._import("0 1 2 3 4 5 6 7 -1")
        self.assertEqual(len(obj.data.vertices), 8)
        self.assertEqual(obj["x3d_morph_states"], 3)
        self.assertEqual(obj["x3d_morph_coord"], "C")
        # State 0 is the rest pose, so it is the Basis; the other two states are shape keys.
        self.assertEqual([b.name for b in obj.data.shape_keys.key_blocks], ["Basis", "C_01", "C_02"])
        self._check(obj, range(8))

    def test_culled_mesh_keeps_the_point_mapping(self):
        # 8 points, 3 used: the importer drops the other five and must map the states onto the kept points.
        obj = self._import("5 2 0 -1")
        self.assertEqual(len(obj.data.vertices), 3)
        self.assertEqual(list(obj.data["x3d_point_map"]), [5, 2, 0])
        self._check(obj, [5, 2, 0])

    def test_animation_range_follows_the_timesensor(self):
        self._import("0 1 2 3 4 5 6 7 -1")
        self.assertEqual(bpy.context.scene.frame_end, 289)

    def test_interpolation_is_linear(self):
        obj = self._import("0 1 2 3 4 5 6 7 -1")
        action = obj.data.shape_keys.animation_data.action
        from io_scene_x3d.import_x3d import _action_fcurves
        fcurves = list(_action_fcurves(action))
        self.assertEqual(len(fcurves), 2)
        for fcu in fcurves:
            for kf in fcu.keyframe_points:
                self.assertEqual(kf.interpolation, "LINEAR")


if __name__ == "__main__":
    unittest.main()
