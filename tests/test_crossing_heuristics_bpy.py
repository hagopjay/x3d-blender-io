# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The crossing census's first three heuristics (docs/CROSSING_CENSUS.md), held by tests.

1. A shape key moved by a driver crosses as a CoordinateInterpolator, like a keyed one.
2. No silent losses: a skipped object type, a custom property, a procedural texture on a Principled input and an
   emission strength above 1 each move the loss receipt; their baselines (nothing to lose) do not.
3. Animation under the default options: still off by default, but an object that moves puts an entry in the receipt
   and a line in the diagnostics.

Each loss is measured against the same scene without it, through the receipt line in the file's head. Skipped when
``bpy`` is not importable::

    cd tests && python -m unittest test_crossing_heuristics_bpy
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

from test_roundtrip_bpy import _register_extension


def _receipt(text):
    m = re.search(r'name="x3d-blender-io\.receipt" content="[^"]*dropped=(\d+) approximated=(\d+) clamped=(\d+)', text)
    return tuple(int(v) for v in m.groups()) if m else None


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class CrossingHeuristicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_crossing_")
        _register_extension(cls.tmpdir)

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 24

    def _cube(self):
        bpy.ops.mesh.primitive_cube_add()
        return bpy.context.object

    def _export(self, name, **options):
        path = os.path.join(self.tmpdir, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, **options), {"FINISHED"})
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _principled(self, obj):
        mat = bpy.data.materials.new("M")
        mat.use_nodes = True
        obj.data.materials.append(mat)
        return mat, next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")

    # 1 -- driven shape keys

    def _driven_shape_key(self):
        obj = self._cube()
        obj.shape_key_add(name="Basis")
        tall = obj.shape_key_add(name="Tall")
        for point in tall.data:
            point.co.z *= 2.5
        driver = tall.driver_add("value").driver
        driver.type, driver.expression = "SCRIPTED", "frame / 24"
        return obj

    def test_a_shape_key_moved_by_a_driver_crosses_as_a_coordinate_interpolator(self):
        self._driven_shape_key()
        root = ET.fromstring(self._export("driven.x3d", use_animation=True))
        interpolators = [e for e in root.iter() if e.tag == "CoordinateInterpolator"]
        self.assertEqual(len(interpolators), 1)
        keys = interpolators[0].get("key").split()
        self.assertGreater(len(keys), 2, "a driver is sampled every frame_step frame, not only at its two ends")
        values = [float(v) for v in interpolators[0].get("keyValue").split()]
        per_key = len(values) // len(keys)
        # the highest vertex of each sampled state: coordinates stay in the mesh's own axes (the axis conversion is
        # on the Transform above), so up is the third component
        tops = [max(values[k * per_key + 2:(k + 1) * per_key:3]) for k in range(len(keys))]
        self.assertAlmostEqual(tops[0], 1.0 + 1.5 / 24, delta=0.02)    # frame 1: the driver says 1/24 of Tall
        self.assertAlmostEqual(tops[-1], 2.5, delta=0.02)              # frame 24: all of Tall
        self.assertEqual(tops, sorted(tops), "the driver only grows, so each state is at least as tall as the last")

    def test_a_keyed_shape_key_still_crosses(self):
        obj = self._cube()
        obj.shape_key_add(name="Basis")
        tall = obj.shape_key_add(name="Tall")
        for point in tall.data:
            point.co.z *= 2.5
        tall.value = 0.0
        tall.keyframe_insert("value", frame=1)
        tall.value = 1.0
        tall.keyframe_insert("value", frame=24)
        self.assertIn("<CoordinateInterpolator", self._export("keyed.x3d", use_animation=True))

    # 2 -- no silent losses

    def test_a_plain_cube_loses_nothing(self):
        self._cube()
        self.assertEqual(_receipt(self._export("plain.x3d")), (0, 0, 0))

    def test_a_skipped_grease_pencil_object_is_counted(self):
        self._cube()
        gp = bpy.data.grease_pencils.new("Ink")
        bpy.context.collection.objects.link(bpy.data.objects.new("Ink", gp))
        dropped, _, _ = _receipt(self._export("gp.x3d"))
        self.assertEqual(dropped, 1)

    def test_a_custom_property_is_counted_and_the_addons_own_are_not(self):
        obj = self._cube()
        obj["x3d_def"] = "Box"                                         # the add-on's bookkeeping: carried as DEF
        self.assertEqual(_receipt(self._export("own.x3d"))[0], 0)
        obj["note"] = "keep me"
        self.assertEqual(_receipt(self._export("custom.x3d"))[0], 1)

    def test_a_procedural_texture_is_counted_and_an_image_texture_is_not(self):
        obj = self._cube()
        mat, bsdf = self._principled(obj)
        image = bpy.data.images.new("grid", 8, 8)
        image.filepath_raw = os.path.join(self.tmpdir, "grid.png")
        image.file_format = "PNG"
        image.save()
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        link = mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        self.assertEqual(_receipt(self._export("image.x3d"))[0], 0)
        mat.node_tree.links.remove(link)
        noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
        mat.node_tree.links.new(noise.outputs["Color"], bsdf.inputs["Base Color"])
        self.assertEqual(_receipt(self._export("noise.x3d"))[0], 1)

    def test_emission_strength_above_one_is_counted_as_clamped(self):
        obj = self._cube()
        _, bsdf = self._principled(obj)
        bsdf.inputs["Emission Color"].default_value = (0.2, 0.9, 1.0, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 1.0
        self.assertEqual(_receipt(self._export("e1.x3d"))[2], 0)
        bsdf.inputs["Emission Strength"].default_value = 5.0
        self.assertEqual(_receipt(self._export("e5.x3d"))[2], 1)

    # 3 -- animation under the default options

    def test_animation_left_out_by_default_is_said(self):
        obj = self._cube()
        for frame, x in ((1, 0.0), (24, 2.0)):
            obj.location.x = x
            obj.keyframe_insert("location", frame=frame)
        text = self._export("default.x3d")
        self.assertNotIn("<PositionInterpolator", text, "use_animation stays off by default")
        self.assertEqual(_receipt(text)[0], 1)
        text = self._export("on.x3d", use_animation=True)
        self.assertIn("<PositionInterpolator", text)
        self.assertEqual(_receipt(text)[0], 0, "with Animation on nothing is left out")

    def test_a_still_scene_says_nothing_about_animation(self):
        self._cube()
        self.assertEqual(_receipt(self._export("still.x3d"))[0], 0)


if __name__ == "__main__":
    unittest.main()
